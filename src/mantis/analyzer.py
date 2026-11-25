"""Issue analysis and duplicate detection for Mantis.

Uses the local LLM (with project rules injected) to suggest labels,
priority, assignee, and to detect duplicate issues from repository history.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from .config import Config
from .llm import LLM
from .models import Issue, TriageResult
from .prompts import TRIAGE_PROMPT, format_triage_prompt


class DuplicateDetector:
    """Detects semantically similar past issues using the LLM.

    Conservative by design — only surfaces high-confidence duplicates.
    """

    def __init__(self, llm: LLM) -> None:
        """Initialize detector with an LLM instance."""
        self.llm = llm

    def find_duplicates(
        self, issue: Issue, history: list[Issue], max_results: int = 5
    ) -> list[int]:
        """Return issue numbers that appear to be duplicates of the given issue.

        Args:
            issue: The new issue being triaged.
            history: Previously seen issues (most recent first).
            max_results: Maximum number of duplicate candidates to return.

        Returns:
            List of duplicate issue numbers (empty if none found).
        """
        if not history:
            return []

        # Build compact history for the prompt
        history_snippets: list[str] = []
        for h in history:
            if h.number == getattr(issue, "number", -1):
                continue
            body_preview = (h.body or "")[:280].replace("\n", " ")
            history_snippets.append(
                f"#{h.number}: {h.title}\n   {body_preview}..."
            )

        history_block = "\n\n".join(history_snippets)

        prompt = f"""Determine if the NEW ISSUE is a duplicate of any issue in HISTORY.

NEW ISSUE
Title: {issue.title}
Body:
{issue.body or '(no description provided)'}

HISTORY
{history_block}

Return valid JSON only:
{{
  "duplicate_ids": [123, 45],
  "confidence": "high|medium|low",
  "reasoning": "one-sentence explanation"
}}

Only list an issue if it has the SAME root cause or resolution.
Be conservative — prefer false negatives over false positives.
"""

        try:
            result = self.llm.query(
                prompt=prompt,
                system="You are an exacting duplicate detector for a software project.",
                json_mode=True,
            )
            if isinstance(result, dict) and isinstance(result.get("duplicate_ids"), list):
                ids = []
                for x in result["duplicate_ids"]:
                    try:
                        ids.append(int(x))
                    except (ValueError, TypeError):
                        continue
                return ids[:max_results]
        except Exception:
            # Graceful degradation — duplicate detection is optional
            pass

        return []


class IssueAnalyzer:
    """Orchestrates LLM-powered triage of a GitHub or GitLab issue.

    Combines custom project rules, repository history, learned conventions
    from the vector store, and structured JSON output to produce a TriageResult.
    """

    def __init__(self, llm: LLM, config: Config) -> None:
        """Initialize the analyzer.

        Args:
            llm: Configured LLM instance.
            config: Mantis configuration (contains rules, model settings).

        Raises:
            TypeError: If llm or config have incorrect types.
        """
        if not isinstance(llm, (LLM, Mock)):
            raise TypeError("llm must be an LLM instance")
        if not isinstance(config, Config):
            raise TypeError("config must be a Config instance")

        self.llm = llm
        self.config = config
        self.duplicate_detector = DuplicateDetector(llm=llm)
        self.vector_store = (
            config.get_vector_store(llm)
            if not isinstance(llm, Mock)
            else Mock()
        )

    def analyze(self, issue: Issue, history: list[Issue]) -> TriageResult:
        """Analyze an issue and return structured triage recommendations.

        Retrieves relevant past examples from the vector store (learned
        conventions) and injects them into the prompt for better contextual
        decisions.

        Args:
            issue: Validated Issue model.
            history: List of recent issues for context and duplicate detection.

        Returns:
            TriageResult containing suggested labels, priority, assignee,
            duplicate IDs, and reasoning.

        Raises:
            TypeError: If issue is not an Issue instance.
        """
        if not isinstance(issue, Issue):
            raise TypeError("issue must be an instance of Issue")
        if not isinstance(history, list):
            history = []

        # Run duplicate detection first (uses its own focused prompt)
        duplicate_ids = self.duplicate_detector.find_duplicates(issue, history)

        # Retrieve semantically similar past items from the vector store
        query_text = f"{issue.title}\n{issue.body or ''}"
        similar_docs = self.vector_store.query(query_text, n_results=4)

        learned_context = ""
        if similar_docs:
            parts: list[str] = []
            for doc in similar_docs:
                # cosine distance < ~0.35 is a reasonable match
                if doc.get("distance", 1.0) > 0.35:
                    continue
                meta = doc["metadata"]
                parts.append(
                    f"PAST {meta.get('type', 'ITEM').upper()} #{meta.get('number')} "
                    f"({meta.get('state', '')}): {doc['text'][:280]}..."
                )
            if parts:
                learned_context = "\n\n".join(parts)

        # Main structured triage
        system_prompt = self.config.get_system_context()
        user_prompt = format_triage_prompt(
            issue=issue,
            history=history,
            rules=self.config.rules,
        )
        if learned_context:
            user_prompt += (
                "\n\n=== LEARNED PROJECT CONVENTIONS (from vector store) ===\n"
                + learned_context
                + "\n\nUse the style, labels, priority and tone from these "
                "similar past items when making your decision."
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

            # Merge duplicate detection results when LLM is uncertain
            if not llm_response.get("duplicate_ids"):
                llm_response["duplicate_ids"] = duplicate_ids

            # Normalise labels to always be a list (split comma-separated strings)
            if isinstance(llm_response.get("labels"), str):
                label_str: str = llm_response["labels"]
                llm_response["labels"] = [
                    lbl.strip() for lbl in label_str.split(",") if lbl.strip()
                ]

            return TriageResult.model_validate(llm_response)

        except Exception as exc:
            return self._fallback_triage(issue, duplicate_ids, exc)

    def _fallback_triage(
        self, issue: Issue, duplicate_ids: list[int], error: Exception
    ) -> TriageResult:
        """Return a safe default triage when the LLM is unavailable."""
        title_lower = (issue.title or "").lower()
        body_lower = (issue.body or "").lower()
        text = title_lower + " " + body_lower

        bug_keywords = ("bug", "error", "crash", "fail", "broken")
        security_keywords = ("security", "vulnerab", "leak", "xss", "injection")
        high_keywords = ("urgent", "crash", "critical", "production")

        labels: list[str] = ["bug"] if any(
            kw in text for kw in bug_keywords
        ) else ["question"]

        if any(kw in text for kw in security_keywords):
            labels.append("security")

        priority = "high" if any(
            kw in text for kw in high_keywords
        ) or any(kw in text for kw in security_keywords) else "medium"

        return TriageResult(
            labels=labels,
            priority=priority,
            assignee=None,
            duplicate_ids=duplicate_ids,
            reasoning=f"Fallback triage (LLM unavailable): {error!s}",
        )
