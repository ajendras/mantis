"""LLM interface for Mantis.

Provides a clean wrapper around Ollama (or any compatible local endpoint)
with JSON mode, streaming support, robust error handling, and automatic
fallback parsing.
"""

from __future__ import annotations

import json
import re
from typing import Any

import ollama
from ollama import Client


class LLM:
    """Local LLM client using Ollama.

    Supports synchronous queries, JSON-mode structured output, token
    streaming for CLI feedback, and helpful error messages when the
    Ollama server is unavailable.
    """

    def __init__(
        self,
        model: str = "llama3",
        temperature: float = 0.3,
        base_url: str = "http://localhost:11434",
        max_tokens: int = 4096,
    ) -> None:
        """Initialize the LLM client.

        Args:
            model: Name of the Ollama model to use.
            temperature: Sampling temperature (0.0-2.0).
            base_url: Ollama server base URL.
            max_tokens: Maximum tokens to generate.

        Raises:
            ValueError: If model name is empty or temperature is out of range.
        """
        if not model or not isinstance(model, str):
            raise ValueError("model must be a non-empty string")
        if not isinstance(temperature, (int, float)) or temperature < 0.0 or temperature > 2.0:
            raise ValueError("temperature must be a float between 0.0 and 2.0")
        if max_tokens < 256:
            raise ValueError("max_tokens must be at least 256")

        self.model = model
        self.temperature = float(temperature)
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.client = Client(host=self.base_url)

    def query(
        self,
        prompt: str,
        system: str | None = None,
        json_mode: bool = False,
        stream: bool = False,
    ) -> str | dict[str, Any]:
        """Send a prompt to the local LLM and return the response.

        Args:
            prompt: User prompt (required).
            system: Optional system prompt providing context and rules.
            json_mode: Whether to request and parse a JSON response.
            stream: Whether to stream tokens to stdout (useful for CLI).

        Returns:
            str if json_mode=False, otherwise a parsed dict.

        Raises:
            ValueError: On empty prompt or JSON parsing failure.
            RuntimeError: On connection or Ollama errors.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if system is not None and not isinstance(system, str):
            raise TypeError("system must be a string or None")

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        options = {
            "temperature": self.temperature,
            "num_predict": self.max_tokens,
        }

        try:
            format_param = "json" if json_mode else None

            if stream:
                stream_resp = self.client.chat(
                    model=self.model,
                    messages=messages,
                    options=options,
                    format=format_param,
                    stream=True,
                )
                content_parts: list[str] = []
                for chunk in stream_resp:
                    delta = chunk.get("message", {}).get("content", "")
                    print(delta, end="", flush=True)
                    content_parts.append(delta)
                print()  # final newline
                content = "".join(content_parts).strip()
            else:
                resp = self.client.chat(
                    model=self.model,
                    messages=messages,
                    options=options,
                    format=format_param,
                    stream=False,
                )
                content = resp.get("message", {}).get("content", "").strip()

            if json_mode:
                return self._parse_json_response(content)

            return content

        except ollama.ResponseError as exc:
            raise RuntimeError(f"Ollama responded with an error: {exc}") from exc
        except Exception as exc:
            msg = str(exc).lower()
            if "connection" in msg or "connection refused" in msg:
                raise RuntimeError(
                    "Could not connect to Ollama. Make sure `ollama serve` is running "
                    f"and the model '{self.model}' is pulled."
                ) from exc
            raise RuntimeError(f"LLM query failed: {exc}") from exc

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        """Parse JSON from the model, with fallback regex extraction."""
        if not content:
            raise ValueError("Received empty response from LLM")

        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("JSON response was not an object")
        except json.JSONDecodeError:
            # Attempt to extract JSON object from surrounding text
            match = re.search(r"(\{.*\})", content, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass

            raise ValueError(
                "LLM did not return valid JSON. "
                f"First 180 characters: {content[:180]!r}"
            ) from None
