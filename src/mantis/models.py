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
        """Extract owner and repo from html_url or repository_url when missing.

        This makes the model compatible with raw GitHub API responses.
        """
        if isinstance(data, dict):
            data = dict(data)  # ensure mutable copy
            if not data.get("owner") or not data.get("repo"):
                html = data.get("html_url") or data.get("repository_url", "")
                if "github.com" in html:
                    parts = html.replace("https://", "").replace("http://", "").split("/")
                    if len(parts) >= 4:
                        data["owner"] = parts[1]
                        data["repo"] = parts[2]
                elif "repository" in data and isinstance(data["repository"], dict):
                    full_name = data["repository"].get("full_name", "")
                    if "/" in full_name:
                        owner, repo = full_name.split("/", 1)
                        data["owner"] = owner
                        data["repo"] = repo
        return data

    @field_validator("owner", "repo")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("owner and repo must be non-empty strings")
        return v.strip().lower()

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("title must be a non-empty string")
        return v.strip()

    @field_validator("number")
    @classmethod
    def positive_number(cls, v: int) -> int:
        if v < 1:
            raise ValueError("issue number must be positive")
        return v


class PR(Issue):
    """Pull request model.

    Inherits from Issue because GitHub treats PRs as a special kind of issue.
    Extra fields are allowed for full API compatibility.
    """

    draft: bool = False
    merged: bool = False
    merged_at: str | None = None


class TriageResult(BaseModel):
    """Structured triage recommendation for a GitHub issue."""

    labels: list[str] = Field(default_factory=list)
    priority: Literal["low", "medium", "high"] = "medium"
    assignee: str | None = None
    duplicate_ids: list[int] = Field(default_factory=list)
    reasoning: str = Field(
        default="No reasoning provided by the model.",
        description="Explanation of triage decisions",
    )

    @field_validator("labels", mode="before")
    @classmethod
    def normalize_labels(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [v.strip()] if v.strip() else []
        if not isinstance(v, list):
            return []
        return [str(item).strip() for item in v if str(item).strip()]

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v: Any) -> Literal["low", "medium", "high"]:
        if not v:
            return "medium"
        norm = str(v).lower().strip()
        if norm not in ("low", "medium", "high"):
            return "medium"
        return norm  # type: ignore[return-value]

    @field_validator("duplicate_ids", mode="before")
    @classmethod
    def normalize_duplicates(cls, v: Any) -> list[int]:
        if not v:
            return []
        if isinstance(v, list):
            try:
                return [int(x) for x in v if str(x).strip()]
            except (ValueError, TypeError):
                return []
        return []


class Comment(BaseModel):
    """A single line-specific comment in a PR review."""

    line: int = Field(default=0, ge=0)
    content: str = Field(..., min_length=10)
    severity: Literal["low", "medium", "high"] = "medium"
    path: str | None = None

    @field_validator("content")
    @classmethod
    def content_meaningful(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 10:
            raise ValueError("Comment content must be at least 10 characters")
        return stripped


class Review(BaseModel):
    """Structured PR review result with verdict, comments and security notes."""

    verdict: Literal["approve", "request_changes", "comment"] = "comment"
    summary: str
    comments: list[Comment] = Field(default_factory=list)
    security_flags: list[str] = Field(default_factory=list)
    reasoning: str | None = None

    @field_validator("summary")
    @classmethod
    def ensure_summary(cls, v: str | None) -> str:
        if not v or not str(v).strip():
            return "No summary provided."
        return str(v).strip()

    @field_validator("security_flags", mode="before")
    @classmethod
    def normalize_flags(cls, v: Any) -> list[str]:
        if not v:
            return []
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        return []


class ConfigRule(BaseModel):
    """A single project-specific automation rule.

    Used for validation and future extensibility (rules are currently
    stored as plain strings in Config but can be upgraded).
    """

    text: str = Field(..., min_length=8)
    category: Literal["style", "security", "process", "other"] | None = "other"
    example: str | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 12:
            raise ValueError(
                "Rule must be descriptive (minimum 12 characters after stripping)"
            )
        if stripped.lower().startswith(("always", "never")) and len(stripped) < 25:
            raise ValueError(
                "Rules starting with 'always' or 'never' must include context or examples"
            )
        return stripped

    def __str__(self) -> str:
        return self.text


__all__ = [
    "Issue",
    "PR",
    "TriageResult",
    "Review",
    "Comment",
    "ConfigRule",
]
