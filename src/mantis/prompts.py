"""Prompt templates and formatting functions for Mantis.

All prompts are engineered for local LLMs (especially Ollama models)
and produce consistent structured JSON when requested. Project rules,
repository context, and history are injected at runtime.
"""

from __future__ import annotations

from textwrap import dedent
from typing import Any

from .models import Issue

TRIAGE_PROMPT = dedent("""\
You are an expert maintainer triaging issues for this project.
You have deep knowledge of its architecture, conventions, and values.

{context}

RECENT HISTORY (for duplicate detection and style):
{history}

---
NEW ISSUE #{number}: {title}

{body}
---

Follow the PROJECT RULES above on every decision.
Be concise, constructive, and precise.

Return **only** valid JSON with this exact schema (no extra text):

{{
  "labels": ["label1", "label2"],
  "priority": "high|medium|low",
  "assignee": "github-username-or-null",
  "duplicate_ids": [42, 17],
  "reasoning": "one-sentence explanation of your choices"
}}

Notes:
- Prefer labels that already exist in the repository.
- Only mark duplicates when the root cause and resolution are clearly the same.
- Priority must reflect urgency, scope, and impact on users.
""")

REVIEW_PROMPT = dedent("""\
You are a rigorous, constructive code reviewer for this project.
You understand its architecture, coding standards, and security posture.

{context}

PROJECT RULES (you MUST obey these):
{rules}

---
PULL REQUEST DIFF:

```diff
{diff}
```

Analyze the changes for correctness, style, security, performance,
and adherence to the rules above.

Return **only** valid JSON with this exact schema:

{{
  "verdict": "approve|request_changes|comment",
  "summary": "one-paragraph overview of the PR and your assessment",
  "comments": [
    {{
      "line": 42,
      "content": "Specific, actionable feedback referencing the exact code.",
      "severity": "low|medium|high"
    }}
  ],
  "security_flags": ["hardcoded_secret", "sql_injection"],
  "reasoning": "internal reasoning (not shown to the contributor)"
}}

Guidelines:
- Reference line numbers from the diff when possible.
- Be kind but direct. Never be condescending.
- If the PR is perfect, use "approve" with an empty comments list.
- Security flags must be precise and only used for real concerns.
""")

REPLY_PROMPT = dedent("""\
You are responding to a GitHub issue or comment as the maintainer of this project.

PROJECT RULES (you MUST follow):
{rules}

USER MESSAGE:
{user_message}

Write a reply that:
- Is concise, constructive, and kind
- Uses the project's existing tone and terminology
- Respects every rule listed above
- Offers clear next steps when appropriate
- Never promises features or changes that contradict the rules

Return only the markdown reply (no JSON, no explanation).
""")

DIGEST_PROMPT = dedent("""\
You are preparing a weekly digest for the maintainers of {owner}/{repo}.

Period: last {days} days.

RECENT ISSUES:
{issues_summary}

RECENT PULL REQUESTS:
{prs_summary}

PROJECT RULES:
{rules_summary}

Write a concise, insightful markdown digest that includes:

- Activity summary (issues opened/closed, PRs merged)
- Key decisions and lessons learned
- Open items that need attention
- Suggested next steps (prioritised)

Use the project's own tone: professional, concise, encouraging.
Include emoji sparingly and only when they add clarity.
Focus on what matters to the maintainers.
""")


def format_triage_prompt(
    issue: Issue, history: list[Issue], rules: list[str]
) -> str:
    """Format the triage prompt with issue data, history, and rules.

    Args:
        issue: The issue being triaged.
        history: Recent issues for context and duplicate detection.
        rules: Project-specific automation rules.

    Returns:
        Fully rendered prompt ready for the LLM.
    """
    if not rules:
        context = "No custom project rules have been defined."
    else:
        context = "PROJECT RULES (follow on every response):\n" + "\n".join(
            f"{i}. {rule}" for i, rule in enumerate(rules, 1)
        )

    history_lines = []
    for h in history[:12]:
        if getattr(issue, "number", -1) == h.number:
            continue
        preview = (h.body or "")[:120].replace("\n", " ")
        history_lines.append(f"#{h.number} {h.title}\n   {preview}...")

    history_block = "\n\n".join(history_lines) or "(no recent history)"

    return TRIAGE_PROMPT.format(
        context=context,
        history=history_block,
        number=issue.number,
        title=issue.title,
        body=issue.body or "(no description provided)",
    )


def format_review_prompt(
    diff: str, context: dict[str, Any], rules: list[str]
) -> str:
    """Format the PR review prompt with diff, PR context, and rules.

    Args:
        diff: The PR patch.
        context: Dictionary containing at minimum a 'pr' key.
        rules: Project-specific rules.

    Returns:
        Fully rendered prompt ready for the LLM.
    """
    pr = context.get("pr") or {}
    pr_title = getattr(pr, "title", pr.get("title", "Untitled"))
    pr_author = getattr(pr, "user", {}) or pr.get("user", {})
    author = pr_author.get("login", "unknown") if isinstance(pr_author, dict) else "unknown"

    context_block = (
        f"Repository: {context.get('repo', 'unknown/unknown')}\n"
        f"PR #{getattr(pr, 'number', pr.get('number', '??'))}: {pr_title}\n"
        f"Author: @{author}\n"
        f"Description: {getattr(pr, 'body', pr.get('body', ''))[:280]}"
    )

    rules_block = (
        "\n".join(f"• {r}" for r in rules)
        if rules
        else "(no additional project rules defined)"
    )

    # Truncate extremely large diffs to stay within token limits
    if len(diff) > 18000:
        diff = diff[:18000] + "\n\n... (diff truncated due to length)"

    return REVIEW_PROMPT.format(
        context=context_block,
        rules=rules_block,
        diff=diff,
    )


def format_reply_prompt(user_message: str, rules: list[str]) -> str:
    """Format a reply-assistant prompt (used by future reply command)."""
    rules_block = "\n".join(f"• {r}" for r in rules) if rules else "(none)"
    return REPLY_PROMPT.format(user_message=user_message, rules=rules_block)


def format_digest_prompt(
    owner: str,
    repo: str,
    issues: list[dict[str, Any]],
    prs: list[dict[str, Any]],
    days: int,
    rules: list[str],
) -> str:
    """Format the digest prompt with activity summaries and rules.

    Args:
        owner: Repository owner.
        repo: Repository name.
        issues: Recent issues from GitHub API.
        prs: Recent PRs from GitHub API.
        days: Number of days covered.
        rules: Project rules.

    Returns:
        Fully rendered prompt for the LLM.
    """
    issues_summary = "\n".join(
        f"- #{i.get('number')} {i.get('title','')} ({i.get('state','')})"
        for i in issues[:15]
    ) or "(no issues in period)"

    prs_summary = "\n".join(
        f"- #{p.get('number')} {p.get('title','')} ({p.get('state','')}) "
        f"by @{p.get('user',{}).get('login','unknown')}"
        for p in prs[:10]
    ) or "(no PRs in period)"

    rules_summary = (
        "\n".join(f"• {r}" for r in rules) if rules else "(no custom rules)"
    )

    return DIGEST_PROMPT.format(
        owner=owner,
        repo=repo,
        days=days,
        issues_summary=issues_summary,
        prs_summary=prs_summary,
        rules_summary=rules_summary,
    )
