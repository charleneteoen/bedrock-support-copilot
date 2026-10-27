"""Offline stand-in for AsyncAnthropicBedrockMantle, used by COPILOT_MODE=mock and the tests.

It mirrors the slice of the SDK the app uses - `messages.stream(...)` as an async
context manager yielding `text` events, then `get_final_message()` - and scripts
plausible behaviour: order ids trigger lookup_order, refund/damage requests
trigger create_support_ticket, anything else is answered from the retrieved context.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from types import SimpleNamespace
from typing import Any

ORDER_RE = re.compile(r"\b([A-Za-z]\d{4})\b")
ESCALATE_RE = re.compile(r"\b(refund|replace|replacement|damaged|broken|human|agent)\b", re.I)
TOKEN_DELAY_S = 0.02


def _question(content: str) -> str:
    return content.split("Customer question:", 1)[-1].strip()


def _first_passage(content: str) -> str | None:
    m = re.search(r"<passage[^>]*>\n(.*?)\n</passage>", content, re.S)
    if not m:
        return None
    body = re.sub(r"^#+ .*\n", "", m.group(1)).strip()
    return " ".join(body.split())[:400]


class _Stream:
    def __init__(self, text: str, tool_use: dict | None):
        self._text = text
        self._tool_use = tool_use

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for word in self._text.split(" "):
            await asyncio.sleep(TOKEN_DELAY_S)
            yield SimpleNamespace(type="text", text=word + " ")

    async def get_final_message(self):
        content = []
        if self._text:
            content.append({"type": "text", "text": self._text + " "})
        if self._tool_use:
            content.append({"type": "tool_use", **self._tool_use})
        blocks = [SimpleNamespace(**c) for c in content]
        return SimpleNamespace(
            content=blocks,
            stop_reason="tool_use" if self._tool_use else "end_turn",
            usage=SimpleNamespace(
                input_tokens=420, output_tokens=max(1, len(self._text.split())), cache_read_input_tokens=380
            ),
            to_dict=lambda: {"content": content},
        )


class _Messages:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs) -> _Stream:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        last = kwargs["messages"][-1]
        content = last["content"]

        if isinstance(content, list):  # tool results came back
            result = json.loads(content[0]["content"])
            if content[0].get("is_error"):
                return _Stream(f"I couldn't find that: {result['error']}. Could you double-check the order id?", None)
            if "ticket_id" in result:
                return _Stream(
                    f"I've opened ticket {result['ticket_id']} with {result['priority']} priority. "
                    "A support specialist will email you within one business day.",
                    None,
                )
            eta = f", expected {result['eta']}" if result.get("eta") else ""
            carrier = f" via {result['carrier']}" if result.get("carrier") else ""
            return _Stream(
                f"Order {result['order_id']} ({', '.join(result['items'])}) is {result['status']}{carrier}{eta}.",
                None,
            )

        question = _question(content)
        tool_id = f"toolu_{uuid.uuid4().hex[:12]}"
        order = ORDER_RE.search(question)
        if ESCALATE_RE.search(question):
            return _Stream(
                "I'm sorry about that - let me get a specialist involved.",
                {"id": tool_id, "name": "create_support_ticket", "input": {
                    "summary": question[:200], "priority": "high", "order_id": order.group(1).upper() if order else "",
                }},
            )
        if order:
            return _Stream("Let me check that order for you.", {
                "id": tool_id, "name": "lookup_order", "input": {"order_id": order.group(1).upper()},
            })
        passage = _first_passage(content)
        if passage:
            return _Stream(f"Here's what I found: {passage}", None)
        return _Stream("I don't have information on that. Would you like me to open a ticket with our team?", None)


class MockBedrockClient:
    def __init__(self):
        self.messages = _Messages()
