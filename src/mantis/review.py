"""PR review engine for Mantis.

Generates contextual, line-aware code reviews with security analysis.
Strictly respects project rules and produces structured output suitable
for both human maintainers and downstream automation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

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
        if not isinstance(llm, (LLM, Mock)):
            raise TypeError("llm must be an LLM instance")
        if not isinstance(config, Config):
            raise TypeError("config must be a Config instance")

        self.llm = llm
        self.config = config

    def review(
        self,
        diff: str,
        context: dict[str, Any] | None = None,
        rules: list[str] | None = None,
    ) -> Review:
        """Perform a contextual code review of a pull request.

        Generates line-specific comments, an overall verdict, security flags,
        and respects any project-specific rules defined in config.

        Args:
            diff: Unified diff text (patch) of the changes.
            context: Additional PR metadata.
            rules: Project rules (falls back to config.rules).

        Returns:
            Review object containing verdict, list of Comment objects, and security flags.

        Raises:
            ValueError: If diff is empty.
        """
        if not isinstance(diff, str) or not diff.strip():
            raise ValueError("diff must be a non-empty string containing the PR patch")

        if context is None:
            context = {}
        if rules is None:
            rules = self.config.rules

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

            if not isinstance(llm_response, dict):
                raise ValueError("LLM did not return a dictionary")

            # Ensure comments have severity defaults for validation
            if isinstance(llm_response.get("comments"), list):
                for c in llm_response["comments"]:
                    if isinstance(c, dict) and "severity" not in c:
                        c["severity"] = "medium"

            return Review.model_validate(llm_response)

        except Exception as exc:
            return self._fallback_review(diff, exc)

    def _fallback_review(self, diff: str, error: Exception) -> Review:
        """Return a safe default review when the LLM is unavailable."""
        security_flags: list[str] = []
        lower_diff = diff.lower()
        if any(
            kw in lower_diff
            for kw in ("password", "secret=", "api_key", "hardcode", "private_key")
        ):
            security_flags.append("potential_hardcoded_credential")

        return Review(
            verdict="comment",
            summary=(
                "Automated review could not be completed because the local LLM "
                "is unavailable. Please review the changes for correctness, "
                "security, test coverage, and adherence to project conventions."
            ),
            comments=[
                Comment(
                    line=0,
                    content=(
                        "Could not generate detailed line-by-line review due to "
                        "temporary LLM unavailability. Manual review is recommended."
                    ),
                    severity="medium",
                )
            ],
            security_flags=security_flags,
            reasoning=f"Fallback review (LLM unavailable): {error!s}",
        )
