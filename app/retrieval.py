"""Retrieval-augmented generation: Bedrock Knowledge Bases, with a local fallback.

With KNOWLEDGE_BASE_ID set, queries go to the Bedrock Knowledge Base (vector
search over documents synced from S3). Without it, a small keyword scorer runs
over the markdown files in ./knowledge so the demo works offline.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"the", "a", "an", "is", "are", "to", "of", "and", "or", "i", "my", "do", "how", "what", "can", "for", "in", "it"}


@dataclass
class Passage:
    text: str
    source: str
    score: float


class Retriever:
    async def retrieve(self, query: str) -> list[Passage]:
        raise NotImplementedError


class KnowledgeBaseRetriever(Retriever):
    def __init__(self, settings: Settings):
        import boto3

        self._client = boto3.client("bedrock-agent-runtime", region_name=settings.aws_region)
        self._kb_id = settings.knowledge_base_id
        self._top_k = settings.retrieval_top_k

    def _retrieve_sync(self, query: str) -> list[Passage]:
        resp = self._client.retrieve(
            knowledgeBaseId=self._kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": self._top_k}},
        )
        passages = []
        for r in resp.get("retrievalResults", []):
            location = r.get("location", {})
            uri = location.get("s3Location", {}).get("uri") or location.get("type", "kb")
            passages.append(Passage(text=r["content"]["text"], source=uri, score=float(r.get("score", 0.0))))
        return passages

    async def retrieve(self, query: str) -> list[Passage]:
        # boto3 is synchronous; keep the event loop free for other WebSocket clients.
        return await asyncio.to_thread(self._retrieve_sync, query)


class LocalRetriever(Retriever):
    def __init__(self, top_k: int = 4, directory: Path = KNOWLEDGE_DIR):
        self._top_k = top_k
        self._chunks: list[tuple[str, str, set[str]]] = []
        for path in sorted(directory.glob("*.md")):
            # One chunk per "## " section, prefixed with the document title for context.
            head, *sections = path.read_text().split("\n## ")
            title = head.strip().lstrip("# ").strip()
            for section in sections:
                chunk = f"{title} - {section.strip()}"
                self._chunks.append((chunk, path.name, _tokens(chunk)))

    async def retrieve(self, query: str) -> list[Passage]:
        q = _tokens(query)
        if not q:
            return []
        scored = []
        for text, source, words in self._chunks:
            overlap = len(q & words)
            if overlap:
                scored.append(Passage(text=text, source=source, score=overlap / len(q)))
        scored.sort(key=lambda p: p.score, reverse=True)
        return scored[: self._top_k]


def _stem(word: str) -> str:
    # Crude suffix stripping so "processed"/"process" and "refunds"/"refund" match.
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def build_retriever(settings: Settings) -> Retriever:
    if settings.knowledge_base_id and not settings.is_mock:
        return KnowledgeBaseRetriever(settings)
    return LocalRetriever(top_k=settings.retrieval_top_k)
