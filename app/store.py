"""Conversation history and order data: DynamoDB in AWS, in-memory locally."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from .config import Settings

SESSION_TTL_SECONDS = 24 * 3600

SAMPLE_ORDERS: dict[str, dict[str, Any]] = {
    "A1001": {"order_id": "A1001", "status": "shipped", "carrier": "UPS", "eta": "2026-10-30", "items": ["Noise-cancelling headphones"]},
    "A1002": {"order_id": "A1002", "status": "processing", "carrier": None, "eta": "2026-11-03", "items": ["USB-C dock", "HDMI cable"]},
    "A1003": {"order_id": "A1003", "status": "delivered", "carrier": "FedEx", "eta": "2026-10-20", "items": ["Mechanical keyboard"]},
}


class SessionStore:
    """Stores the Messages-API history (list of {role, content}) per session."""

    def __init__(self):
        self._sessions: dict[str, list[dict]] = {}

    async def load(self, session_id: str) -> list[dict]:
        return list(self._sessions.get(session_id, []))

    async def save(self, session_id: str, messages: list[dict]) -> None:
        self._sessions[session_id] = list(messages)


class DynamoSessionStore(SessionStore):
    def __init__(self, settings: Settings):
        import boto3

        self._table = boto3.resource("dynamodb", region_name=settings.aws_region).Table(settings.sessions_table)

    async def load(self, session_id: str) -> list[dict]:
        resp = await asyncio.to_thread(self._table.get_item, Key={"session_id": session_id})
        item = resp.get("Item")
        return json.loads(item["messages"]) if item else []

    async def save(self, session_id: str, messages: list[dict]) -> None:
        item = {
            "session_id": session_id,
            "messages": json.dumps(messages),
            "expires_at": int(time.time()) + SESSION_TTL_SECONDS,  # DynamoDB TTL attribute
        }
        await asyncio.to_thread(self._table.put_item, Item=item)


class OrderRepository:
    def __init__(self):
        self._orders = dict(SAMPLE_ORDERS)
        self._tickets: list[dict] = []

    async def get_order(self, order_id: str) -> dict | None:
        return self._orders.get(order_id.upper())

    async def create_ticket(self, ticket: dict) -> dict:
        ticket = {"ticket_id": f"T{len(self._tickets) + 5001}", "created_at": int(time.time()), **ticket}
        self._tickets.append(ticket)
        return ticket


class DynamoOrderRepository(OrderRepository):
    def __init__(self, settings: Settings):
        import boto3

        super().__init__()
        self._table = boto3.resource("dynamodb", region_name=settings.aws_region).Table(settings.orders_table)

    async def get_order(self, order_id: str) -> dict | None:
        resp = await asyncio.to_thread(self._table.get_item, Key={"order_id": order_id.upper()})
        return resp.get("Item")


def build_session_store(settings: Settings) -> SessionStore:
    if settings.sessions_table and not settings.is_mock:
        return DynamoSessionStore(settings)
    return SessionStore()


def build_order_repository(settings: Settings) -> OrderRepository:
    if settings.orders_table and not settings.is_mock:
        return DynamoOrderRepository(settings)
    return OrderRepository()
