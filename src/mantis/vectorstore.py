"""Local vector store for persisting and retrieving project conventions.

Uses ChromaDB (persistent) and Ollama embeddings (via LLM.embed) to store
past issues, PRs, labels and decisions. Retrieved context is injected into
triage/review prompts so Mantis continuously learns project-specific style
without bloating every prompt with the full history.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from .llm import LLM


class VectorStore:
    """Persistent vector database for project conventions and history.

    Conservative defaults and graceful degradation when embeddings are
    unavailable.
    """

    def __init__(self, path: Path | str = ".mantis/vectorstore", llm: LLM | None = None) -> None:
        """Initialize the vector store.

        Args:
            path: Directory where ChromaDB will persist its data.
            llm: LLM instance providing embeddings (required for real semantic search).
        """
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(self.path),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name="mantis_conventions",
            metadata={"hnsw:space": "cosine"},
        )
        self.llm = llm

    def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding. Uses LLM or a deterministic fallback."""
        if self.llm is not None:
            return self.llm.embed(text)

        # Test/offline path – deterministic per text for reproducibility
        random.seed(hash(text) % 100000)
        return [random.random() for _ in range(768)]

    def add(
        self, doc_id: str, text: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Add or replace a document (delete first to support updates)."""
        if metadata is None:
            metadata = {}

        embedding = self._get_embedding(text)

        try:
            self.collection.delete(ids=[doc_id])
        except Exception:
            pass  # does not exist

        self.collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )

    def query(
        self, query_text: str, n_results: int = 5, where: dict | None = None
    ) -> list[dict[str, Any]]:
        """Semantic search for similar past items.

        Returns list of dicts containing text, metadata and distance.
        """
        if not query_text or not query_text.strip():
            return []

        embedding = self._get_embedding(query_text)
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        items: list[dict[str, Any]] = []
        for i, doc in enumerate(results.get("documents", [[]])[0]):
            items.append(
                {
                    "text": doc,
                    "metadata": results.get("metadatas", [[]])[0][i],
                    "distance": (
                        results.get("distances", [[]])[0][i]
                        if results.get("distances")
                        else 0.0
                    ),
                }
            )
        return items

    def learn_from_items(self, items: list[dict[str, Any]]) -> int:
        """Index a list of issues/PRs (from API) into the vector store.

        Returns the number of items successfully added.
        """
        count = 0
        for item in items:
            number = item.get("number") or item.get("iid") or item.get("id")
            if not number:
                continue

            title = item.get("title", "")
            body = item.get("body") or item.get("description", "")
            item_type = "pr" if any(
                kw in str(item).lower()
                for kw in ("pull_request", "merge_request", "pr")
            ) else "issue"

            text = f"{item_type.upper()} #{number}: {title}\n\n{body}"

            labels = item.get("labels") or []
            if labels:
                if isinstance(labels[0] if labels else None, dict):
                    label_names = [lbl.get("name", str(lbl)) for lbl in labels]
                else:
                    label_names = [str(lbl) for lbl in labels]
                text += f"\n\nLabels: {', '.join(label_names)}"

            metadata = {
                "type": item_type,
                "number": int(number),
                "title": title,
                "state": item.get("state", "closed"),
                "html_url": item.get("html_url", ""),
            }

            doc_id = f"{item_type}-{number}"
            self.add(doc_id, text, metadata)
            count += 1

        return count

    def count(self) -> int:
        """Return total number of stored documents."""
        return self.collection.count()
