<!-- header:start -->
<div align="center">

<img src="./assets/banner.svg" alt="Mantis" width="100%">

<a href="#-quick-start"><img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=20&pause=1000&color=5c4033&center=true&vCenter=true&width=640&lines=Local+AI+copilot+for+open-source+maintainers;Triage+%E2%80%A2+Review+%E2%80%A2+Respond+without+leaving+your+r;Private%2C+contextual%2C+and+instantly+useful" alt="Local AI copilot for open-source maintainers · Triage • Review • Respond without leaving your r · Private, contextual, and instantly useful"></a>

<a href="LICENSE"><img src="https://img.shields.io/github/license/ajendras/mantis?style=for-the-badge&color=f8f1e3" alt="License"></a>
<img src="https://img.shields.io/badge/Python-f8f1e3?style=for-the-badge&logo=python&logoColor=white" alt="Python">
<a href="https://github.com/ajendras/mantis/stargazers"><img src="https://img.shields.io/github/stars/ajendras/mantis?style=for-the-badge&logo=github&color=5c4033" alt="Stars"></a>
<a href="https://github.com/ajendras/mantis/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/ajendras/mantis/ci.yml?style=for-the-badge&label=CI" alt="CI"></a>
<img src="https://img.shields.io/github/last-commit/ajendras/mantis?style=for-the-badge&color=f8f1e3" alt="Last commit">
<a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-22c55e?style=for-the-badge" alt="PRs welcome"></a>

**Automates GitHub issue triage, PR reviews and maintainer tasks with local LLMs**

