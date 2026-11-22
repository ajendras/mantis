"""Tests for PR review logic including fallback behavior."""

import pytest
from unittest.mock import Mock

from mantis.config import Config
from mantis.llm import LLM
from mantis.models import Review
from mantis.review import PRReviewer


@pytest.fixture
def mock_llm():
    llm = Mock(spec=LLM)
    llm.query.return_value = {
        "verdict": "comment",
        "summary": "Looks good overall.",
        "comments": [],
        "security_flags": [],
        "reasoning": "All rules followed.",
    }
    return llm


@pytest.fixture
def sample_pr():
    return {
        "title": "Broken feature",
        "number": 123,
        "html_url": "https://github.com/owner/repo/pull/123",
    }


def test_review_fallback_on_llm_error(mock_llm, sample_pr):
    mock_llm.query.side_effect = RuntimeError("Failed to connect to Ollama")
    config = Config()
    reviewer = PRReviewer(llm=mock_llm, config=config)
    diff = "diff --git a/file.py b/file.py\n+ broken code"
    result: Review = reviewer.review(
        diff=diff, context={"pr": sample_pr, "repo_rules": []}
    )
    assert result.verdict == "comment"
    assert (
        "Automated review could not be completed because the local LLM is unavailable"
        in result.summary
    )
    assert "Fallback review (LLM unavailable)" in result.reasoning


def test_review_fallback_has_reasoning(mock_llm, sample_pr):
    mock_llm.query.side_effect = RuntimeError("some error")
    config = Config()
    reviewer = PRReviewer(llm=mock_llm, config=config)
    diff = "some diff"
    result = reviewer.review(diff=diff, context={"pr": sample_pr})
    assert "some error" in str(result.reasoning)
    assert "Fallback review (LLM unavailable)" in str(result.reasoning)


def test_successful_review_with_rules(mock_llm):
    config = Config(rules=["Always add tests"])
    reviewer = PRReviewer(llm=mock_llm, config=config)
    result = reviewer.review(
        diff="valid diff", context={"pr": {"title": "Feature"}}
    )
    assert result.verdict in ("approve", "comment", "request_changes")
