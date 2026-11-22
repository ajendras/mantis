"""Command-line interface for Mantis.

Elegant Typer CLI with Rich output styled after an editorial magazine:
warm off-white tones, clear hierarchy, thin borders, muted ink colours
(#5c4033 brown, generous whitespace). All commands are production-ready
with helpful error messages and graceful degradation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from mantis import (
    __version__,
    generate_digest,
    review_pr,
    triage_issue,
)
from mantis.config import Config
from mantis.github import GitHubClient
from mantis.gitlab import GitLabClient
from mantis.models import Review, TriageResult

app = typer.Typer(
    name="mantis",
    help="Local-first GitHub and GitLab maintainer assistant powered by Ollama.",
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
    add_completion=True,
)

console = Console()


def _print_header(title: str) -> None:
    """Print an elegant header consistent with the editorial serif aesthetic."""
    console.print()
    header = Panel(
        Text(title, style="bold #5c4033", justify="left"),
        title="🪰 [bold]Mantis[/bold]",
        title_align="left",
        border_style="#5c4033",
        padding=(1, 3),
        subtitle=f"v{__version__} • local-first",
        subtitle_align="right",
    )
    console.print(header)
    console.print()


def _get_client(config: Config) -> GitHubClient | GitLabClient:
    """Return the appropriate VCS client based on configured platform."""
    token = config.github_token
    if config.platform == "gitlab":
        token = config.gitlab_token or config.github_token
    if config.platform == "github":
        return GitHubClient(token=token)
    return GitLabClient(token=token, base_url=config.gitlab_url)


@app.command()
def init(
    rules: str = typer.Option(
        "",
        "--rules",
        "-r",
        help="Comma-separated initial rules (quotes recommended)",
    ),
) -> None:
    """Initialize configuration and .mantis directory in the current repo."""
    config_dir = Path(".mantis")
    config_path = config_dir / "config.json"

    if config_path.exists():
        console.print("[yellow]Configuration file already exists.[/yellow]")
        if not typer.confirm("Overwrite existing configuration?", default=False):
            raise typer.Abort()

    config = Config()

    if rules.strip():
        rule_list = [r.strip() for r in rules.split(",") if r.strip()]
        if rule_list:
            config.rules = rule_list
            console.print(f"[green]Added {len(rule_list)} project rule(s).[/green]")

    try:
        saved = config.save(config_path)
        console.print(f"[green]✓[/green] Initialized Mantis at [bold]{saved}[/bold]")
    except Exception as exc:
        console.print(f"[red]Failed to save configuration: {exc}[/red]")
        raise typer.Exit(1) from exc

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  mantis config --show          # review settings")
    console.print("  mantis triage --repo owner/repo --issue 42")
    console.print("  ollama pull llama3            # if not already present")


@app.command()
def triage(
    repo: str = typer.Option(
        ..., "--repo", "-r", help="Repository in owner/repo format"
    ),
    issue: int = typer.Option(..., "--issue", "-i", help="Issue or PR number"),
    model: str | None = typer.Option(None, "--model", "-m", help="Override LLM model"),
    platform: str = typer.Option(
        "github", "--platform", help="Platform: github or gitlab"
    ),
) -> None:
    """Analyze an issue and suggest labels, priority, assignee and duplicates."""
    _print_header("Issue Triage")

    if "/" not in repo or len(repo.split("/")) != 2:
        console.print("[red]Error: --repo must be in owner/repo format[/red]")
        raise typer.Exit(1)

    if platform not in ("github", "gitlab"):
        console.print("[red]Error: --platform must be github or gitlab[/red]")
        raise typer.Exit(1)

    owner, repo_name = repo.split("/", 1)

    config = Config.load()
    if model:
        config.model = model
    if platform != "github":
        config.platform = platform

    client = _get_client(config)

    try:
        issue_data: dict[str, Any] = client.get_issue(owner, repo_name, issue)
    except Exception as exc:
        console.print(f"[red]Could not fetch issue #{issue}: {exc}[/red]")
        console.print("[dim]Is the repository correct and are you online?[/dim]")
        raise typer.Exit(1) from exc

    try:
        result: TriageResult = triage_issue(issue_data, config=config)
    except Exception as exc:
        console.print(f"[red]Triage failed: {exc}[/red]")
        raise typer.Exit(1) from exc

    # Editorial-style output
    issue_panel = Panel(
        f"[bold]{issue_data.get('title', 'Untitled')}[/bold]\n"
        f"[dim]#{issue} • opened by @{issue_data.get('user', {}).get('login', 'unknown')}[/dim]",
        title="Issue",
        border_style="#5c4033",
        padding=(1, 2),
    )
    console.print(issue_panel)

    # Metadata table
    meta = Table(show_header=False, box=None, padding=(0, 2))
    meta.add_row(
        "Labels",
        "  ".join(f"[bold cyan]#{lbl}[/]" for lbl in result.labels),
    )
    priority_color = (
        "red" if result.priority == "high" else "yellow" if result.priority == "medium" else "green"
    )
    meta.add_row("Priority", f"[{priority_color} bold]{result.priority.upper()}[/{priority_color} bold]")
    if result.assignee:
        meta.add_row("Assignee", f"[bold]@{result.assignee}[/bold]")
    console.print(meta)

    if result.duplicate_ids:
        web_base = "https://github.com" if config.platform == "github" else "https://gitlab.com"
        dups = "  ".join(f"[link={web_base}/{owner}/{repo_name}/issues/{d}]#{d}[/link]" for d in result.duplicate_ids)
        console.print(f"\n[yellow]Possible duplicates:[/yellow] {dups}")

    console.print("\n[bold #5c4033]Reasoning[/bold #5c4033]")
    console.print(result.reasoning.strip())

    console.print("\n[dim]Copy these labels into GitHub or GitLab or run with --model to experiment.[/dim]")


@app.command()
def review(
    repo: str = typer.Option(
        ..., "--repo", "-r", help="Repository in owner/repo format"
    ),
    pr: int = typer.Option(..., "--pr", "-p", help="Pull request / MR number"),
    model: str | None = typer.Option(None, "--model", "-m", help="Override LLM model"),
    platform: str = typer.Option(
        "github", "--platform", help="Platform: github or gitlab"
    ),
) -> None:
    """Review a pull request or merge request and generate line-specific comments."""
    _print_header("Pull Request / MR Review")

    if "/" not in repo or len(repo.split("/")) != 2:
        console.print("[red]Error: --repo must be in owner/repo format[/red]")
        raise typer.Exit(1)

    if platform not in ("github", "gitlab"):
        console.print("[red]Error: --platform must be github or gitlab[/red]")
        raise typer.Exit(1)

    owner, repo_name = repo.split("/", 1)

    config = Config.load()
    if model:
        config.model = model
    if platform != "github":
        config.platform = platform

    client = _get_client(config)

    try:
        pr_data: dict[str, Any] = client.get_merge_request(owner, repo_name, pr)
        diff_text = client.get_mr_diff(owner, repo_name, pr)
    except Exception as exc:
        console.print(f"[red]Could not fetch PR/MR #{pr}: {exc}[/red]")
        raise typer.Exit(1) from exc

    try:
        result: Review = review_pr(pr=pr_data, diff=diff_text, config=config)
    except Exception as exc:
        console.print(f"[red]Review failed: {exc}[/red]")
        raise typer.Exit(1) from exc

    verdict_style = {
        "approve": "green",
        "request_changes": "red",
        "comment": "yellow",
    }.get(result.verdict.lower(), "white")

    item_type = "PR" if config.platform == "github" else "MR"
    verdict_panel = Panel(
        f"[{verdict_style} bold]{result.verdict.upper()}[/{verdict_style} bold]",
        title=f"{item_type} #{pr} • {pr_data.get('title','Untitled')}",
        border_style="#5c4033",
        padding=(1, 2),
    )
    console.print(verdict_panel)

    console.print("\n[bold #5c4033]Summary[/bold #5c4033]")
    console.print(result.summary.strip())

    if result.security_flags:
        console.print("\n[bold red]Security Flags[/bold red]")
        for flag in result.security_flags:
            console.print(f"   • {flag}")

    if result.comments:
        console.print("\n[bold #5c4033]Comments[/bold #5c4033]")
        for comment in result.comments:
            severity_color = {
                "high": "red",
                "medium": "yellow",
                "low": "blue",
            }.get(getattr(comment, "severity", "medium"), "white")
            console.print(
                f"\n[dim]Line {comment.line}[/dim] [{severity_color}]{getattr(comment, 'severity', 'medium').upper()}[/{severity_color}]"
            )
            console.print(f"   {comment.content.strip()}")

    console.print("\n[dim]These comments can be posted directly to the PR/MR on GitHub or GitLab.[/dim]")


@app.command()
def digest(
    repo: str = typer.Option(
        ..., "--repo", "-r", help="Repository in owner/repo format"
    ),
    days: int = typer.Option(7, "--days", "-d", min=1, max=90, help="Days to summarize"),
    model: str | None = typer.Option(None, "--model", "-m", help="Override LLM model"),
    platform: str = typer.Option(
        "github", "--platform", help="Platform: github or gitlab"
    ),
) -> None:
    """Generate a concise markdown digest of recent repository activity."""
    _print_header(f"Digest — {repo} (last {days} days)")

    if "/" not in repo or len(repo.split("/")) != 2:
        console.print("[red]Error: --repo must be in owner/repo format[/red]")
        raise typer.Exit(1)

    if platform not in ("github", "gitlab"):
        console.print("[red]Error: --platform must be github or gitlab[/red]")
        raise typer.Exit(1)

    config = Config.load()
    if model:
        config.model = model
    if platform != "github":
        config.platform = platform

    try:
        report = generate_digest(repo=repo, days=days, config=config)
        console.print(
            Panel(
                report,
                title="Weekly Digest",
                border_style="#5c4033",
                padding=(2, 3),
                expand=False,
            )
        )
    except Exception as exc:
        console.print(f"[red]Digest generation failed: {exc}[/red]")
        raise typer.Exit(1) from exc


@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="Display full configuration as JSON"),
    model: str = typer.Option("", "--model", help="Update default model name"),
    add_rule: str = typer.Option("", "--add-rule", help="Add a new project rule"),
    platform: str = typer.Option("", "--platform", help="Set platform (github|gitlab)"),
) -> None:
    """View or update Mantis configuration."""
    config = Config.load()

    updated = False
    if model:
        config.model = model
        updated = True
        console.print(f"[green]✓[/green] Default model set to [bold]{model}[/bold]")

    if platform and platform in ("github", "gitlab"):
        config.platform = platform
        updated = True
        console.print(f"[green]✓[/green] Platform set to [bold]{platform}[/bold]")

    if add_rule:
        if add_rule.strip() not in config.rules:
            config.rules.append(add_rule.strip())
            updated = True
            console.print(f"[green]✓[/green] Added rule: [italic]\"{add_rule}\"[/italic]")

    if updated:
        config.save()
        console.print("[dim]Configuration persisted to .mantis/config.json[/dim]")

    if show or not (model or add_rule or platform):
        cfg_dict = config.model_dump(
            mode="json",
            exclude={"repo_path"},
            exclude_unset=True,
        )
        console.print(
            Panel(
                json.dumps(cfg_dict, indent=2),
                title="Mantis Configuration",
                border_style="#5c4033",
                padding=(1, 2),
            )
        )
        console.print("\n[dim]Override with MANTIS_* environment variables or edit .mantis/config.json[/dim]")


if __name__ == "__main__":
    app()
