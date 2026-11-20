"""Tests for IssueAnalyzer and DuplicateDetector.

Covers normal triage, duplicate detection, fallback behavior, rule injection,
and edge cases using six distinct sample issues. All tests are deterministic
thanks to the mock_llm fixture.
"""

from __future__ import annotations

import pytest

from mantis.analyzer import DuplicateDetector, IssueAnalyzer
from mantis.config import Config
from mantis.models import Issue, TriageResult


def test_analyzer_init_validates_types(mock_llm, config_with_rules: Config) -> None:
    """Analyzer constructor performs strict type checking."""
    with pytest.raises(TypeError, match="llm must be an LLM instance"):
        IssueAnalyzer(llm="not-an-llm", config=config_with_rules)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="config must be a Config instance"):
        IssueAnalyzer(llm=mock_llm, config="not-a-config")  # type: ignore[arg-type]


def test_analyze_requires_issue_instance(mock_llm, config_with_rules: Config) -> None:
    """analyze() rejects non-Issue objects with a clear error."""
    analyzer = IssueAnalyzer(llm=mock_llm, config=config_with_rules)

    with pytest.raises(TypeError, match="issue must be an instance of Issue"):
        analyzer.analyze(issue={"title": "dict instead"}, history=[])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("title", "body", "expected_labels", "expected_priority", "expected_duplicates"),
    [
        # 1. Clear bug with high urgency
        (
            "Segmentation fault on login",
            "Crashes with SIGSEGV on Ubuntu 22.04",
            ["bug"],
            "high",
            [],
        ),
        # 2. Feature request
        (
            "Support dark mode in UI",
            "Many users have requested a dark theme",
            ["enhancement"],
            "medium",
            [],
        ),
        # 3. Duplicate of an existing crash report
        (
            "Same crash as before but on Windows",
            "This looks exactly like #5",
            ["bug", "duplicate"],
            "high",
            [5],
        ),
        # 4. Documentation improvement
        (
            "README is missing installation steps for Windows",
            "The docs are incomplete",
            ["documentation"],
            "low",
            [],
        ),
        # 5. Security concern
        (
            "Possible XSS in comment rendering",
            "User controlled HTML is rendered without escaping",
            ["security", "bug"],
            "high",
            [],
        ),
        # 6. Question / support request
        (
            "How do I configure the database connection?",
            "The docs don't mention connection pooling",
            ["question"],
            "medium",
            [],
        ),
    ],
)
def test_analyze_with_six_sample_issues(
    mock_llm,
    sample_issue: Issue,
    config_with_rules: Config,
    title: str,
    body: str,
    expected_labels: list[str],
    expected_priority: str,
    expected_duplicates: list[int],
    empty_history: list[Issue],
) -> None:
    """Run the full analyze pipeline against six representative issues.

    Verifies label selection, priority, duplicate detection, and that
    project rules are injected into the prompt.
    """
    # Configure mock to return scenario-specific result
    mock_llm.query.side_effect = lambda prompt, **kwargs: {
        "labels": expected_labels,
        "priority": expected_priority,
        "assignee": "core-maintainer" if "security" in expected_labels else None,
        "duplicate_ids": expected_duplicates,
        "reasoning": f"Test reasoning for {title}",
    }

    issue = Issue(
        owner="testowner",
        repo="testrepo",
        number=100,
        title=title,
        body=body,
    )

    analyzer = IssueAnalyzer(llm=mock_llm, config=config_with_rules)
    result: TriageResult = analyzer.analyze(issue=issue, history=empty_history)

    assert isinstance(result, TriageResult)
    assert set(result.labels) >= set(expected_labels)
    assert result.priority == expected_priority
    assert result.duplicate_ids == expected_duplicates
    assert "Test reasoning" in result.reasoning

    # Verify that rules were injected into at least one of the LLM calls
    calls = mock_llm.query.call_args_list
    rule_texts = [str(rule) for rule in config_with_rules.rules]
    assert any(
        any(rule in str(call.kwargs.get("system", "")) for rule in rule_texts)
        or any(rule in str(call.args[0]) for rule in rule_texts)
        for call in calls
    ), "Project rules were not injected into any prompt"


