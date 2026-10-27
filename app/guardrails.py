"""Amazon Bedrock Guardrails, applied to the user's input and the model's output.

Uses the standalone ApplyGuardrail API, so the same policy (PII masking,
denied topics, prompt-attack filters) covers both directions of the chat.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .config import Settings


@dataclass
class GuardrailResult:
    blocked: bool
    text: str  # original text, or the guardrail's replacement/masked text


class Guardrail:
    async def check(self, text: str, source: str) -> GuardrailResult:
        return GuardrailResult(blocked=False, text=text)


class BedrockGuardrail(Guardrail):
    def __init__(self, settings: Settings):
        import boto3

        self._client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
        self._id = settings.guardrail_id
        self._version = settings.guardrail_version

    def _check_sync(self, text: str, source: str) -> GuardrailResult:
        resp = self._client.apply_guardrail(
            guardrailIdentifier=self._id,
            guardrailVersion=self._version,
            source=source,  # "INPUT" or "OUTPUT"
            content=[{"text": {"text": text}}],
        )
        if resp.get("action") != "GUARDRAIL_INTERVENED":
            return GuardrailResult(blocked=False, text=text)
        replacement = " ".join(o.get("text", "") for o in resp.get("outputs", [])).strip()
        return GuardrailResult(blocked=True, text=replacement or "Sorry, I can't help with that request.")

    async def check(self, text: str, source: str) -> GuardrailResult:
        return await asyncio.to_thread(self._check_sync, text, source)


def build_guardrail(settings: Settings) -> Guardrail:
    if settings.guardrail_id and not settings.is_mock:
        return BedrockGuardrail(settings)
    return Guardrail()
