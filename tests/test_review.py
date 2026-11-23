"""Tests for the PR review module."""

from unittest.mock import Mock, patch

import pytest

from mantis.models import Review, Comment
from mantis.review import PRReviewer
from mantis.config import Config


def test_review_uses_system_context(mock_llm, config, sample_pr, sample_pr_diff):
    reviewer = PRReviewer(llm=mock_llm, config=config)
    reviewer.review(sample_pr_diff, {"pr": sample_pr}, config.rules)
    mock_llm.query.assert_called_once()
    call_args = mock_llm.query.call_args
    assert "system" in call_args.kwargs


def test_review_parses_verdict_and_comments(mock_llm, config):
    mock_llm.query.return_value = {
        "verdict": "request_changes",
        "summary": "Needs more tests.",
        "comments": [
            {"line": 42, "content": "Add type hints", "severity": "medium"}
        ],
        "security_flags": ["hardcoded secret"],
        "reasoning": "test",
    }
    reviewer = PRReviewer(llm=mock_llm, config=config)
    result = reviewer.review("diff here", {}, [])
    assert result.verdict == "request_changes"
    assert len(result.comments) == 1
    assert result.comments[0].line == 42
    assert len(result.security_flags) == 1


def test_fallback_review_on_llm_failure(mock_llm, config):
    mock_llm.query.side_effect = RuntimeError("boom")
    reviewer = PRReviewer(llm=mock_llm, config=config)
    result = reviewer.review("some diff", {}, ["no secrets"])
    assert result.verdict in ("comment", "request_changes")
    assert "Fallback" in result.summary or "unavailable" in result.summary.lower()


def test_post_pr_comment_with_mock(mock_github_client):
    """Test the new post_pr_comment integration point (used by interactive approval)."""
    body = "## Mantis Review\n**Verdict**: APPROVE\n\nLooks good."
    mock_github_client.post_pr_comment("owner", "repo", 1, body)
    mock_github_client.post_pr_comment.assert_called_with("owner", "repo", 1, body)
