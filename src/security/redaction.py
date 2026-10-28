"""Redact configured secrets before exposing data in events, tools, or logs."""

from dataclasses import asdict, is_dataclass
import re
from pydantic import SecretStr


class Redactor:
    def __init__(self, settings):
        values = []
        for name in type(settings).model_fields:
            value = getattr(settings, name)
            if isinstance(value, SecretStr) and value.get_secret_value():
                values.append(value.get_secret_value())
        self.secrets = tuple(sorted(set(values), key=len, reverse=True))

    def text(self, value):
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(
            r"(?i)\b(?:PWD|PASSWORD|UID|USER ID|API_KEY|API-KEY|AUTHORIZATION)\s*[=:]\s*[^;\s]+",
            "[REDACTED_CREDENTIAL]",
            value,
        )
        value = re.sub(r"\b(?:sk-ant-|pcsk_)[A-Za-z0-9_-]{8,}", "[REDACTED_KEY]", value)
        return value

    def data(self, value):
        if isinstance(value, str):
            return self.text(value)
        if is_dataclass(value) and not isinstance(value, type):
            return self.data(asdict(value))
        if isinstance(value, dict):
            return {self.text(str(key)): self.data(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.data(item) for item in value]
        return value


class StreamingRedactor:
    """Hold enough suffix to avoid leaking a configured secret split across deltas."""

    def __init__(self, redactor):
        self.redactor = redactor
        self.buffer = ""
        self.tail = max([len(secret) for secret in redactor.secrets] + [1]) - 1

    def feed(self, text):
        self.buffer += text
        cut = max(0, len(self.buffer) - self.tail)
        for secret in self.redactor.secrets:
            start = 0
            while (position := self.buffer.find(secret, start)) >= 0:
                if position < cut < position + len(secret):
                    cut = position
                start = position + len(secret)
        result = self.redactor.text(self.buffer[:cut])
        self.buffer = self.buffer[cut:]
        return result

    def flush(self):
        result = self.redactor.text(self.buffer)
        self.buffer = ""
        return result
