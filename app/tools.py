"""Tools the model can call, with schema validation before anything runs."""

from __future__ import annotations

import json
import re
from typing import Any

from .store import OrderRepository

ORDER_ID = re.compile(r"^[A-Za-z]\d{3,9}$")

TOOLS: list[dict[str, Any]] = [
    {
        "name": "lookup_order",
        "description": "Look up an order's status, carrier, ETA and items by order id (e.g. A1001). "
        "Use whenever the customer asks about a specific order.",
        "strict": True,
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "Order id such as A1001"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_support_ticket",
        "description": "Escalate to a human agent by creating a support ticket. Use when the customer "
        "asks for a refund/replacement, reports a damaged item, or the issue can't be solved from the docs.",
        "strict": True,
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "One-sentence summary of the issue"},
                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                "order_id": {"type": "string", "description": "Related order id, or empty string"},
            },
            "required": ["summary", "priority", "order_id"],
            "additionalProperties": False,
        },
    },
]


class ToolInputError(ValueError):
    pass


def validate(name: str, args: Any) -> dict:
    """Re-check tool input: with eager input streaming the server doesn't validate it."""
    if not isinstance(args, dict):
        raise ToolInputError("input must be an object")
    if name == "lookup_order":
        oid = args.get("order_id")
        if not isinstance(oid, str) or not ORDER_ID.match(oid):
            raise ToolInputError("order_id must look like A1001")
        return {"order_id": oid}
    if name == "create_support_ticket":
        summary, priority, oid = args.get("summary"), args.get("priority"), args.get("order_id", "")
        if not isinstance(summary, str) or not summary.strip():
            raise ToolInputError("summary is required")
        if priority not in ("low", "normal", "high"):
            raise ToolInputError("priority must be low, normal or high")
        if not isinstance(oid, str):
            raise ToolInputError("order_id must be a string")
        return {"summary": summary.strip()[:500], "priority": priority, "order_id": oid}
    raise ToolInputError(f"unknown tool {name}")


async def run_tool(name: str, args: Any, orders: OrderRepository) -> tuple[str, bool]:
    """Returns (result_json, is_error)."""
    try:
        clean = validate(name, args)
    except ToolInputError as e:
        return json.dumps({"error": str(e)}), True

    if name == "lookup_order":
        order = await orders.get_order(clean["order_id"])
        if order is None:
            return json.dumps({"error": f"No order found with id {clean['order_id']}"}), True
        return json.dumps(order, default=str), False

    ticket = await orders.create_ticket(clean)
    return json.dumps(ticket, default=str), False
