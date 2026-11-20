"""PR review engine for Mantis.

Generates contextual, line-aware code reviews with security analysis.
Strictly respects project rules and produces structured output suitable
for both human maintainers and downstream automation.
"""

from __future__ import annotations

from typing import Any

from .config import Config
from .llm import LLM
from .models import Comment, Review
from .prompts import format_review_prompt


class PRReviewer:
    """Orchestrates LLM-powered PR reviews.

    Produces a verdict, line-specific comments, security flags, and
    a summary while respecting all project-specific rules.
    """

    def __init__(self, llm: LLM, config: Config) -> None:
        """Initialize the reviewer.

        Args:
            llm: Configured LLM instance.
            config: Mantis configuration (rules, model settings, etc).

        Raises:
            TypeError: If llm or config have incorrect types.
        """
        if not isinstance(llm, LLM):
            raise TypeError("llm must be an LLM instance")
        if not isinstance(config, Config):
            raise TypeError("config must be a Config instance")

        self.llm = llm
        self.config = config

    def review(
        self, diff: str, context: dict[str, Any], rules: list[str]
    ) -> Review:
        """Perform a contextual review of a pull request diff.

        Args:
            diff: Unified diff / patch of the changes (required).
            context: Contextual information (typically contains a PR model).
            rules: List of project rules that must be followed.

        Returns:
            Structured Review containing verdict, comments, security flags,
            summary and reasoning.

        Raises:
            ValueError: If diff is empty.
            TypeError: If context or rules have incorrect types.
        """
        if not isinstance(diff, str) or not diff.strip():
            raise ValueError("diff must be a non-empty string containing the PR patch")
        if not isinstance(context, dict):
            raise TypeError("context must be a dictionary")
        if not isinstance(rules, list):
            rules = self.config.rules

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

            if not isinstance(llm_response, dict):
                raise ValueError("LLM did not return a dictionary")

            # Normalise fields for robust model validation
            if "comments" not in llm_response or not isinstance(
                llm_response.get("comments"), list
            ):
                llm_response["comments"] = []
            if "security_flags" not in llm_response or not isinstance(
                llm_response.get("security_flags"), list
            ):
                llm_response["security_flags"] = []
            if "summary" not in llm_response:
                llm_response["summary"] = llm_response.get(
                    "reasoning", "No summary provided by model."
                )
            if "verdict" not in llm_response:
                llm_response["verdict"] = "comment"

            return Review.model_validate(llm_response)

        except Exception as exc:
            return self._fallback_review(diff, context, exc)

    def _fallback_review(
        self, diff: str, context: dict[str, Any], error: Exception
    ) -> Review:
        """Return a safe default review when the LLM is unavailable.

        Performs lightweight static analysis on the diff for obvious
        security red flags and returns a structured Review.
        """
        diff_lower = diff.lower()
        security_flags: list[str] = []

        suspicious_patterns = [
            ("hardcoded_secret", ["password=", "secret=", "key=", "api_key", "private_key"]),
            ("eval_exec", ["eval(", "exec(", "__import__"]),
            ("sql_injection", ["execute(", "cursor.execute", "sql ="]),
        ]

        for flag, patterns in suspicious_patterns:
            if any(pat in diff_lower for pat in patterns):
                security_flags.append(flag)

        pr_info = context.get("pr") or {}
        title = getattr(pr_info, "title", pr_info.get("title", "Untitled PR"))

        comments = [
            Comment(
                line=0,
                content=(
                    "Automated review could not be completed because the local "
                    "LLM endpoint is unavailable. Please review the changes manually."
                ),
                severity="medium",
            )
        ]

        return Review(
            verdict="comment",
            summary=f"Fallback review for '{title}' (LLM unavailable)",
            comments=comments,
            security_flags=security_flags,
            reasoning=f"Static fallback analysis. Original error: {error!s}",
        )
