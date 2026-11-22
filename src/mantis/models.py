"""Pydantic models for Mantis.

Defines structured data classes for GitHub issues/PRs, triage results,
reviews, and configuration rules. All models include strict validation,
sensible defaults, and clear error messages. Models are compatible with
raw GitHub API payloads.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Issue(BaseModel):
    """Represents a GitHub issue (or PR) with extracted repository context.

    Accepts raw GitHub API payloads and normalizes owner/repo information.
    """

    owner: str
    repo: str
    number: int = Field(..., gt=0)
    title: str
    body: str | None = None
    html_url: str | None = None
    user: dict[str, Any] | None = None
    labels: list[dict[str, Any]] | list[str] | None = None
    state: str | None = "open"

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "json_schema_extra": {"examples": [{"title": "Sample issue"}]},
    }

    @model_validator(mode="before")
    @classmethod
    def extract_owner_repo(cls, data: Any) -> Any:
        """Extract owner and repo from html_url if not provided."""
        if isinstance(data, dict):
            if "html_url" in data and ("owner" not in data or "repo" not in data):
                url = data["html_url"]
                # simplistic parse for github/gitlab urls
                if "/github.com/" in url or "/gitlab.com/" in url or "/-/issues/" in url:
                    parts = url.replace("https://", "").replace("http://", "").split("/")
                    try:
                        if "github.com" in url:
                            idx = parts.index("github.com")
                            data.setdefault("owner", parts[idx + 1])
                            data.setdefault("repo", parts[idx + 2])
                        elif "gitlab.com" in parts:
                            idx = parts.index("gitlab.com")
                            data.setdefault("owner", parts[idx + 1])
                            data.setdefault("repo", parts[idx + 2])
                        else:
                            # self-hosted heuristic
                            for i, p in enumerate(parts):
                                if p in ("issues", "merge_requests"):
                                    if i > 1:
                                        data.setdefault("owner", parts[i - 2])
                                        data.setdefault("repo", parts[i - 1])
                                        break
                    except (ValueError, IndexError):
                        pass
            # normalize GitLab-style fields
            if "iid" in data and "number" not in data:
                data["number"] = data["iid"]
            if "description" in data and "body" not in data:
                data["body"] = data["description"]
            if "author" in data and isinstance(data["author"], dict) and "user" not in data:
                author = data["author"]
                data["user"] = {
                    "login": author.get("username") or author.get("name", "unknown"),
                    **author,
                }
        return data


class PR(Issue):
    """PR or MR model (extends Issue)."""

    pass


class Comment(BaseModel):
    """A single review comment, optionally tied to a file/line."""

    content: str
    line: int | None = None
    severity: Literal["low", "medium", "high"] = "medium"
    path: str | None = None


class TriageResult(BaseModel):
    """Structured output from issue triage."""

    labels: list[str] = Field(default_factory=list)
    priority: Literal["low", "medium", "high"] = "medium"
    assignee: str | None = None
    duplicate_ids: list[int] = Field(default_factory=list)
    reasoning: str = Field(default="No reasoning available.")

    @field_validator("labels", mode="before")
    @classmethod
    def normalize_labels(cls, v: Any) -> list[str]:
        """Normalize labels whether provided as a string, comma-separated string or list."""
        if isinstance(v, str):
            if not v or not v.strip():
                return []
            return [lbl.strip() for lbl in v.split(",") if lbl.strip()]
        if isinstance(v, list):
            result: list[str] = []
            for item in v:
                if isinstance(item, str):
                    if not item or not item.strip():
                        continue
                    if "," in item:
                        result.extend(
                            [lbl.strip() for lbl in item.split(",") if lbl.strip()]
                        )
                    else:
                        result.append(item.strip())
                elif item is not None:
                    result.append(str(item).strip())
            return result
        return []

    @field_validator("duplicate_ids", mode="before")
    @classmethod
    def normalize_duplicate_ids(cls, v: Any) -> list[int]:
        """Ensure duplicate_ids is always a list of ints."""
        if isinstance(v, list):
            ids: list[int] = []
            for x in v:
                try:
                    ids.append(int(x))
                except (ValueError, TypeError):
                    continue
            return ids
        if isinstance(v, (int, str)):
            try:
                return [int(v)]
            except (ValueError, TypeError):
                return []
        return []

    model_config = {
        "extra": "forbid",
    }


class Review(BaseModel):
    """Structured PR/MR review result."""

    verdict: Literal["approve", "request_changes", "comment"] = "comment"
    summary: str
    comments: list[Comment] = Field(default_factory=list)
    security_flags: list[str] = Field(default_factory=list)
    reasoning: str = "No reasoning provided."

    model_config = {
        "extra": "forbid",
    }
