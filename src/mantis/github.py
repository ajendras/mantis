"""GitHub API client for Mantis.

Handles issue/PR retrieval, diff fetching, and recent activity listing
with automatic rate-limit backoff and clear error messaging.

Also provides MR aliases so the same interface works with GitLabClient.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from .models import Issue  # noqa: F401 - re-exported for type checking in analyzer


class GitHubClient:
    """Thin wrapper around the GitHub REST API.

    Supports public and authenticated access, rate-limit handling,
    and returns data compatible with the Pydantic models in .models.
    The get_merge_request/get_mr_diff methods are aliases so that
    GitLabClient can be dropped in transparently.
    """

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str | None = None) -> None:
        """Initialize the client.

        Args:
            token: Optional GitHub Personal Access Token.
        """
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "mantis/0.1.0 (github.com/ajendras/mantis)",
            }
        )
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _request(
        self, method: str, url: str, **kwargs: Any
    ) -> requests.Response:
        """Perform an HTTP request with rate-limit awareness."""
        resp = self.session.request(method, url, **kwargs)

        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            self._handle_rate_limit(resp)

        resp.raise_for_status()
        return resp

    def _handle_rate_limit(self, resp: requests.Response) -> None:
        """Sleep until the rate limit resets (if short) or raise."""
        reset_ts = int(resp.headers.get("X-RateLimit-Reset", 0))
        remaining = resp.headers.get("X-RateLimit-Remaining", "0")

        if reset_ts > 0:
            wait = reset_ts - int(time.time())
            if 0 < wait < 30:  # only auto-wait for brief pauses
                print(f"GitHub rate limit hit. Waiting {wait}s...")
                time.sleep(wait + 1)
                return

        raise RuntimeError(
            f"GitHub rate limit exceeded (remaining calls: {remaining}).\n"
            "Set MANTIS_GITHUB_TOKEN for higher limits or wait before retrying."
        )

    def get_issue(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        """Retrieve a single issue (or PR) by number.

        Args:
            owner: Repository owner.
            repo: Repository name.
            number: Issue or PR number.

        Returns:
            Raw GitHub issue payload.

        Raises:
            ValueError: On invalid parameters.
            requests.HTTPError: On API errors.
        """
        if not owner or not repo or number < 1:
            raise ValueError("owner, repo, and number (>0) are required")

        url = f"{self.BASE_URL}/repos/{owner}/{repo}/issues/{number}"
        response = self._request("GET", url)
        return response.json()

    def get_pr_diff(self, owner: str, repo: str, number: int) -> str:
        """Fetch the unified diff for a pull request.

        Args:
            owner: Repository owner.
            repo: Repository name.
            number: PR number.

        Returns:
            Unified diff as text.

        Raises:
            ValueError: On invalid parameters.
            requests.HTTPError: On API errors.
        """
        if not owner or not repo or number < 1:
            raise ValueError("owner, repo, and number (>0) are required")

        url = f"{self.BASE_URL}/repos/{owner}/{repo}/pulls/{number}"
        headers = {"Accept": "application/vnd.github.v3.diff"}
        response = self._request("GET", url, headers=headers)
        return response.text

    def list_recent_issues(
        self,
        owner: str,
        repo: str,
        limit: int = 20,
        state: str = "all",
    ) -> list[dict[str, Any]]:
        """List the most recently updated issues (includes PRs).

        Args:
            owner: Repository owner.
            repo: Repository name.
            limit: Maximum number of issues to return.
            state: Issue state filter (open, closed, all).

        Returns:
            List of issue dicts.
        """
        if not owner or not repo:
            raise ValueError("owner and repo are required")
        limit = max(1, min(limit, 100))

        url = f"{self.BASE_URL}/repos/{owner}/{repo}/issues"
        params = {
            "state": state,
            "sort": "updated",
            "direction": "desc",
            "per_page": limit,
        }

        response = self._request("GET", url, params=params)
        issues: list[dict[str, Any]] = response.json()
        return issues[:limit]

    def list_recent_prs(
        self, owner: str, repo: str, limit: int = 15
    ) -> list[dict[str, Any]]:
        """List the most recently updated pull requests.

        Args:
            owner: Repository owner.
            repo: Repository name.
            limit: Maximum number of PRs to return.

        Returns:
            List of PR dicts.
        """
        if not owner or not repo:
            raise ValueError("owner and repo are required")
        limit = max(1, min(limit, 100))

        url = f"{self.BASE_URL}/repos/{owner}/{repo}/pulls"
        params = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": limit,
        }

        response = self._request("GET", url, params=params)
        prs: list[dict[str, Any]] = response.json()
        return prs[:limit]

    def get_merge_request(
        self, owner: str, repo: str, number: int
    ) -> dict[str, Any]:
        """Alias for get_issue on GitHub since PRs are issues."""
        return self.get_issue(owner, repo, number)

    def get_mr_diff(self, owner: str, repo: str, number: int) -> str:
        """Alias for get_pr_diff on GitHub."""
        return self.get_pr_diff(owner, repo, number)
