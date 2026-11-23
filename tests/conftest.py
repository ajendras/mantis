import pytest
from unittest.mock import Mock

from mantis.config import Config
from mantis.models import Issue, PR


@pytest.fixture(scope="function")
def config():
    c = Config()
    c.rules = ["Always add tests for new features"]
    return c


@pytest.fixture
def mock_llm():
    m = Mock()
    m.query.return_value = {
        "labels": ["bug"],
        "priority": "medium",
        "assignee": None,
        "duplicate_ids": [],
        "reasoning": "test",
        "verdict": "approve",
        "summary": "All looks good.",
        "comments": [],
        "security_flags": [],
    }
    return m


@pytest.fixture
def mock_github_client():
    client = Mock()
    client.get_issue.return_value = {
        "title": "Test Issue",
        "body": "Test body",
        "number": 42,
        "user": {"login": "tester"},
        "html_url": "https://github.com/owner/repo/issues/42",
    }
    client.get_merge_request.return_value = {
        "title": "Test PR",
        "body": "PR body",
        "number": 57,
    }
    client.get_mr_diff.return_value = "diff --git a/file.py b/file.py\n..."
    client.list_recent_issues.return_value = []
    client.list_recent_prs.return_value = []
    client.post_pr_comment = Mock(return_value={"id": 123})
    return client


@pytest.fixture
def sample_issue():
    return Issue(
        owner="owner",
        repo="repo",
        number=42,
        title="Test issue",
        body="This is a test",
    )


@pytest.fixture
def sample_pr():
    return PR(
        owner="owner",
        repo="repo",
        number=57,
        title="Test PR",
        body="Changes...",
    )


@pytest.fixture
def sample_pr_diff():
    return """diff --git a/src/mantis/cli.py b/src/mantis/cli.py
--- a/src/mantis/cli.py
+++ b/src/mantis/cli.py
@@ -10,6 +10,7 @@ def test():
"""
