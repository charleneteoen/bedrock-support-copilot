"""Runtime configuration, read once from environment variables."""

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # "bedrock" calls AWS; "mock" runs a scripted model so the app works offline.
    mode: str = field(default_factory=lambda: _env("COPILOT_MODE", "mock"))
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", "us-east-1"))
    model_id: str = field(default_factory=lambda: _env("BEDROCK_MODEL_ID", "anthropic.claude-opus-5-5"))
    effort: str = field(default_factory=lambda: _env("MODEL_EFFORT", "low"))
    max_tokens: int = field(default_factory=lambda: int(_env("MAX_TOKENS", "8000")))

    # Optional AWS integrations - each is skipped when its id is empty.
    knowledge_base_id: str = field(default_factory=lambda: _env("KNOWLEDGE_BASE_ID"))
    guardrail_id: str = field(default_factory=lambda: _env("GUARDRAIL_ID"))
    guardrail_version: str = field(default_factory=lambda: _env("GUARDRAIL_VERSION", "DRAFT"))
    sessions_table: str = field(default_factory=lambda: _env("SESSIONS_TABLE"))
    orders_table: str = field(default_factory=lambda: _env("ORDERS_TABLE"))

    retrieval_top_k: int = field(default_factory=lambda: int(_env("RETRIEVAL_TOP_K", "4")))
    max_tool_rounds: int = field(default_factory=lambda: int(_env("MAX_TOOL_ROUNDS", "5")))

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"


settings = Settings()
