"""Tests for the PR/MR review functionality."""

from unittest.mock import Mock

import pytest

from mantis.config import Config
from mantis.models import Review, Comment, PR
from mantis.review import PRReviewer


def test_review_uses_system_context(
    mock_llm, sample_pr_diff, sample_pr, mock_config
):
    """Verify that review passes the system context from config to the LLM."""
    reviewer = PRReviewer(llm=mock_llm, config=mock_config)
    mock_config.get_system_context.return_value = "You are an expert maintainer..."

    mock_llm.query.return_value = {
        "verdict": "approve",
        "summary": "Looks good.",
        "comments": [],
        "security_flags": [],
        "reasoning": "all clear",
    }

    reviewer.review(sample_pr_diff, {"pr": sample_pr}, mock_config.rules)

    mock_llm.query.assert_called_once()
    call_kwargs = mock_llm.query.call_args.kwargs
    assert "system" in call_kwargs
    assert "expert maintainer" in call_kwargs["system"]
    assert call_kwargs["json_mode"] is True


def test_review_parses_verdict_and_comments(
    mock_llm, sample_pr_diff, mock_config
):
    """Check that the LLM JSON response is turned into a Review model."""
    reviewer = PRReviewer(llm=mock_llm, config=mock_config)
    mock_response = {
        "verdict": "request_changes",
        "summary": "Needs more tests",
        "comments": [
            {
                "line": 42,
                "content": "Add docstring here",
                "severity": "medium",
            }
        ],
        "security_flags": ["hardcoded secret"],
        "reasoning": "test coverage low",
    }
    mock_llm.query.return_value = mock_response

    result = reviewer.review(sample_pr_diff, {}, mock_config.rules)

    assert isinstance(result, Review)
    assert result.verdict == "request_changes"
    assert result.summary == "Needs more tests"
    assert len(result.comments) == 1
    assert result.comments[0].line == 42
    assert result.comments[0].content == "Add docstring here"
    assert result.security_flags == ["hardcoded secret"]


def test_fallback_review_on_llm_failure(
    mock_llm, sample_pr_diff, mock_config
):
    """Ensure graceful fallback when the LLM raises an exception."""
    reviewer = PRReviewer(llm=mock_llm, config=mock_config)
    mock_llm.query.side_effect = RuntimeError("Ollama not available")

    result = reviewer.review("some diff", {}, ["no secrets"])

    assert isinstance(result, Review)
    assert result.verdict == "comment"
    assert "unavailable" in result.summary.lower() or "error" in result.summary.lower()
    assert len(result.comments) == 1
    assert "manually" in result.comments[0].content.lower()
    assert result.security_flags == []


def test_review_accepts_context_with_pr_model(
    mock_llm, sample_pr_diff, mock_config, sample_pr
):
    """Test that context with PR object (or dict) is properly handled in prompt."""
    reviewer = PRReviewer(llm=mock_llm, config=mock_config)
    mock_llm.query.return_value = {
        "verdict": "approve",
        "summary": "Good work",
        "comments": [],
        "security_flags": [],
        "reasoning": "ok",
    }

    context = {"pr": sample_pr, "extra": "data"}
    result = reviewer.review(sample_pr_diff, context, mock_config.rules)

    assert isinstance(result, Review)
    assert result.verdict == "approve"
    mock_llm.query.assert_called_once()
