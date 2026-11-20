"""Pytest fixtures for Mantis tests.

Provides reusable mocks and sample data for LLM, GitHub client,
issues, and PR diffs. All fixtures are designed for fast, deterministic
unit tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mantis.config import Config
from mantis.github import GitHubClient
from mantis.llm import LLM
from mantis.models import Issue


@pytest.fixture
def mock_llm() -> MagicMock:
    """Mock LLM instance that returns controlled JSON responses.

    By default returns a sensible triage result. Tests can override
    the return_value or side_effect as needed.
    """
    mock = MagicMock(spec=LLM)
    mock.query.return_value = {
        "labels": ["bug"],
        "priority": "medium",
        "assignee": None,
        "duplicate_ids": [],
        "reasoning": "Mock analysis for test",
    }
    return mock


@pytest.fixture
def mock_github_client() -> MagicMock:
    """Mock GitHubClient with realistic return values for tests."""
    mock = MagicMock(spec=GitHubClient)
    mock.list_recent_issues.return_value = [
        {
            "number": 5,
            "title": "Previous login bug",
            "body": "Users cannot log in after upgrade.",
            "html_url": "https://github.com/testowner/testrepo/issues/5",
        }
    ]
    mock.get_issue.return_value = {
        "number": 42,
        "title": "Test issue",
        "body": "Something is broken",
        "html_url": "https://github.com/testowner/testrepo/issues/42",
        "user": {"login": "testuser"},
    }
    mock.get_pr_diff.return_value = (
        "diff --git a/file.py b/file.py\n"
        "index 0000000..1111111 100644\n"
        "--- a/file.py\n"
        "+++ b/file.py\n"
        "@@ -1,3 +1,4 @@\n"
        "+print('hello')\n"
    )
    mock.list_recent_prs.return_value = []
    return mock


@pytest.fixture
def sample_issue() -> Issue:
    """A realistic bug report used across many tests."""
    return Issue(
        owner="testowner",
        repo="testrepo",
        number=42,
        title="Crash when clicking login button",
        body=(
            "After upgrading to v2.1 the login button causes a segmentation "
            "fault on Linux. Steps to reproduce:\n\n"
            "1. Open the app\n"
            "2. Click login\n"
            "3. Crash"
        ),
        html_url="https://github.com/testowner/testrepo/issues/42",
    )


@pytest.fixture
def sample_pr_diff() -> str:
    """A small but realistic unified diff for PR review tests."""
    return """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -23,7 +23,12 @@ def validate_token(token: str) -> bool:
     if not token:
         return False
-    return check_signature(token)
+    # TODO: add rate limiting
+    if is_expired(token):
+        return False
+    return check_signature(token) and not is_blacklisted(token)
+
+def is_expired(token: str) -> bool:
+    ...
"""


@pytest.fixture
def config_with_rules() -> Config:
    """Configuration object pre-populated with example rules."""
    return Config(
        model="llama3",
        rules=[
            "Never assign issues to unconfirmed contributors",
            "All security-related issues must receive the 'security' label",
        ],
    )


@pytest.fixture
def empty_history() -> list[Issue]:
    """Empty history list for tests that do not need context."""
    return []
