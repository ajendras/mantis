"""GitLab API client for Mantis.

Mirrors the public interface of GitHubClient (including method names)
so the rest of the codebase can switch platforms with zero changes.
Response payloads are normalized to GitHub-like shape for model
compatibility.
"""

from __future__ import annotations

import time
from typing import Any

import requests


class GitLabClient:
    """Thin wrapper around the GitLab REST API v4.

    Provides identical method names and return shapes as GitHubClient.
    Normalizes fields (web_url->html_url, author->user, iid->number,
    description->body) so Pydantic models and prompts continue to work.
    Supports self-hosted GitLab via the gitlab_url config option.
    """

    def __init__(self, token: str | None = None, base_url: str | None = None) -> None:
        """Initialize the client.

        Args:
            token: GitLab personal access token.
            base_url: Base URL for the GitLab instance (default gitlab.com).
        """
        self.token = token
        self.base_url = (base_url or "https://gitlab.com").rstrip("/")
        self.api_url = f"{self.base_url}/api/v4"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "mantis/0.1.0 (github.com/ajendras/mantis)",
            }
        )
        if token:
            self.session.headers["PRIVATE-TOKEN"] = token

    def _request(
        self, method: str, url: str, **kwargs: Any
    ) -> requests.Response:
        """Perform an HTTP request with rate-limit awareness."""
        resp = self.session.request(method, url, **kwargs)

        if resp.status_code in (429, 403) and any(
            term in resp.text.lower() for term in ("rate limit", "too many requests")
        ):
            self._handle_rate_limit(resp)

        resp.raise_for_status()
        return resp

    def _handle_rate_limit(self, resp: requests.Response) -> None:
        """Sleep until the rate limit resets (if short) or raise."""
        reset_ts = int(
            resp.headers.get("RateLimit-Reset", 0)
            or resp.headers.get("X-RateLimit-Reset", 0)
        )
        remaining = resp.headers.get(
            "RateLimit-Remaining", resp.headers.get("X-RateLimit-Remaining", "0")
        )

        if reset_ts > 0:
            wait = reset_ts - int(time.time())
            if 0 < wait < 30:
                print(f"GitLab rate limit hit. Waiting {wait}s...")
                time.sleep(wait + 1)
                return

        raise RuntimeError(
            f"GitLab rate limit exceeded (remaining: {remaining}).\n"
            "Set MANTIS_GITLAB_TOKEN for higher limits or wait before retrying."
        )

    def _normalize(self, data: Any) -> Any:
        """Normalize GitLab payload to be compatible with GitHub-shaped code."""
        if isinstance(data, list):
            return [self._normalize(item) for item in data]
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        if "web_url" in normalized and "html_url" not in normalized:
            normalized["html_url"] = normalized["web_url"]
        if "description" in normalized and "body" not in normalized:
            normalized["body"] = normalized.get("description")
        if "iid" in normalized and "number" not in normalized:
            normalized["number"] = normalized["iid"]
        if "author" in normalized and "user" not in normalized:
            author = normalized["author"]
            normalized["user"] = {
                "login": author.get("username") or author.get("name", "unknown"),
                **author,
            }
        if ("owner" not in normalized or "repo" not in normalized) and normalized.get(
            "html_url"
        ):
            url = normalized["html_url"]
            if "gitlab.com" in url or any(p in url for p in ("-/issues/", "-/merge_requests/")):
                parts = url.replace("https://", "").replace("http://", "").split("/")
                try:
                    idx = parts.index("gitlab.com") if "gitlab.com" in parts else -1
                    if idx == -1:
                        # self-hosted may not have gitlab.com in path
                        for i, p in enumerate(parts):
                            if p in ("issues", "merge_requests", "-"):
                                if i > 1:
                                    normalized["owner"] = parts[i - 2]
                                    normalized["repo"] = parts[i - 1]
                                    break
                    elif len(parts) > idx + 2:
                        normalized["owner"] = parts[idx + 1]
                        normalized["repo"] = parts[idx + 2]
                except ValueError:
                    pass
        return normalized

    def get_issue(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        """Retrieve a single issue by number.

        Args:
            owner: Repository owner (or group).
            repo: Repository name.
            number: Issue IID.

        Returns:
            Normalized issue dict.
        """
        if not owner or not repo or number < 1:
            raise ValueError("owner, repo, and number (>0) are required")

        project = f"{owner}%2F{repo}"
        url = f"{self.api_url}/projects/{project}/issues/{number}"
        response = self._request("GET", url)
        return self._normalize(response.json())

    def get_pr_diff(self, owner: str, repo: str, number: int) -> str:
        """Alias that forwards to get_mr_diff for GitLab."""
        return self.get_mr_diff(owner, repo, number)

    def get_merge_request(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        """Retrieve a single merge request by IID.

        Args:
            owner: Repository owner (or group).
            repo: Repository name.
            number: MR IID.

        Returns:
            Normalized MR dict (compatible with PR model).
        """
        if not owner or not repo or number < 1:
            raise ValueError("owner, repo, and number (>0) are required")

        project = f"{owner}%2F{repo}"
        url = f"{self.api_url}/projects/{project}/merge_requests/{number}"
        response = self._request("GET", url)
        return self._normalize(response.json())

    def get_mr_diff(self, owner: str, repo: str, number: int) -> str:
        """Fetch unified diff for a merge request.

        Uses the convenient .diff endpoint that returns a patch directly.
        """
        if not owner or not repo or number < 1:
            raise ValueError("owner, repo, and number (>0) are required")

        diff_url = f"{self.base_url}/{owner}/{repo}/-/merge_requests/{number}.diff"
        response = self.session.get(diff_url)
        response.raise_for_status()
        return response.text

    def list_recent_issues(
        self,
        owner: str,
        repo: str,
        limit: int = 20,
        state: str = "all",
    ) -> list[dict[str, Any]]:
        """List the most recently updated issues."""
        if not owner or not repo:
            raise ValueError("owner and repo are required")
        limit = max(1, min(limit, 100))

        project = f"{owner}%2F{repo}"
        url = f"{self.api_url}/projects/{project}/issues"
        params = {
            "state": state,
            "order_by": "updated_at",
            "sort": "desc",
            "per_page": limit,
        }

        response = self._request("GET", url, params=params)
        issues = self._normalize(response.json())
        if isinstance(issues, list):
            return issues[:limit]
        return []

    def list_recent_prs(
        self, owner: str, repo: str, limit: int = 15
    ) -> list[dict[str, Any]]:
        """List the most recently updated merge requests."""
        if not owner or not repo:
            raise ValueError("owner and repo are required")
        limit = max(1, min(limit, 100))

        project = f"{owner}%2F{repo}"
        url = f"{self.api_url}/projects/{project}/merge_requests"
        params = {
            "state": "all",
            "order_by": "updated_at",
            "sort": "desc",
            "per_page": limit,
        }

        response = self._request("GET", url, params=params)
        prs = self._normalize(response.json())
        if isinstance(prs, list):
            return prs[:limit]
        return []
