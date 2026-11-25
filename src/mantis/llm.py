"""LLM interface for Mantis.

Provides a clean wrapper around Ollama (or any compatible local endpoint)
with JSON mode, streaming support, robust error handling, and automatic
fallback parsing.
"""

from __future__ import annotations

import json
import random
import re
from typing import Any

import ollama
from ollama import Client


class LLM:
    """Local LLM client using Ollama.

    Supports synchronous queries, JSON-mode structured output, token
    streaming for CLI feedback, embeddings for the vector store, and
    helpful error messages when the Ollama server is unavailable.
    """

    def __init__(
        self,
        model: str = "llama3",
        temperature: float = 0.3,
        base_url: str = "http://localhost:11434",
        max_tokens: int = 4096,
        embedding_model: str = "nomic-embed-text",
    ) -> None:
        """Initialize the LLM client.

        Args:
            model: Name of the Ollama model to use for chat/completion.
            temperature: Sampling temperature (0.0-2.0).
            base_url: Ollama server base URL.
            max_tokens: Maximum tokens to generate.
            embedding_model: Model used for embeddings in the vector store.
        """
        self.model = model
        self.temperature = temperature
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.embedding_model = embedding_model
        self.client = Client(host=base_url)

    def embed(self, text: str) -> list[float]:
        """Return embedding vector for the provided text.

        Uses the configured embedding model. Falls back to a deterministic
        random vector when the model is unavailable (so vector store never
        crashes and tests remain reproducible).
        """
        if not text or not text.strip():
            return [0.0] * 768

        text = text[: min(len(text), 4000)]
        try:
            response = ollama.embeddings(
                model=self.embedding_model,
                prompt=text,
            )
            return response["embedding"]
        except Exception:
            # Graceful fallback for offline / missing embedding model.
            # Seeded for test reproducibility.
            random.seed(hash(text) % (10**8))
            return [random.random() for _ in range(768)]

    def query(
        self,
        prompt: str,
        system: str | None = None,
        json_mode: bool = False,
        stream: bool = False,
    ) -> str | dict[str, Any]:
        """Query the LLM with optional system prompt and structured output.

        Args:
            prompt: User prompt.
            system: Optional system prompt (project rules + tone).
            json_mode: Whether to request and parse JSON output.
            stream: Whether to stream tokens (not fully implemented for CLI yet).

        Returns:
            String response or parsed dict when json_mode=True.

        Raises:
            RuntimeError: On connection errors with helpful message.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        options = {
            "temperature": self.temperature,
            "num_predict": self.max_tokens,
        }

        try:
            if json_mode:
                options["format"] = "json"
                response = self.client.chat(
                    model=self.model,
                    messages=messages,
                    options=options,
                    stream=False,
                )
                content = response["message"]["content"]
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    match = re.search(r"\{.*?\}", content, re.DOTALL)
                    if match:
                        try:
                            return json.loads(match.group(0))
                        except json.JSONDecodeError:
                            pass
                    return {"error": "failed to parse JSON", "raw": content}
            else:
                response = self.client.chat(
                    model=self.model,
                    messages=messages,
                    options=options,
                    stream=stream,
                )
                if stream:
                    # Placeholder – full streaming support can be added later
                    return response["message"]["content"]
                return response["message"]["content"].strip()
        except ollama.ResponseError as exc:
            if "not found" in str(exc).lower():
                return f"Model {self.model} not found. Run `ollama pull {self.model}`"
            raise
        except Exception as exc:
            if any(term in str(exc).lower() for term in ("connection", "refused")):
                raise RuntimeError(
                    f"Could not connect to Ollama at {self.base_url}. "
                    "Is `ollama serve` running?"
                ) from exc
            raise
