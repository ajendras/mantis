"""Test suite for the Mantis issue analyzer and duplicate detection logic.

Covers JSON parsing, fallback paths, keyword-based triage, rule injection,
model validation and merging of duplicate results from the dedicated
detector.
"""

from unittest.mock import MagicMock, patch

import pytest

from mantis.analyzer import DuplicateDetector, IssueAnalyzer
from mantis.config import Config
from mantis.models import Issue, TriageResult


@pytest.fixture
def config() -> Config:
    c = Config(model="llama3", temperature=0.0, rules=["Always include reproduction steps"])
    return c


@pytest.fixture
def sample_issue() -> Issue:
    return Issue.model_validate({
        "owner": "ajendras",
        "repo": "mantis",
        "number": 42,
        "title": "Segmentation fault on login",
        "body": "Crashes with SIGSEGV when logging in with special chars.",
        "html_url": "https://github.com/ajendras/mantis/issues/42",
    })


@pytest.fixture
def history() -> list[Issue]:
    return [
        Issue.model_validate({
            "owner": "ajendras",
            "repo": "mantis",
            "number": 7,
            "title": "Login crash on Windows",
            "body": "Similar SIGSEGV in auth module.",
        }),
        Issue.model_validate({
            "owner": "ajendras",
            "repo": "mantis",
            "number": 19,
            "title": "Another login bug",
            "body": "Login fails with memory error.",
        }),
    ]


def test_duplicate_detector_parses_json_and_falls_back(
    mock_llm, sample_issue, history
):
    detector = DuplicateDetector(llm=mock_llm)
    mock_llm.query.return_value = {
        "duplicate_ids": [7, 19],
        "confidence": "high",
        "reasoning": "Both report same SIGSEGV in login",
    }
    duplicates = detector.find_duplicates(sample_issue, history, max_results=5)
    assert duplicates == [7, 19]

    mock_llm.query.reset_mock()
    mock_llm.query.side_effect = RuntimeError("connection error")
    duplicates = detector.find_duplicates(sample_issue, history)
    assert duplicates == []


def test_fallback_triage_keyword_detection(config):
    analyzer = IssueAnalyzer(llm=MagicMock(), config=config)  # type: ignore[arg-type]
    issue = Issue(
        owner="ajendras",
        repo="mantis",
        number=101,
        title="Urgent: crash in production",
        body="Getting segmentation fault on startup in prod environment.",
    )
    result = analyzer._fallback_triage(issue, [7], ValueError("LLM down"))
    assert "bug" in result.labels
    assert "security" not in result.labels
    assert result.priority == "high"
    assert result.duplicate_ids == [7]
    assert "Fallback triage (LLM unavailable)" in result.reasoning


def test_analyzer_uses_rules(mock_llm, config, sample_issue):
    config.rules = ["Never assign to junior devs", "Always label as bug if crash"]
    analyzer = IssueAnalyzer(llm=mock_llm, config=config)
    mock_llm.query.return_value = {
        "labels": ["bug", "crash"],
        "priority": "high",
        "assignee": None,
        "duplicate_ids": [7],
        "reasoning": "Matches rule for crashes",
    }
    result = analyzer.analyze(sample_issue, [])
    assert "bug" in result.labels
    assert result.priority == "high"
    assert "rule" in result.reasoning.lower()


def test_analyzer_fallback_on_llm_error(mock_llm, config, sample_issue):
    analyzer = IssueAnalyzer(llm=mock_llm, config=config)
    mock_llm.query.side_effect = RuntimeError("Failed to connect to Ollama")
    result = analyzer.analyze(sample_issue, [])
    assert "bug" in result.labels
    assert result.priority == "high"
    assert "Fallback triage (LLM unavailable)" in result.reasoning


@patch("mantis.analyzer.DuplicateDetector.find_duplicates")
def test_analyze_merges_duplicate_ids(
    mock_find_duplicates, mock_llm, config, sample_issue, history
):
    mock_find_duplicates.return_value = [7, 19]
    analyzer = IssueAnalyzer(llm=mock_llm, config=config)
    mock_llm.query.return_value = {
        "labels": ["bug"],
        "priority": "medium",
        "assignee": None,
        "duplicate_ids": [],
        "reasoning": "test",
    }
    result = analyzer.analyze(sample_issue, history)
    assert result.duplicate_ids == [7, 19]
    mock_find_duplicates.assert_called_once()


def test_analyzer_rejects_invalid_issue(config):
    analyzer = IssueAnalyzer(llm=MagicMock(), config=config)
    with pytest.raises(TypeError, match="must be an instance of Issue"):
        analyzer.analyze({"title": "bad"}, [])


def test_duplicate_detector_empty_history(mock_llm, sample_issue):
    detector = DuplicateDetector(llm=mock_llm)
    assert detector.find_duplicates(sample_issue, []) == []


def test_fallback_includes_security_label(config):
    analyzer = IssueAnalyzer(llm=MagicMock(), config=config)
    issue = Issue(
        owner="ajendras",
        repo="mantis",
        number=5,
        title="XSS vulnerability in form",
        body="Can inject script tags.",
    )
    result = analyzer._fallback_triage(issue, [], None)  # type: ignore[arg-type]
    assert "security" in result.labels
    assert result.priority == "high"


def test_triage_result_model_validation():
    data = {
        "labels": "bug,crash",
        "priority": "HIGH",
        "duplicate_ids": ["19"],
        "reasoning": "test",
    }
    result = TriageResult.model_validate(data)
    assert result.labels == ["bug", "crash"]
    assert result.priority == "high"
    assert result.duplicate_ids == [19]
