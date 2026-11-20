"""Runnable example demonstrating the Mantis public API for issue triage.

Loads a realistic mock issue, runs the complete triage pipeline (including
history lookup and LLM call with fallback), and prints a structured JSON result.
Works offline via graceful degradation when Ollama is not running.
"""

from __future__ import annotations

import json

from mantis import triage_issue
from mantis.config import Config
from mantis.models import TriageResult


def main() -> None:
    """Run a self-contained triage demonstration."""
    print("Mantis Triage Example")
    print("=" * 40)

    config = Config()
    # Use a small, fast model for the example (fallback will be used if unavailable)
    config.model = "llama3.2"
    config.temperature = 0.0

    # Synthetic GitHub issue payload (compatible with Issue.model_validate)
    mock_issue: dict = {
        "title": "Crash when processing files larger than 2GB",
        "body": (
            "When uploading a file >2GB the application raises an unhandled "
            "OverflowError in the chunking logic.\n\n"
            "**Steps to reproduce:**\n"
            "1. Create a 3GB test file\n"
            "2. POST to /upload\n"
            "**Expected:** graceful rejection with 413 status\n"
            "**Actual:** 500 error and stack trace\n\n"
            "Regression introduced in #134."
        ),
        "number": 156,
        "html_url": "https://github.com/exampleorg/mantis/issues/156",
        "user": {"login": "bugreporter42"},
        "labels": [],
        "state": "open",
        # owner/repo are extracted automatically by the model validator
    }

    print(f"\nTriaging issue #{mock_issue['number']}: {mock_issue['title']}")
    print("(This will use fallback triage if Ollama is not running)\n")

    try:
        result: TriageResult = triage_issue(issue=mock_issue, config=config)

        print("Triage Result")
        print("-" * 20)
        print(json.dumps(result.model_dump(mode="json", exclude_none=True), indent=2))

        if "fallback" in result.reasoning.lower() or "unavailable" in result.reasoning.lower():
            print("\n→ Note: Used keyword-based fallback (Ollama not available).")
            print("  Start Ollama and run `ollama pull " + config.model + "` for full LLM triage.")

        print("\n→ In a real workflow you would apply these labels on GitHub.")

    except Exception as exc:  # pragma: no cover
        print(f"Unexpected error during triage: {exc}")


if __name__ == "__main__":
    main()
