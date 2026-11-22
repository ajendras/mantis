"""Configuration management for Mantis.

Pydantic Settings with environment variable support, rule validation,
and helpful error messages. Secure defaults and local-first design.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Mantis configuration.

    Loaded from environment variables (MANTIS_* prefix), .env files,
    and supports optional project config file. All values have
    production-safe defaults.
    """

    model: str = Field(
        default="llama3",
        description="Ollama model name (or any OpenAI-compatible local endpoint)",
    )
    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Sampling temperature for the LLM",
    )
    github_token: str | None = Field(
        default=None,
        description="GitHub PAT. Only needed for private repos or higher rate limits.",
    )
    platform: Literal["github", "gitlab"] = Field(
        default="github",
        description="Version control platform (github or gitlab)",
    )
    gitlab_token: str | None = Field(
        default=None,
        description="GitLab PAT. Falls back to github_token if not set.",
    )
    gitlab_url: str = Field(
        default="https://gitlab.com",
        description="Base URL of your GitLab instance (supports self-hosted)",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL of the Ollama (or compatible) server",
    )
    max_tokens: int = Field(
        default=4096,
        gt=100,
        description="Maximum tokens to request from the model",
    )
    rules: list[str] = Field(
        default_factory=list,
        description="Project-specific rules the LLM must follow on every run",
    )
    repo_path: Path = Field(
        default_factory=Path.cwd,
        description="Root directory of the repository",
    )

    model_config = SettingsConfigDict(
        env_prefix="MANTIS_",
        env_file=(".env", ".mantis.env"),
        env_ignore_empty=True,
        extra="forbid",
        validate_default=True,
        json_schema_extra={"populate_by_name": True},
    )

    @model_validator(mode="after")
    def validate_after_load(self) -> "Config":
        """Run custom validation after settings are populated."""
        self.validate_rules()
        return self

    @classmethod
    def load(cls, config_path: Path | None = None) -> "Config":
        """Load configuration, optionally from a JSON config file.

        If a config file is provided and exists, it is merged on top of
        environment variables.
        """
        if config_path is None:
            config_path = Path(".mantis/config.json")

        if config_path.exists():
            try:
                with open(config_path) as f:
                    file_config = json.load(f)
                return cls.model_validate({**file_config})
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise ValueError(
                    f"Failed to load config from {config_path}: {exc}"
                ) from exc

        return cls()

    def validate_rules(self) -> None:
        """Validate custom automation rules with clear, actionable messages."""
        if not isinstance(self.rules, list):
            raise TypeError(
                "MANTIS_RULES must be a list of strings. "
                "Example: MANTIS_RULES='[\"never suggest closing without asking\"]'"
            )

        for i, rule in enumerate(self.rules):
            if not isinstance(rule, str):
                raise TypeError(f"rules[{i}] must be a string, got {type(rule).__name__}")
            stripped = rule.strip()
            if len(stripped) < 8:
                raise ValueError(
                    f"Rule {i+1} is too vague ({len(stripped)} chars). "
                    "Provide clear, actionable maintainer guidance."
                )
            if stripped.lower().startswith(("always", "never")) and len(stripped) < 20:
                raise ValueError(
                    f"Rule {i+1} looks incomplete. Expand it with context or examples."
                )

        # Detect near-duplicate rules
        normalized = {r.lower().strip() for r in self.rules}
        if len(normalized) != len(self.rules):
            raise ValueError(
                "Duplicate or near-duplicate rules detected. "
                "Each rule must express a distinct policy."
            )

    def get_system_context(self) -> str:
        """Return a system prompt fragment containing project rules and context.

        Used by LLM calls throughout the codebase.
        """
        lines = [
            "You are an expert, opinionated maintainer for this project.",
            "You have deep knowledge of its architecture, conventions, and values.",
            "",
            "=== PROJECT RULES (you MUST follow these on every response) ===",
        ]

        if self.rules:
            for i, rule in enumerate(self.rules, 1):
                lines.append(f"{i}. {rule}")
        else:
            lines.append("(no custom rules defined)")

        lines.extend(
            [
                "",
                "=== TONE & STYLE ===",
                "• Be concise, constructive, and kind.",
                "• Use the project's existing terminology.",
                "• Never suggest changes that contradict the rules above.",
                "",
                "Answer in markdown with clear sections when appropriate.",
            ]
        )

        return "\n".join(lines)

    def get_llm_kwargs(self) -> dict[str, Any]:
        """Return a dict suitable for instantiating the LLM class."""
        return {
            "model": self.model,
            "temperature": self.temperature,
            "base_url": self.ollama_base_url,
            "max_tokens": self.max_tokens,
        }

    def save(self, path: Path | None = None) -> Path:
        """Persist configuration to a JSON file (useful after `mantis init`)."""
        if path is None:
            path = Path(".mantis/config.json")
        path.parent.mkdir(parents=True, exist_ok=True)

        data = self.model_dump(
            mode="json",
            exclude={"repo_path"},
            exclude_unset=True,
        )
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        return path
