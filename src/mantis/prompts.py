"""Prompt templates and formatting functions for Mantis.

Central place for all LLM prompts to keep them consistent, rule-injecting
and tuned for local models like Llama 3. The format_* functions build
complete user prompts from structured inputs.
"""

from __future__ import annotations

from typing import Any

from .models import Issue


def format_triage_prompt(
    issue: Issue, history: list[Issue], rules: list[str]
) -> str:
    """Build a detailed triage prompt including issue, history and rules.

    Requests structured JSON output for easy parsing.
    """
    history_snippets = []
    for h in history:
        if h.number == issue.number:
            continue
        body_snip = (h.body or "")[:120].replace("\n", " ")
        history_snippets.append(f"#{h.number} - {h.title}: {body_snip}...")

    history_block = "\n".join(history_snippets) if history_snippets else "(no history)"
    rules_block = "\n".join(f"  - {rule}" for rule in rules) if rules else "  (no custom rules)"

    return f"""You are an expert maintainer triaging incoming issues.

CURRENT ISSUE
Title: {issue.title}
Body:
{issue.body or '(no description)'}
URL: {getattr(issue, 'html_url', 'n/a')}

RECENT HISTORY FOR CONTEXT:
{history_block}

PROJECT RULES — YOU MUST FOLLOW THESE:
{rules_block}

Analyze and respond with **valid JSON only** using this schema:
{{
  "labels": ["bug", "enhancement"],
  "priority": "high|medium|low",
  "assignee": "username or null",
  "duplicate_ids": [23, 45],
  "reasoning": "one sentence explanation"
}}

Be concise. Only return the JSON.
"""


def format_review_prompt(
    diff: str,
    rules: list[str],
    context: dict[str, Any] | None = None,
) -> str:
    """Build a review prompt from the diff, rules and contextual PR data.

    Accepts context to incorporate PR title, body and other metadata
    for more informed, contextual reviews.
    """
    ctx = context or {}
    pr = ctx.get("pr") or {}

    # support both pydantic model and dict
    if hasattr(pr, "title"):
        title = pr.title
        body = getattr(pr, "body", "") or "(no description)"
    else:
        title = pr.get("title", "Untitled PR")
        body = pr.get("body") or pr.get("description", "(no description)")

    rules_block = (
        "\n".join(f"{i+1}. {r}" for i, r in enumerate(rules))
        if rules
        else "(none defined)"
    )

    return f"""Review the following pull/merge request for this project.

PR/MR TITLE: {title}
DESCRIPTION:
{body}

CHANGES:
```diff
{diff}
```

You MUST follow these PROJECT RULES:
{rules_block}

Perform a thorough review. Look for bugs, security issues, style violations,
missing tests, performance problems and adherence to the rules.

Return **valid JSON only** (no markdown, no extra text) with this structure:

{{
  "verdict": "approve" | "request_changes" | "comment",
  "summary": "Overall assessment in 2-4 sentences",
  "comments": [
    {{
      "line": <line_number_from_diff_or_0>,
      "content": "Constructive comment or suggestion",
      "severity": "high" | "medium" | "low"
    }}
  ],
  "security_flags": ["short description of any security issues found or []"],
  "reasoning": "Your step-by-step reasoning (not shown to user)"
}}

Use real line numbers from the diff when making comments (look for lines after @@).
Be specific, actionable and kind. If everything looks good use "approve".
"""


def format_digest_prompt(
    owner: str,
    repo: str,
    issues: list[dict[str, Any]],
    prs: list[dict[str, Any]],
    days: int,
    rules: list[str],
) -> str:
    """Format the prompt used for weekly digest generation."""
    rules_block = "\n".join(f"- {rule}" for rule in rules) if rules else "(no rules)"
    issue_count = len(issues)
    pr_count = len(prs)

    return f"""Create a concise weekly digest for the {owner}/{repo} repository.

Period: last {days} days
Issues: {issue_count}
PRs/MRs: {pr_count}

Rules: 
{rules_block}

Provide a markdown summary of what happened, key decisions made, 
any patterns in incoming work, and 2-3 suggested next steps for maintainers.

Use the project's tone. Be brief, insightful and encouraging.
Output only the markdown report.
"""


# Legacy prompt constants (for backward compatibility / documentation)
# The format_* functions above are the primary interface.
TRIAGE_PROMPT = "See format_triage_prompt()"
REVIEW_PROMPT = "See format_review_prompt()"
DIGEST_PROMPT = "See format_digest_prompt()"
