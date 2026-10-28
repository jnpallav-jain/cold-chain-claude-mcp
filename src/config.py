"""Central configuration; importing this module opens no external connections."""

from functools import lru_cache
from pathlib import Path
import re
from typing import Literal
from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigurationError(ValueError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
        populate_by_name=True,
        frozen=True,
    )
    sql_host: str = Field(default="localhost", validation_alias="SQL_SERVER_HOST")
    sql_port: int = Field(
        default=1434, ge=1, le=65535, validation_alias="SQL_SERVER_PORT"
    )
    sql_database: str = Field(
        default="cold_chain_claude_mcp", validation_alias="SQL_DATABASE"
    )
    sql_agent_user: str = Field(
        default="USR_CC_CLAUDE_RO", validation_alias="SQL_AGENT_USER"
    )
    sql_agent_password: SecretStr = Field(
        default=SecretStr(""), validation_alias="SQL_AGENT_PASSWORD", repr=False
    )
    sql_admin_user: str = Field(default="sa", validation_alias="SQL_ADMIN_USER")
    sql_admin_password: SecretStr = Field(
        default=SecretStr(""), validation_alias="SQL_ADMIN_PASSWORD", repr=False
    )
    sql_login_timeout: int = Field(
        default=8, ge=1, le=60, validation_alias="SQL_LOGIN_TIMEOUT"
    )
    sql_row_limit: int = Field(
        default=10, ge=1, le=100, validation_alias="SQL_ROW_LIMIT"
    )
    sql_query_timeout: int = Field(
        default=3, ge=1, le=30, validation_alias="SQL_QUERY_TIMEOUT"
    )
    sql_pool_timeout: float = Field(
        default=3, gt=0, le=30, validation_alias="SQL_POOL_TIMEOUT"
    )
    sql_max_chars: int = Field(
        default=8000, ge=100, le=10000, validation_alias="SQL_MAX_CHARS"
    )
    tool_timeout: float = Field(
        default=45, gt=0, le=120, validation_alias="TOOL_TIMEOUT"
    )
    tool_max_attempts: int = Field(
        default=1, ge=1, le=2, validation_alias="TOOL_MAX_ATTEMPTS"
    )
    tool_worker_limit: int = Field(
        default=2, ge=1, le=4, validation_alias="TOOL_WORKER_LIMIT"
    )
    tool_max_output_bytes: int = Field(
        default=16384, ge=512, le=65536, validation_alias="TOOL_MAX_OUTPUT_BYTES"
    )
    claude_max_tool_calls: int = Field(
        default=8, ge=1, le=20, validation_alias="CLAUDE_MAX_TOOL_CALLS"
    )
    claude_max_prompt_chars: int = Field(
        default=6000, ge=100, le=20000, validation_alias="CLAUDE_MAX_PROMPT_CHARS"
    )
    pinecone_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="PINECONE_API_KEY", repr=False
    )
    pinecone_index_name: str = Field(
        default="cold-chain-claude-mcp-sop-local",
        validation_alias="PINECONE_INDEX_NAME",
    )
    pinecone_namespace: str = Field(
        default="sop-v1", validation_alias="PINECONE_NAMESPACE"
    )
    pinecone_cloud: str = Field(default="aws", validation_alias="PINECONE_CLOUD")
    pinecone_region: str = Field(
        default="us-east-1", validation_alias="PINECONE_REGION"
    )
    embedding_mode: Literal["LOCAL", "OPENAI"] = Field(
        default="LOCAL",
        validation_alias=AliasChoices("EMBEDDING_MODE", "Embeddings_model"),
    )
    local_embedding_model: str = Field(
        default="BAAI/bge-m3",
        validation_alias=AliasChoices("LOCAL_EMBEDDING_MODEL", "Local_Embedding_Model"),
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", validation_alias="OPENAI_EMBEDDING_MODEL"
    )
    openai_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="OPENAI_API_KEY", repr=False
    )
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="ANTHROPIC_API_KEY", repr=False
    )
    claude_model: str = Field(default="sonnet", validation_alias="CLAUDE_MODEL")
    claude_max_turns: int = Field(
        default=8, ge=1, le=30, validation_alias="CLAUDE_MAX_TURNS"
    )
    claude_max_budget_usd: float = Field(
        default=0.5, gt=0, le=10, validation_alias="CLAUDE_MAX_BUDGET_USD"
    )
    claude_request_timeout: float = Field(
        default=120, gt=0, le=600, validation_alias="CLAUDE_REQUEST_TIMEOUT"
    )
    approval_operator: str = Field(
        default="dispatcher",
        min_length=1,
        max_length=64,
        validation_alias="APPROVAL_OPERATOR",
    )
    approval_password_hash: SecretStr = Field(
        default=SecretStr(""), validation_alias="APPROVAL_PASSWORD_HASH", repr=False
    )
    approval_db_path: Path = Field(
        default=Path("data/control/approvals.sqlite3"),
        validation_alias="APPROVAL_DB_PATH",
    )
    approval_ttl_seconds: int = Field(
        default=900, ge=30, le=3600, validation_alias="APPROVAL_TTL_SECONDS"
    )
    retrieval_k: int = Field(default=2, ge=1, le=20, validation_alias="RETRIEVAL_K")
    weather_timeout: float = Field(
        default=6, gt=0, le=60, validation_alias="WEATHER_TIMEOUT"
    )
    telemetry_csv_path: Path = Field(
        default=Path("data/sample/synthetic_fleet.csv"),
        validation_alias="TELEMETRY_CSV_PATH",
    )
    policy_dir: Path = Field(default=Path("data/policy"), validation_alias="POLICY_DIR")

    @model_validator(mode="after")
    def protect_resource_names(self):
        if not re.fullmatch(
            r"cold_chain_claude_mcp(?:_[a-z0-9_]+)?", self.sql_database
        ):
            raise ConfigurationError(
                "SQL_DATABASE must use this project's cold_chain_claude_mcp prefix; system and original databases are forbidden."
            )
        if (
            not re.fullmatch(
                r"cold-chain-claude-mcp-[a-z0-9-]+", self.pinecone_index_name
            )
            or len(self.pinecone_index_name) > 45
        ):
            raise ConfigurationError(
                "PINECONE_INDEX_NAME must use this project's cold-chain-claude-mcp- prefix (maximum 45 characters)."
            )
        if not self.pinecone_namespace.strip():
            raise ConfigurationError("PINECONE_NAMESPACE must be nonempty.")
        if self.sql_agent_user != "USR_CC_CLAUDE_RO":
            raise ConfigurationError(
                "Use the dedicated USR_CC_CLAUDE_RO agent account."
            )
        if (
            self.embedding_mode == "LOCAL"
            and self.local_embedding_model != "BAAI/bge-m3"
        ):
            raise ConfigurationError(
                "Only BAAI/bge-m3 is supported by this baseline's 1024-dimensional local index."
            )
        if self.embedding_mode == "OPENAI" and not self.pinecone_index_name.endswith(
            "-openai"
        ):
            raise ConfigurationError(
                "OpenAI embeddings require a separate index ending in -openai."
            )
        return self

    @property
    def embedding_dimension(self):
        return 1024 if self.embedding_mode == "LOCAL" else 1536

    def resolve_path(self, path):
        return path if path.is_absolute() else PROJECT_ROOT / path

    def require(self, *names):
        for name in names:
            value = getattr(self, name)
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            if not value:
                raise ConfigurationError(f"Missing configuration: {name.upper()}")


@lru_cache(maxsize=1)
def get_settings():
    return Settings()
