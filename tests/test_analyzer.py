"""Tests for analyzer.py - IssueAnalyzer, DuplicateDetector and fallback."""

from unittest.mock import Mock

import pytest

from mantis.analyzer import DuplicateDetector, IssueAnalyzer
from mantis.config import Config
from mantis.llm import LLM
from mantis.models import Issue, TriageResult


def test_duplicate_detector_no_history(mock_llm):
    detector = DuplicateDetector(llm=mock_llm)
    issue = Issue(owner="o", repo="r", number=1, title="t", body="b")
    assert detector.find_duplicates(issue, []) == []


def test_duplicate_detector_with_history(mock_llm):
    mock_llm.query.return_value = {"duplicate_ids": [5, 10], "confidence": "high"}
    detector = DuplicateDetector(llm=mock_llm)
    issue = Issue(owner="o", repo="r", number=42, title="New bug", body="desc")
    history = [
        Issue(owner="o", repo="r", number=5, title="Similar bug", body="desc...")
    ]
    dups = detector.find_duplicates(issue, history)
    assert dups == [5]


@pytest.fixture
def mock_llm():
    m = Mock(spec=LLM)
    m.query.return_value = {
        "labels": ["bug"],
        "priority": "medium",
        "assignee": None,
        "duplicate_ids": [],
        "reasoning": "reason",
    }
    return m


@pytest.fixture
def config():
    c = Config()
    c.rules = ["test rule"]
    return c


@pytest.fixture
def sample_issue():
    return Issue(
        owner="test",
        repo="test",
        number=42,
        title="Broken feature",
        body="It crashes",
    )


def test_fallback_includes_security_label(mock_llm, config):
    mock_llm.query.side_effect = RuntimeError("service unavailable")
    analyzer = IssueAnalyzer(llm=mock_llm, config=config)
    issue = Issue(
        owner="test",
        repo="test",
        number=99,
        title="Security flaw",
        body="This is a critical vulnerability that can lead to remote code execution.",
    )
    result = analyzer.analyze(issue=issue, history=[])
    assert "security" in result.labels
    assert result.priority == "high"
    assert "Fallback triage (LLM unavailable)" in result.reasoning


def test_triage_result_model_validation():
    result = TriageResult.model_validate(
        {
            "labels": "bug,crash",
            "priority": "high",
            "reasoning": "Test case for validation",
        }
    )
    assert result.labels == ["bug", "crash"]
    assert result.priority == "high"


def test_analyze_success(mock_llm, config, sample_issue):
    analyzer = IssueAnalyzer(llm=mock_llm, config=config)
    result = analyzer.analyze(sample_issue, [])
    assert isinstance(result, TriageResult)
    assert "bug" in result.labels