[✨ Features](#-features) • [⚡ Quick start](#-quick-start) • [🧰 Usage](#-usage) • [🧩 Architecture](#-architecture) • [📍 Roadmap](#-roadmap) • [🤝 Contributing](#-contributing)

</div>
<!-- header:end -->

## ✨ Why Mantis?

Open-source maintainers drown in issues, PRs and repetitive questions while burning out. Existing AI tools leak private repo data to the cloud and lack project-specific context. Mantis runs 100% locally, learns your conventions from the repo itself, and handles the busywork so humans can focus on architecture and community.

- Runs entirely with Ollama or any local OpenAI-compatible endpoint — nothing leaves your machine
- Learns tone, labels and priorities from your own issue and PR history
- Enforces every custom rule you define (style, security, process)
- Produces structured, copy-paste-ready output for GitHub while gracefully falling back when offline

## 🎬 Demo

<p align="center"><img src="./assets/demo.svg" alt="Mantis demo" width="760"></p>

## 🚀 Features

<table>
<tr>
<td>
🏷️ <b>Smart Triage</b><br>
Analyzes new issues and suggests accurate labels, priority, assignee and duplicates using project history
</td>
<td>
🔎 <b>Duplicate Detector</b><br>
Finds semantically similar past issues via targeted LLM prompts and conservative matching
</td>
<td>
📋 <b>PR Reviewer</b><br>
Generates contextual reviews with line-specific comments, verdicts and security flags
</td>
</tr>
<tr>
<td>
📅 <b>Weekly Digest</b><br>
Produces concise markdown reports of activity, decisions and suggested next steps
</td>
<td>
⚙️ <b>Rule Engine</b><br>
Injects and strictly respects custom project rules on every LLM call
</td>
<td>
💻 <b>Local-first</b><br>
Works offline with Ollama, LM Studio or any compatible endpoint; zero cloud leakage
</td>
</tr>
</table>

## 📦 Installation

Requires Python 3.9+ and a running Ollama instance with a model pulled (e.g. `ollama pull llama3`).

```bash
pip install mantis
mantis init
```

The `mantis` console script is automatically installed via the pyproject.toml entrypoint.

## ⚡ Quick start

```bash
mantis triage --repo ajendras/mantis --issue 42
```

Or via the Python API:

```python
from mantis import triage_issue, Config
from mantis.models import Issue

config = Config.load()
issue = {"title": "Segmentation fault on login", "body": "Crashes with SIGSEGV...", "number": 42}
result = triage_issue(issue, config=config)
print(result.labels, result.priority, result.duplicate_ids)
```

## 🧰 Usage

Run a full triage with model override:

```bash
mantis triage --repo ajendras/mantis --issue 123 --model llama3.1
```

Review a PR (fetches diff automatically):

```bash
mantis review --repo ajendras/mantis --pr 57
```

Generate a digest for the last 14 days:

```bash
mantis digest --repo ajendras/mantis --days 14
```

Initialize a new project with starter rules:

```bash
mantis init --rules "Never close issues without reproduction steps,Always label security issues as 'security'"
```

<details><summary>Library usage – full triage pipeline with mock data</summary>

```python
from mantis import triage_issue, Config
from mantis.models import Issue

config = Config(model="llama3", rules=["Use conventional commit labels"])
issue_dict = {
    "title": "Crash on startup with Python 3.12",
    "body": "Traceback shows... ",
    "number": 42,
    "html_url": "https://github.com/ajendras/mantis/issues/42"
}

result = triage_issue(issue_dict, config)
print(result.model_dump_json(indent=2))
```
</details>

<details><summary>Advanced: custom configuration and rule validation</summary>

```python
from pathlib import Path
from mantis import Config, generate_digest

config = Config.load(Path(".mantis/config.json"))
config.rules.append("All new features must include a test plan")
config.save()

report = generate_digest("ajendras/mantis", days=7, config=config)
print(report)
```
</details>

## 🔧 Configuration

| Option            | Default                  | Description |
|-------------------|--------------------------|-------------|
| model             | llama3                   | Ollama model name (or any OpenAI-compatible local endpoint) |
| temperature       | 0.3                      | Sampling temperature for the LLM (0.0–1.0) |
| github_token      | None                     | GitHub PAT for private repos or higher rate limits |
| ollama_base_url   | http://localhost:11434   | Base URL of the Ollama (or compatible) server |
| max_tokens        | 4096                     | Maximum tokens to request from the model |
| rules             | []                       | List of project-specific rules the LLM must follow on every run |

All options can be set via `MANTIS_*` environment variables, `.env`, or `.mantis/config.json`.

## 🧩 Architecture

```mermaid
flowchart TD
    CLI[cli.py] -->|commands| API[__init__.py]
    API -->|triage_issue| Analyzer[analyzer.py]
    API -->|review_pr| Reviewer[review.py]
    API -->|generate_digest| Prompts[prompts.py]
    Analyzer --> LLM[llm.py]
    Reviewer --> LLM
    Analyzer --> Duplicate[DuplicateDetector]
    Analyzer --> GitHub[github.py]
    Reviewer --> GitHub
    LLM --> Ollama[(Ollama)]
    GitHub --> GitHubAPI[GitHub REST API]
    Config[config.py] -->|rules + context| Analyzer
    Config -->|rules + context| Reviewer
    Config -->|rules + context| Prompts
    Models[models.py] -->|validation| Analyzer
    Models -->|validation| Reviewer
```

Mantis composes small, single-responsibility modules that the public API and CLI orchestrate. Every LLM call receives the same system context and project rules from `Config.get_system_context()`. `analyzer.py` and `review.py` handle domain logic while `llm.py` abstracts model access and JSON parsing with graceful offline fallbacks.

## 📁 Project structure

```text
src/mantis/
├── __init__.py          # Public API: triage_issue(), review_pr(), generate_digest(), Config
├── cli.py               # Typer CLI with commands: init, triage, review, digest, config
├── config.py            # Pydantic Settings, rule validation, system context
├── llm.py               # LLM wrapper with JSON mode, streaming and error handling
├── github.py            # GitHubClient with get_issue(), get_pr_diff(), list_recent_issues()
├── analyzer.py          # IssueAnalyzer + DuplicateDetector using TRIAGE_PROMPT
├── review.py            # PRReviewer using REVIEW_PROMPT and structured Review output
├── prompts.py           # Template constants and format_* functions
├── models.py            # Pydantic models: Issue, PR, TriageResult, Review, Comment
└── ...

tests/
├── conftest.py          # Fixtures: mock_llm, mock_github_client, sample_issue
├── test_analyzer.py     # Tests analyze(), duplicate detection, fallback triage
├── test_review.py       # Tests PRReviewer.review(), verdict logic and rule adherence
└── ...

examples/
└── triage_example.py    # Runnable example using mock issue and full pipeline
```

## 🧪 Testing

```bash
pytest -q
```

Tests cover `IssueAnalyzer.analyze()`, `DuplicateDetector.find_duplicates()`, `PRReviewer.review()`, rule injection, fallback behavior, model validation and CLI output paths using the `mock_llm` and `mock_github_client` fixtures.

## 📍 Roadmap

<!-- roadmap:start -->
- [x] **v0.1.0** — first release: Smart Triage, Duplicate Detector, PR Reviewer, Reply Assistant
- [ ] Add GitLab support alongside GitHub
- [ ] Interactive approval mode before posting comments
- [ ] Persist learned project conventions in a local vector store
- [ ] Support for additional local backends (llama.cpp, MLX)
- [ ] Few-shot examples pulled from repo's past maintainer comments
- [ ] Discord and Slack notification hooks for high-priority items
- [ ] Auto-generate release notes from merged PRs and linked issues
- [ ] Plugin system for custom Python hooks that run after LLM decisions
- [ ] Web UI dashboard showing pending triage queue and decision log
- [ ] Command to fine-tune a small model on a repo's historical decisions
- [ ] Integration with conventional commits for automatic changelog entries
- [ ] Scheduled weekly digest email option (local SMTP or sendgrid-free)

> 🤖 This roadmap is worked through continuously — ideas and PRs welcome!
<!-- roadmap:end -->

## 🤝 Contributing

Contributions are welcome and appreciated! Please read [CONTRIBUTING.md](https://github.com/ajendras/mantis/blob/main/CONTRIBUTING.md) and adhere to our [Code of Conduct](https://github.com/ajendras/mantis/blob/main/CODE_OF_CONDUCT.md). Good-first-issue PRs are tagged and make excellent places to start.

## 📄 License

MIT © Mantis Contributors — see [LICENSE](LICENSE).

<!-- footer:start -->
<div align="center">

### ⭐ Star history

<a href="https://star-history.com/#ajendras/mantis&Date"><img src="https://api.star-history.com/svg?repos=ajendras/mantis&type=Date" alt="Star history" width="600"></a>

If **Mantis** saves you time, a ⭐ helps others find it.

Made with ❤️ by [Ajendra](https://ajendra.info)

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:f8f1e3,100:5c4033&height=120&section=footer" width="100%" alt="">

</div>
<!-- footer:end -->
