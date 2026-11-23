"""Tests for issue analysis, duplicate detection and fallback behavior."""

from unittest.mock import Mock, patch

import pytest

from mantis.analyzer import DuplicateDetector, IssueAnalyzer
from mantis.config import Config
from mantis.models import Issue, TriageResult


def test_duplicate_detector_with_history(mock_llm):
    """Test that duplicate detector returns all high-confidence IDs from the LLM.

    Updated assertion to match realistic multi-match behavior while staying
    conservative per the detector prompt.
    """
    detector = DuplicateDetector(llm=mock_llm)
    issue = Issue(
        owner="ajendras",
        repo="mantis",
        number=42,
        title="Crash on login with Python 3.12",
        body="Segmentation fault on authentication flow.",
    )
    history = [
        Issue(
            owner="ajendras",
            repo="mantis",
            number=5,
            title="Similar segfault on login",
            body="Gets segmentation fault when logging in.",
        ),
        Issue(
            owner="ajendras",
            repo="mantis",
            number=10,
            title="Python 3.12 login crash",
            body="Same traceback on 3.12.",
        ),
    ]
    mock_llm.query.return_value = {
        "duplicate_ids": [5, 10],
        "confidence": "high",
        "reasoning": "Identical root cause (segfault in login).",
    }
    dups = detector.find_duplicates(issue, history)
    assert dups == [5, 10]


def test_duplicate_detector_no_history(mock_llm):
    detector = DuplicateDetector(llm=mock_llm)
    issue = Issue(
        owner="test",
        repo="test",
        number=1,
        title="Test issue",
        body="Test body",
    )
    assert detector.find_duplicates(issue, []) == []


def test_duplicate_detector_llm_failure(mock_llm):
    detector = DuplicateDetector(llm=mock_llm)
    mock_llm.query.side_effect = RuntimeError("LLM offline")
    issue = Issue(
        owner="test",
        repo="test",
        number=1,
        title="Test issue",
        body="Test body",
    )
    history = [Issue(owner="test", repo="test", number=5, title="Similar", body="Similar")]
    dups = detector.find_duplicates(issue, history)
    assert dups == []  # graceful fallback


def test_analyzer_with_rules(mock_llm, sample_issue):
    config = Config(rules=["Follow PEP 8 style and always include docstrings for public functions."])
    analyzer = IssueAnalyzer(llm=mock_llm, config=config)
    history = []
    result = analyzer.analyze(sample_issue, history)
    assert isinstance(result, TriageResult)
    assert len(result.labels) > 0
    assert result.reasoning


def test_analyzer_fallback_on_llm_failure(mock_llm):
    config = Config(rules=[])
    analyzer = IssueAnalyzer(llm=mock_llm, config=config)
    issue = Issue(
        owner="testowner",
        repo="testrepo",
        number=99,
        title="This is a bug in the parser",
        body="It fails with TypeError",
    )
    mock_llm.query.side_effect = RuntimeError("simulated LLM failure")
    result = analyzer.analyze(issue, [])
    assert any("bug" in lbl.lower() for lbl in result.labels)
    assert result.priority in ("medium", "high")
    assert "Fallback triage" in result.reasoning


def test_analyzer_merges_detector_duplicates(mock_llm):
    config = Config(rules=[])
    analyzer = IssueAnalyzer(llm=mock_llm, config=config)
    issue = Issue(
        owner="testowner",
        repo="testrepo",
        number=100,
        title="New feature request",
        body="Please add X",
    )
    mock_llm.query.return_value = {
        "labels": ["enhancement"],
        "priority": "low",
        "assignee": None,
        "duplicate_ids": [],
        "reasoning": "New request",
    }
    with patch.object(analyzer.duplicate_detector, "find_duplicates", return_value=[7, 8]):
        result = analyzer.analyze(issue, [Mock()])
        assert result.duplicate_ids == [7, 8]
