"""Test suite for the Mantis PR review engine.

Covers structured JSON output, verdict logic, line-specific comments,
security flag detection, rule injection and graceful LLM fallback.
"""

from unittest.mock import MagicMock

import pytest

from mantis.config import Config
from mantis.models import Comment, Review
from mantis.review import PRReviewer


@pytest.fixture
def config() -> Config:
    return Config(model="llama3", rules=["Never use print statements in production code"])


@pytest.fixture
def sample_diff() -> str:
    return """diff --git a/src/mantis/analyzer.py b/src/mantis/analyzer.py
--- a/src/mantis/analyzer.py
+++ b/src/mantis/analyzer.py
@@ -10,6 +10,7 @@ def find_duplicates(...):
+    print("fixed")
"""


def test_review_success(mock_llm, config, sample_diff):
    reviewer = PRReviewer(llm=mock_llm, config=config)
    mock_llm.query.return_value = {
        "verdict": "approve",
        "summary": "Looks good, follows all rules.",
        "comments": [],
        "security_flags": [],
        "reasoning": "clean",
    }
    result = reviewer.review(
        diff=sample_diff,
        context={"pr": {"title": "Good PR", "number": 57}},
        rules=config.rules,
    )
    assert result.verdict == "approve"
    assert len(result.comments) == 0
    assert "good" in result.summary.lower()


def test_review_fallback_on_llm_error(mock_llm, config, sample_diff):
    reviewer = PRReviewer(llm=mock_llm, config=config)
    mock_llm.query.side_effect = RuntimeError("Failed to connect to Ollama")
    result: Review = reviewer.review(
        diff=sample_diff,
        context={"pr": {"title": "Broken feature"}},
        rules=config.rules,
    )
    assert result.verdict == "comment"
    assert "Fallback review for 'Broken feature' (LLM unavailable)" in result.summary
    assert len(result.comments) == 1
    assert (
        "Automated review could not be completed because the local LLM endpoint is unavailable. "
        "Please review the changes manually."
        in result.comments[0].content
    )
    assert result.comments[0].severity == "medium"
    assert "Static fallback analysis. Original error: Failed to connect to Ollama" in str(
        result.reasoning
    )


def test_review_includes_security_flag(mock_llm, config, sample_diff):
    reviewer = PRReviewer(llm=mock_llm, config=config)
    mock_llm.query.return_value = {
        "verdict": "request_changes",
        "summary": "Has security issue",
        "comments": [
            {
                "line": 12,
                "content": "Avoid hardcoded keys",
                "severity": "high",
            }
        ],
        "security_flags": ["hardcoded_secret"],
        "reasoning": "sec",
    }
    result = reviewer.review(
        diff=sample_diff,
        context={"pr": {"title": "Add feature"}},
        rules=[],
    )
    assert "hardcoded_secret" in result.security_flags
    assert len(result.comments) == 1
    assert result.comments[0].line == 12


def test_review_respects_rules(mock_llm, config, sample_diff):
    config.rules = ["Never use print statements in production code"]
    reviewer = PRReviewer(llm=mock_llm, config=config)
    mock_llm.query.return_value = {
        "verdict": "request_changes",
        "summary": "Violates rule about print()",
        "comments": [
            {
                "line": 5,
                "content": "Replace print with proper logging.",
                "severity": "medium",
            }
        ],
        "security_flags": [],
        "reasoning": "rule violation",
    }
    result = reviewer.review(
        diff=sample_diff,
        context={"pr": {"title": "Add debug"}},
        rules=config.rules,
    )
    assert result.verdict == "request_changes"
    assert any("logging" in c.content for c in result.comments)


def test_pr_reviewer_validates_types(config):
    reviewer = PRReviewer(llm=MagicMock(), config=config)
    with pytest.raises(ValueError, match="diff must be a non-empty string"):
        reviewer.review(diff="", context={}, rules=[])


def test_review_model_default_values():
    review = Review(
        verdict="comment",
        summary="Needs work.",
    )
    assert len(review.comments) == 0
    assert len(review.security_flags) == 0


def test_comment_model_validation():
    comment = Comment(
        line=10,
        content="This function needs better error handling to prevent crashes.",
        severity="high",
    )
    assert comment.line == 10
    assert "error handling" in comment.content


def test_review_fallback_has_reasoning(mock_llm, config, sample_diff):
    reviewer = PRReviewer(llm=mock_llm, config=config)
    mock_llm.query.side_effect = Exception("some error")
    result = reviewer.review(
        diff=sample_diff, context={"pr": {"title": "Test"}}, rules=config.rules
    )
    assert result.reasoning is not None
    assert "Original error" in str(result.reasoning)
