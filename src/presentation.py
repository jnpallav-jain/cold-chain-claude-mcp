"""Extract evidence for the reviewer without treating model prose as measured data."""

import json


def evidence_cards(traces):
    cards = []
    for item in traces:
        if item.get("kind") != "tool_result" or item.get("is_error"):
            continue
        content = item.get("content")
        blocks = content if isinstance(content, list) else [{"text": content}]
        for block in blocks:
            try:
                payload = json.loads(block.get("text", ""))
                if payload.get("ok") and isinstance(payload.get("data"), dict):
                    cards.append(
                        {
                            "tool": item["name"].removeprefix("mcp__coldchain__"),
                            "data": payload["data"],
                        }
                    )
            except (ValueError, TypeError, AttributeError):
                continue
    return cards
