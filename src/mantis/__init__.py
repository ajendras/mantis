"""Mantis — Local-first GitHub and GitLab maintainer assistant powered by Ollama.

Provides a clean public API for triage, review, and digest generation.
All heavy lifting is delegated to specialized modules while respecting
project conventions, rules, and history.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Config

__version__ = "0.1.0"
__all__ = ["triage_issue", "review_pr", "generate_digest", "Config"]


def triage_issue(issue: dict[str, Any], config: Config | None = None) -> "TriageResult":
    """Analyze a GitHub or GitLab issue and return structured triage recommendations.

    Uses the project's own history, custom rules, and local LLM to suggest
    labels, priority, assignee, and duplicate candidates.

    Args:
        issue: GitHub/GitLab issue payload (dict from API or raw JSON).
        config: Optional configuration; loads from env/file if omitted.

    Returns:
        TriageResult with labels, priority, suggested assignee, and duplicate IDs.

    Raises:
        TypeError: If issue is not a dict.
        ValueError: If configuration or rules are invalid.
    """
    if config is None:
        config = Config.load()
    config.validate_rules()

    if not isinstance(issue, dict):
        raise TypeError("issue must be a dictionary containing VCS issue data")

    # Local imports keep the public API module lightweight and avoid
    # circular dependencies during the build-out of supporting modules.
    from .analyzer import IssueAnalyzer
    from .github import GitHubClient
    from .llm import LLM
    from .models import Issue, TriageResult

    issue_model = Issue.model_validate(issue)

    llm = LLM(**config.get_llm_kwargs())

    if config.platform == "github":
        vcs_client = GitHubClient(token=config.github_token)
    else:
        from .gitlab import GitLabClient

        token = config.gitlab_token or config.github_token
        vcs_client = GitLabClient(token=token, base_url=config.gitlab_url)

    # Pull recent history for semantic context (duplicate detection + style learning)
    try:
        history = vcs_client.list_recent_issues(
            owner=issue_model.owner, repo=issue_model.repo, limit=20
        )
    except Exception:
        # Graceful offline fallback — still produces a useful result
        history = []

    analyzer = IssueAnalyzer(llm=llm, config=config)
    return analyzer.analyze(issue=issue_model, history=history)


def review_pr(
    pr: dict[str, Any], diff: str, config: Config | None = None
) -> "Review":
    """Perform a contextual code review of a pull request or merge request.

    Generates line-specific comments, an overall verdict, security flags,
    and respects any project-specific rules defined in config.

    Args:
        pr: GitHub/GitLab PR/MR payload (dict).
        diff: Unified diff text (patch) of the changes.
        config: Optional configuration; loads from env/file if omitted.

    Returns:
        Review object containing verdict, list of Comment objects, and security flags.

    Raises:
        ValueError: If diff is empty or configuration is invalid.
    """
    if config is None:
        config = Config.load()
    config.validate_rules()

    if not diff or not diff.strip():
        raise ValueError("diff must be a non-empty string containing the PR/MR patch")

    from .llm import LLM
    from .models import PR, Review
    from .review import PRReviewer

    pr_model = PR.model_validate(pr)

    llm = LLM(**config.get_llm_kwargs())
    reviewer = PRReviewer(llm=llm, config=config)

    return reviewer.review(
        diff=diff,
        context={"pr": pr_model, "repo_rules": config.rules},
        rules=config.rules,
    )


def generate_digest(repo: str, days: int = 7, config: Config | None = None) -> str:
    """Generate a concise markdown weekly digest of repository activity.

    Summarizes issues, PRs/MRs, decisions, and suggests next steps using
    the project's own tone and rules.

    Args:
        repo: Repository in owner/repo format.
        days: Number of days to look back.
        config: Optional configuration; loads from env/file if omitted.

    Returns:
        Markdown formatted digest report.

    Raises:
        ValueError: If repo format is invalid.
    """
    if config is None:
        config = Config.load()
    config.validate_rules()

    if "/" not in repo:
        raise ValueError("repo must be in 'owner/repo' format")

    owner, repo_name = repo.split("/", 1)

    from .github import GitHubClient
    from .llm import LLM
    from .prompts import DIGEST_PROMPT, format_digest_prompt

    llm = LLM(**config.get_llm_kwargs())

    if config.platform == "github":
        client = GitHubClient(token=config.github_token)
    else:
        from .gitlab import GitLabClient

        token = config.gitlab_token or config.github_token
        client = GitLabClient(token=token, base_url=config.gitlab_url)

    try:
        issues = client.list_recent_issues(owner, repo_name, limit=30)
        prs = client.list_recent_prs(owner, repo_name, limit=15)
    except Exception:
        issues = []
        prs = []

    system = config.get_system_context()
    prompt = format_digest_prompt(
        owner=owner,
        repo=repo_name,
        issues=issues,
        prs=prs,
        days=days,
        rules=config.rules,
    )

    try:
        digest = llm.query(prompt=prompt, system=system, json_mode=False)
        return digest.strip()
    except Exception as exc:
        # Production-friendly offline fallback that still produces valid markdown
        return _offline_digest_fallback(owner, repo_name, days, exc)


def _offline_digest_fallback(owner: str, repo: str, days: int, error: Exception) -> str:
    """Return a helpful offline markdown digest when the LLM is unavailable."""
    return f"""# Mantis Digest — {owner}/{repo}

**Period**: Last {days} days  
**Generated**: (offline mode)

The local LLM endpoint is currently unavailable ({error!s}).

## Suggested Next Steps
- Start Ollama with `ollama serve` and pull the configured model (`{Config().model}`).
- Run `mantis config` to verify settings.
- Use `mantis triage` or `mantis review` once the model is available.

**Tip**: All Mantis operations run 100% locally and never transmit repository data.
"""


# Re-export core models and config for library users
from .config import Config  # noqa: F401
from .models import Review, TriageResult  # noqa: F401
