"""Prompt templates and formatting utilities for Mantis.

Centralizes all LLM prompts to ensure consistency, proper injection of
project rules and context, and robust handling of input types (dicts from
API, Pydantic models, and unittest.mock.Mock used in tests).
"""

from __future__ import annotations

from typing import Any

from .models import Issue, PR


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    """Safely retrieve a field by key from either a dict or an object.

    Handles Pydantic models, plain dicts from VCS APIs, and unittest.mock.Mock
    used in tests without raising TypeError or AttributeError.
    """
    if isinstance(obj, dict):
        return obj.get(key, default)
    # For objects (models or Mocks), getattr works; Mocks return child mocks
    # which we handle downstream by checking type
    return getattr(obj, key, default)


def _safe_preview(obj: Any, max_len: int = 120) -> str:
    """Return a truncated, cleaned preview of an issue/PR body.

    Robust against Mock objects and missing fields.
    """
    body = _get_field(obj, "body") or _get_field(obj, "description", "")
    if not isinstance(body, str):
        body = ""
    preview = body[:max_len].replace("\n", " ").strip()
    return preview + "..." if len(body) > max_len else preview


TRIAGE_PROMPT = """Analyze this issue and provide triage recommendations.

Title: {title}
Body: {body}

Recent similar issues for context:
{history}

Project rules to follow:
{rules_section}

Respond with valid JSON only using this schema:
{{
  "labels": ["label1", "label2"],
  "priority": "high" | "medium" | "low",
  "assignee": "username or null",
  "duplicate_ids": [42, 13],
  "reasoning": "One sentence explaining your decision"
}}

Be conservative with duplicates. Use project conventions for labels."""

REVIEW_PROMPT = """Review the following pull request / merge request.

PR Title: {pr_title}
PR Description: {pr_body}

Changes:
```diff
{diff}
```

Project rules:
{rules_section}

Provide a structured review with verdict (approve, request_changes, comment),
summary, line-specific comments if needed, and any security flags.

Return valid JSON only:
{{
  "verdict": "approve|request_changes|comment",
  "summary": "overall assessment",
  "comments": [
    {{"line": 42, "content": "comment text", "severity": "medium"}}
  ],
  "security_flags": ["potential sql injection"]
}}

Follow the project rules strictly. Be constructive."""

DIGEST_PROMPT = """Generate a concise weekly digest for the repository.

Repository: {owner}/{repo}
Period: last {days} days

Recent issues:
{issues_summary}

Recent PRs/MRs:
{prs_summary}

Project rules: {rules_summary}

Produce a markdown report with sections: Summary, Key Decisions, Open Items,
Suggested Next Steps. Match the project's tone."""


def format_triage_prompt(
    issue: Issue, history: list[Any], rules: list[str]
) -> str:
    """Format the user prompt for issue triage.

    Handles history items that may be dicts, Issue models or test Mocks.
    """
    if not isinstance(history, list):
        history = []

    history_lines: list[str] = []
    issue_num = _get_field(issue, "number")
    for h in history:
        if _get_field(h, "number") == issue_num:
            continue
        preview = _safe_preview(h, 120)
        title = _get_field(h, "title", "Untitled")
        num = _get_field(h, "number", "??")
        history_lines.append(f"#{num}: {title}\n   {preview}")

    history_str = "\n\n".join(history_lines) or "No prior history available."

    rules_section = "\n".join(f"- {rule}" for rule in rules) if rules else "(no rules defined)"

    return TRIAGE_PROMPT.format(
        title=issue.title,
        body=(issue.body or "(no body provided)")[:500],
        history=history_str,
        rules_section=rules_section,
    )


def format_review_prompt(
    pr: PR | dict[str, Any] | Any, diff: str, rules: list[str]
) -> str:
    """Format the user prompt for PR/MR review.

    Accepts PR model, dict, context dict (for test compatibility) or Mock.
    """
    # Support test calls that may pass the full context dict
    if isinstance(pr, dict) and "pr" in pr:
        pr = pr["pr"]

    pr_title = _get_field(pr, "title", "Untitled")
    pr_body = _get_field(pr, "body") or _get_field(pr, "description", "(no description)")
    if not isinstance(pr_body, str):
        pr_body = "(no description)"

    rules_section = "\n".join(f"- {r}" for r in rules) if rules else "(no rules)"

    return REVIEW_PROMPT.format(
        pr_title=pr_title,
        pr_body=pr_body[:300],
        diff=diff,
        rules_section=rules_section,
    )


def format_digest_prompt(
    owner: str,
    repo: str,
    issues: list[Any],
    prs: list[Any],
    days: int,
    rules: list[str],
) -> str:
    """Format the prompt for generating a repository digest.

    Uses safe field access so it works with dicts from the VCS clients.
    """
    def summarize_items(items: list[Any], item_type: str) -> str:
        lines = []
        for item in items[:5]:  # limit context size for prompt
            title = _get_field(item, "title", "Untitled")
            num = _get_field(item, "number", "?")
            state = _get_field(item, "state", "open")
            lines.append(f"- #{num} {title} ({state})")
        return "\n".join(lines) or f"No recent {item_type}."

    issues_summary = summarize_items(issues, "issues")
    prs_summary = summarize_items(prs, "PRs/MRs")

    rules_summary = ", ".join(rules) if rules else "none"

    return DIGEST_PROMPT.format(
        owner=owner,
        repo=repo,
        days=days,
        issues_summary=issues_summary,
        prs_summary=prs_summary,
        rules_summary=rules_summary,
    )


__all__ = [
    "format_triage_prompt",
    "format_review_prompt",
    "format_digest_prompt",
]
