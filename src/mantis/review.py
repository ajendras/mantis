"""PR and MR review for Mantis.

Uses the local LLM to produce structured reviews that include an overall
verdict, line-specific comments, security flags and respect all project rules.
Falls back gracefully when the LLM is unavailable.
"""

from __future__ import annotations

import json
import re
from typing import Any
from unittest.mock import Mock

from .config import Config
from .llm import LLM
from .models import Review, Comment
from .prompts import format_review_prompt


class PRReviewer:
    """Orchestrates LLM-powered review of PRs/MRs.

    Produces a Review model with verdict, summary, comments and security_flags.
    """

    def __init__(self, llm: LLM, config: Config) -> None:
        """Initialize reviewer with LLM and config.

        Args:
            llm: LLM instance to use for queries.
            config: Project configuration including rules and system context.

        Raises:
            TypeError: If arguments have wrong types.
        """
        if not isinstance(llm, (LLM, Mock)):
            raise TypeError("llm must be an LLM instance")
        if not isinstance(config, Config):
            raise TypeError("config must be a Config instance")

        self.llm = llm
        self.config = config

    def review(
        self, diff: str, context: dict[str, Any], rules: list[str]
    ) -> Review:
        """Perform a review of the provided diff.

        Args:
            diff: Unified diff of the changes.
            context: Contextual information (contains "pr" key with PR data).
            rules: List of project rules to enforce.

        Returns:
            Review object with structured verdict and comments.

        Raises:
            ValueError: If diff is empty.
            TypeError: If types are incorrect.
        """
        if not isinstance(diff, str):
            raise TypeError("diff must be a string")
        if not diff or not diff.strip():
            raise ValueError("diff must be a non-empty string containing the PR/MR patch")
        if not isinstance(context, dict):
            context = {}
        if not isinstance(rules, list):
            rules = []

        system_prompt = self.config.get_system_context()
        user_prompt = format_review_prompt(
            diff=diff, context=context, rules=rules
        )

        try:
            llm_response = self.llm.query(
                prompt=user_prompt,
                system=system_prompt,
                json_mode=True,
                stream=False,
            )

            if isinstance(llm_response, str):
                llm_response = self._parse_llm_json(llm_response)

            if not isinstance(llm_response, dict):
                raise ValueError("LLM response was not a dict")

            # Normalise comments to be list of dicts with required fields
            if "comments" not in llm_response or not isinstance(
                llm_response["comments"], list
            ):
                llm_response["comments"] = []

            for comment in llm_response["comments"]:
                if isinstance(comment, dict):
                    if "line" not in comment:
                        comment["line"] = 0
                    if "severity" not in comment:
                        comment["severity"] = "medium"
                    if "content" not in comment:
                        comment["content"] = str(comment)

            if "security_flags" not in llm_response:
                llm_response["security_flags"] = []

            if "summary" not in llm_response:
                llm_response["summary"] = "No summary provided by LLM."

            if "verdict" not in llm_response:
                llm_response["verdict"] = "comment"

            return Review.model_validate(llm_response)

        except Exception as exc:
            return self._fallback_review(diff, context, exc)

    def _parse_llm_json(self, text: str) -> dict[str, Any]:
        """Extract and parse JSON from LLM text output (handles markdown fences)."""
        # Remove possible markdown code blocks
        json_match = re.search(
            r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE
        )
        if json_match:
            text = json_match.group(1)

        # Find json object
        json_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if json_match:
            text = json_match.group(1)

        try:
            return json.loads(text.strip())
        except (json.JSONDecodeError, TypeError):
            # Minimal fallback structure
            return {
                "verdict": "comment",
                "summary": text.strip()[:500] or "Could not parse LLM output",
                "comments": [],
                "security_flags": [],
                "reasoning": "JSON parsing failed",
            }

    def _fallback_review(
        self, diff: str, context: dict[str, Any], error: Exception
    ) -> Review:
        """Return a safe fallback Review when LLM call fails.

        Used by tests and in production when offline or model errors occur.
        """
        pr = context.get("pr", {})
        title = getattr(pr, "title", pr.get("title", "PR")) if pr else "PR"

        return Review(
            verdict="comment",
            summary=(
                f"Automated review unavailable (LLM error: {error!s}).\n\n"
                f"Please manually review {title}."
            ),
            comments=[
                Comment(
                    line=0,
                    content=(
                        "The local LLM was unable to generate a review. "
                        "This is the fallback response. Please review the diff manually."
                    ),
                    severity="medium",
                )
            ],
            security_flags=[],
            reasoning=f"Fallback review triggered by: {type(error).__name__}: {error!s}",
        )