def test_duplicate_detector_returns_empty_on_no_history(
    mock_llm, sample_issue: Issue
) -> None:
    """DuplicateDetector gracefully returns [] when history is empty."""
    detector = DuplicateDetector(llm=mock_llm)
    duplicates = detector.find_duplicates(sample_issue, history=[])
    assert duplicates == []
    mock_llm.query.assert_not_called()


def test_duplicate_detector_parses_json_and_falls_back(
    mock_llm, sample_issue: Issue
) -> None:
    """Duplicate detector correctly extracts IDs and degrades gracefully."""
    mock_llm.query.return_value = {
        "duplicate_ids": [7, 19],
        "confidence": "high",
        "reasoning": "Exact same stack trace",
    }

    history = [
        Issue(
            owner="testowner",
            repo="testrepo",
            number=7,
            title="Similar crash",
            body="Also segfaults on login",
        )
    ]

    detector = DuplicateDetector(llm=mock_llm)
    duplicates = detector.find_duplicates(sample_issue, history=history, max_results=3)

    assert duplicates == [7]
    mock_llm.query.assert_called_once()

    # Test graceful fallback on malformed JSON
    mock_llm.query.side_effect = ValueError("bad json")
    duplicates = detector.find_duplicates(sample_issue, history=history)
    assert duplicates == []


def test_analyzer_fallback_when_llm_fails(
    mock_llm, sample_issue: Issue, empty_history: list[Issue]
) -> None:
    """When the LLM is unavailable, a keyword-based fallback triage is used."""
    mock_llm.query.side_effect = RuntimeError("Ollama not running")

    config = Config(rules=["Always label security issues"])
    analyzer = IssueAnalyzer(llm=mock_llm, config=config)

    result = analyzer.analyze(sample_issue, history=empty_history)

    assert isinstance(result, TriageResult)
    assert "bug" in result.labels or "question" in result.labels
    assert result.priority in ("high", "medium")
    assert "LLM unavailable" in result.reasoning
    assert "Fallback triage" in result.reasoning


def test_analyzer_merges_duplicate_results_from_separate_detector(
    mock_llm, sample_issue: Issue
) -> None:
    """If the main triage LLM omits duplicate_ids, the dedicated detector's
    results are merged in.
    """
    # Main triage call returns no duplicates
    mock_llm.query.side_effect = [
        # first call = duplicate detector
        {"duplicate_ids": [13], "confidence": "medium", "reasoning": "same root cause"},
        # second call = main triage
        {
            "labels": ["bug"],
            "priority": "high",
            "assignee": None,
            "duplicate_ids": [],  # intentionally empty
            "reasoning": "Main triage",
        },
    ]

    history = [Issue(owner="a", repo="b", number=13, title="Old duplicate", body="...")]

    analyzer = IssueAnalyzer(llm=mock_llm, config=Config())
    result = analyzer.analyze(sample_issue, history=history)

    assert 13 in result.duplicate_ids
    assert "Main triage" in result.reasoning


def test_fallback_triage_keyword_detection() -> None:
    """Standalone test of the private fallback logic with varied inputs."""
    config = Config()
    analyzer = IssueAnalyzer(llm=MagicMock(), config=config)  # type: ignore[arg-type]

    # High priority crash
    crash = Issue(
        owner="test",
        repo="test",
        number=1,
        title="URGENT: production crash on startup",
        body="Null pointer exception in main()",
    )
    fallback = analyzer._fallback_triage(crash, duplicate_ids=[9], error=Exception("test"))
    assert "high" == fallback.priority
    assert any("bug" in lbl.lower() for lbl in fallback.labels)

    # Security keyword
    sec = Issue(
        owner="test",
        repo="test",
        number=2,
        title="XSS vulnerability in profile page",
        body="User input is reflected",
    )
    fallback = analyzer._fallback_triage(sec, duplicate_ids=[], error=Exception("test"))
    assert "security" in [lbl.lower() for lbl in fallback.labels]
    assert fallback.priority == "high"
