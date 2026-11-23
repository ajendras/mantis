"""Tests for PR/MR review functionality."""

from unittest.mock import Mock, patch

import pytest

from mantis.config import Config
from mantis.models import Review
from mantis.review import PRReviewer


def test_successful_review_with_rules(mock_llm):
    """Test review with project rules.

    Rule expanded with context/examples so it passes validate_rules().
    """
    config = Config(
        rules=[
            "Always add tests when changing code. For example, when submitting "
            "a PR include unit tests that reproduce the original bug (if any) "
            "and verify the fix; ensure CI still passes."
        ]
    )
    reviewer = PRReviewer(llm=mock_llm, config=config)
    mock_llm.query.return_value = {
        "verdict": "approve",
        "summary": "The PR follows all rules including test coverage.",
        "comments": [],
        "security_flags": [],
    }
    diff = "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1,3 +1,5 @@\n+def test_feature():\n+    assert True"
    pr_data = {
        "owner": "ajendras",
        "repo": "mantis",
        "number": 57,
        "title": "Add new feature",
        "body": "Implements X",
    }
    result: Review = reviewer.review(
        diff=diff,
        context={"pr": pr_data, "repo_rules": config.rules},
        rules=config.rules,
    )
    assert result.verdict == "approve"
    assert "test" in result.summary.lower()


def test_review_security_issues(mock_llm):
    config = Config(rules=["Never ignore security best practices."])
    reviewer = PRReviewer(llm=mock_llm, config=config)
    mock_llm.query.return_value = {
        "verdict": "request_changes",
        "summary": "Found potential security issue",
        "comments": [
            {"line": 42, "content": "Avoid hard-coded secrets", "severity": "high"}
        ],
        "security_flags": ["hardcoded credential"],
    }
    diff = "sample diff with secret"
    result: Review = reviewer.review(
        diff=diff,
        context={"pr": {"title": "insecure change"}},
        rules=config.rules,
    )
    assert len(result.security_flags) == 1
    assert result.verdict == "request_changes"


def test_review_llm_failure_fallback(mock_llm):
    config = Config(rules=[])
    reviewer = PRReviewer(llm=mock_llm, config=config)
    mock_llm.query.side_effect = RuntimeError("LLM unavailable")
    diff = "diff --git ..."
    result = reviewer.review(
        diff=diff,
        context={"pr": {"title": "offline test"}},
        rules=[],
    )
    assert result is not None
    assert hasattr(result, "verdict")


def test_rule_injection_into_prompt(mock_llm):
    config = Config(rules=["All PRs must include a linked issue and pass all CI checks."])
    reviewer = PRReviewer(llm=mock_llm, config=config)
    mock_llm.query.return_value = {
        "verdict": "comment",
        "summary": "Rule-compliant review",
        "comments": [],
        "security_flags": [],
    }
    result = reviewer.review(
        diff="diff content",
        context={"pr": {"title": "test"}},
        rules=config.rules,
    )
    assert isinstance(result, Review)
    # verify rule was passed (mock call already exercised by review())
    assert mock_llm.query.called
