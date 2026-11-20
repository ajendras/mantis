"""Tests for PRReviewer.review().

Verifies verdict logic, structured comment parsing, security flag extraction,
prompt construction (including rule injection), and fallback behavior.
Uses fixtures from conftest.py for consistent mocks and sample data.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mantis.config import Config
from mantis.llm import LLM
from mantis.models import Review, Comment
from mantis.review import PRReviewer


def test_pr_reviewer_happy_path(mock_llm: MagicMock, sample_pr_diff: str) -> None:
    """Successful review path with approve verdict and no comments."""
    config = Config(rules=["Require tests for all new functions"])
    reviewer = PRReviewer(llm=mock_llm, config=config)

    mock_llm.query.return_value = {
        "verdict": "approve",
        "summary": "Changes are clean, well-tested, and respect project conventions.",
        "comments": [],
        "security_flags": [],
        "reasoning": "No issues found after thorough review.",
    }

    result = reviewer.review(
        diff=sample_pr_diff,
        context={
            "pr": {
                "title": "Refactor utils module",
                "number": 123,
                "body": "Improves readability.",
            }
        },
        rules=config.rules,
    )

    assert isinstance(result, Review)
    assert result.verdict == "approve"
    assert "clean" in result.summary.lower()
    assert len(result.comments) == 0
    assert len(result.security_flags) == 0
    assert result.reasoning == "No issues found after thorough review."

    # Verify correct prompt construction and LLM call
    mock_llm.query.assert_called_once()
    call_kwargs = mock_llm.query.call_args.kwargs
    assert call_kwargs.get("json_mode") is True
    assert "Require tests for all new functions" in call_kwargs["prompt"]
    assert "```diff" in call_kwargs["prompt"]
    assert sample_pr_diff[:50] in call_kwargs["prompt"]


def test_pr_reviewer_with_comments_and_security(mock_llm: MagicMock, sample_pr_diff: str) -> None:
    """Parse multiple line comments with varying severity and security flags."""
    config = Config()
    reviewer = PRReviewer(llm=mock_llm, config=config)

    mock_response = {
        "verdict": "request_changes",
        "summary": "Several issues need attention before merge.",
        "comments": [
            {
                "line": 12,
                "content": "This leaks the database credential. Use a secret manager.",
                "severity": "high",
                "path": "src/db.py",
            },
            {
                "line": 67,
                "content": "Consider using pathlib instead of os.path.",
                "severity": "medium",
            },
        ],
        "security_flags": ["credential_leak", "insecure_storage"],
        "reasoning": "Security issue is critical.",
    }
    mock_llm.query.return_value = mock_response

    result = reviewer.review(
        diff=sample_pr_diff,
        context={"pr": {"title": "Add database layer"}},
        rules=[],
    )

    assert isinstance(result, Review)
    assert result.verdict == "request_changes"
    assert "Several issues" in result.summary
    assert len(result.comments) == 2
    assert len(result.security_flags) == 2
    assert "credential_leak" in result.security_flags

    comment1 = result.comments[0]
    assert isinstance(comment1, Comment)
    assert comment1.line == 12
    assert comment1.severity == "high"
    assert "secret manager" in comment1.content.lower()
    assert comment1.path == "src/db.py"

    comment2 = result.comments[1]
    assert comment2.line == 67
    assert comment2.severity == "medium"


def test_review_respects_custom_rules(mock_llm: MagicMock, sample_pr_diff: str) -> None:
    """Custom rules must be injected into the system/context prompt."""
    rules = [
        "Never commit debug print statements",
        "All public functions must have comprehensive docstrings",
    ]
    config = Config(rules=rules)
    reviewer = PRReviewer(llm=mock_llm, config=config)

    mock_llm.query.return_value = {
        "verdict": "comment",
        "summary": "Reviewed per rules.",
        "comments": [],
        "security_flags": [],
    }

    reviewer.review(
        diff=sample_pr_diff,
        context={"pr": {"title": "Test PR"}},
        rules=rules,
    )

    prompt = mock_llm.query.call_args.kwargs["prompt"]
    for rule in rules:
        assert rule in prompt
    # Also check that format_review_prompt was used
    assert "PROJECT RULES (you MUST obey these)" in prompt
    assert "Never commit debug print statements" in prompt


def test_review_fallback_on_llm_error(sample_pr_diff: str) -> None:
    """Graceful fallback when LLM is unavailable (mirrors analyzer fallback pattern)."""
    mock_llm = MagicMock(spec=LLM)
    mock_llm.query.side_effect = RuntimeError("Failed to connect to Ollama")

    config = Config(rules=["Enforce PEP 8"])
    reviewer = PRReviewer(llm=mock_llm, config=config)

    result = reviewer.review(
        diff=sample_pr_diff,
        context={"pr": {"title": "Broken feature", "body": "Causes crash on large input"}},
        rules=config.rules,
    )

    assert isinstance(result, Review)
    assert result.verdict == "comment"  # safe default for fallback
    assert result.summary
    assert "fallback" in result.summary.lower() or "unavailable" in result.summary.lower()
    assert "Ollama" in result.summary or "LLM" in result.summary
    # No comments or flags in fallback to avoid hallucinated suggestions
    assert len(result.comments) == 0
    assert len(result.security_flags) == 0


def test_review_rejects_empty_diff(mock_llm: MagicMock) -> None:
    """Empty diff is rejected early (consistent with public API contract)."""
    config = Config()
    reviewer = PRReviewer(llm=mock_llm, config=config)

    with pytest.raises(ValueError, match="non-empty"):
        reviewer.review(
            diff="   ",
            context={},
            rules=[],
        )


def test_review_normalizes_comment_severity(mock_llm: MagicMock, sample_pr_diff: str) -> None:
    """LLM responses with invalid severity fall back to 'medium'."""
    config = Config()
    reviewer = PRReviewer(llm=mock_llm, config=config)

    mock_llm.query.return_value = {
        "verdict": "comment",
        "summary": "Minor observations.",
        "comments": [
            {
                "line": 5,
                "content": "Style nit: missing trailing comma.",
                "severity": "invalid_value",  # should be normalized by model
            }
        ],
        "security_flags": [],
    }

    result = reviewer.review(diff=sample_pr_diff, context={}, rules=[])

    assert len(result.comments) == 1
    assert result.comments[0].severity == "medium"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
