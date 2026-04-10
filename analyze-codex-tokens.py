#!/usr/bin/env python3
"""
Codex token usage analyzer.

Analyzes Codex JSONL session logs from:
- ~/.codex/sessions
- ~/.codex/archived_sessions

It groups sessions by project, reports token usage, and extracts user prompts.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
SESSION_DIRS = [
    CODEX_HOME / "sessions",
    CODEX_HOME / "archived_sessions",
]
OUTPUT_DIR = Path(
    os.environ.get("OUTPUT_DIR", str(CODEX_HOME / "analysis" / "tokens"))
).expanduser()

# Filter: only include sessions that started within the last N days (None = all time)
SINCE_DAYS = int(os.environ.get("SINCE_DAYS", "0")) or None
SINCE_DATE = os.environ.get("SINCE_DATE")  # e.g. "2026-03-30"


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_cutoff() -> datetime | None:
    """Return a UTC-aware datetime cutoff, or None for all time."""
    if SINCE_DATE:
        return datetime.fromisoformat(SINCE_DATE).replace(tzinfo=timezone.utc)
    if SINCE_DAYS:
        return datetime.now(timezone.utc) - timedelta(days=SINCE_DAYS)
    return None


def format_tokens(value: int) -> str:
    return f"{value:,}"


def format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 999:
        return f"{value:,.0f}x"
    return f"{value:.1f}x"


def format_percent(value: float) -> str:
    return f"{value:.1f}%"


def iter_session_files() -> list[Path]:
    files: list[Path] = []
    for directory in SESSION_DIRS:
        if directory.is_dir():
            files.extend(sorted(directory.rglob("*.jsonl")))
    return files


def derive_project_name(meta: dict[str, Any]) -> str:
    git_info = meta.get("git") or {}
    repository_url = git_info.get("repository_url")
    if isinstance(repository_url, str) and repository_url:
        parsed = urlparse(repository_url)
        name = Path(parsed.path).name
        if name.endswith(".git"):
            name = name[:-4]
        if name:
            return name

    cwd = meta.get("cwd")
    if isinstance(cwd, str) and cwd:
        path = Path(cwd)
        if path.name:
            return path.name

    return "unknown"


def normalize_source(source: Any) -> str:
    if isinstance(source, str) and source:
        return source
    if isinstance(source, dict) and "subagent" in source:
        return "subagent"
    if source is None:
        return "unknown"
    return str(source)


def classify_workspace(cwd: str | None) -> str:
    if not cwd:
        return "unknown"
    normalized = cwd.rstrip("/")
    worktree_marker = f"{CODEX_HOME}/worktrees/"
    if normalized.startswith(worktree_marker):
        return "codex worktree"
    return "repo root/other"


def is_subagent_session(meta: dict[str, Any]) -> bool:
    source = meta.get("source")
    return isinstance(source, dict) and "subagent" in source


def get_parent_session_id(meta: dict[str, Any]) -> str | None:
    if meta.get("forked_from_id"):
        return meta["forked_from_id"]

    source = meta.get("source")
    if isinstance(source, dict):
        parent_id = (
            source.get("subagent", {})
            .get("thread_spawn", {})
            .get("parent_thread_id")
        )
        if isinstance(parent_id, str) and parent_id:
            return parent_id

    return None


def get_subagent_label(meta: dict[str, Any]) -> str:
    task_name = meta.get("agent_path")
    if isinstance(task_name, str) and task_name:
        return task_name
    nickname = meta.get("agent_nickname")
    if isinstance(nickname, str) and nickname:
        return nickname
    role = meta.get("agent_role")
    if isinstance(role, str) and role:
        return role
    return "subagent"


def session_in_range(session: dict[str, Any], cutoff: datetime | None) -> bool:
    if not cutoff:
        return True
    ts = parse_iso_datetime(session.get("timestamp_start"))
    return ts is None or ts >= cutoff


def estimate_instruction_tokens(char_count: int) -> int:
    # Rough heuristic for Latin text. Reported as an estimate only.
    return round(char_count / 4)


def get_first_prompt_text(session: dict[str, Any], limit: int = 160) -> str:
    if not session["prompts"]:
        return ""
    return session["prompts"][0]["text"][:limit].replace("\n", " ")


def compute_input_output_ratio(session: dict[str, Any]) -> float | None:
    output_tokens = session["usage"].get("output_tokens", 0)
    if output_tokens <= 0:
        return None
    return session["usage"].get("input_tokens", 0) / output_tokens


def compute_cached_output_ratio(session: dict[str, Any]) -> float | None:
    output_tokens = session["usage"].get("output_tokens", 0)
    if output_tokens <= 0:
        return None
    return session["usage"].get("cached_input_tokens", 0) / output_tokens


def parse_session(jsonl_path: Path) -> dict[str, Any] | None:
    try:
        lines = jsonl_path.read_text().splitlines()
    except Exception:
        return None

    if not lines:
        return None

    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError:
        return None

    if first.get("type") != "session_meta":
        return None

    meta = first.get("payload", {})
    base_instruction_text = (
        (meta.get("base_instructions") or {}).get("text")
        if isinstance(meta.get("base_instructions"), dict)
        else ""
    )
    base_instruction_chars = (
        len(base_instruction_text) if isinstance(base_instruction_text, str) else 0
    )
    usage_total = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }
    prompts: list[dict[str, Any]] = []
    final_message = None
    max_user_instruction_chars = 0
    turn_count = 0

    for line in lines[1:]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        obj_type = obj.get("type")

        if obj_type == "turn_context":
            turn_count += 1
            payload = obj.get("payload", {})
            user_instructions = payload.get("user_instructions")
            if isinstance(user_instructions, str):
                max_user_instruction_chars = max(
                    max_user_instruction_chars, len(user_instructions)
                )
            continue

        if obj_type != "event_msg":
            continue

        payload = obj.get("payload", {})
        payload_type = payload.get("type")

        if payload_type == "token_count":
            info = payload.get("info") or {}
            totals = info.get("total_token_usage") or {}
            if totals:
                usage_total = {
                    "input_tokens": int(totals.get("input_tokens", 0)),
                    "cached_input_tokens": int(totals.get("cached_input_tokens", 0)),
                    "output_tokens": int(totals.get("output_tokens", 0)),
                    "reasoning_output_tokens": int(
                        totals.get("reasoning_output_tokens", 0)
                    ),
                    "total_tokens": int(totals.get("total_tokens", 0)),
                }

        elif payload_type == "user_message":
            text = payload.get("message", "")
            if text:
                prompts.append(
                    {
                        "text": text,
                        "timestamp": obj.get("timestamp"),
                    }
                )

        elif payload_type == "task_complete":
            final_message = payload.get("last_agent_message")

    instruction_chars = base_instruction_chars + max_user_instruction_chars

    return {
        "file": str(jsonl_path),
        "project": derive_project_name(meta),
        "session_id": meta.get("id") or jsonl_path.stem,
        "parent_session_id": get_parent_session_id(meta),
        "is_subagent": is_subagent_session(meta),
        "subagent_label": get_subagent_label(meta) if is_subagent_session(meta) else None,
        "agent_role": meta.get("agent_role"),
        "originator": meta.get("originator"),
        "source": meta.get("source"),
        "source_kind": normalize_source(meta.get("source")),
        "cwd": meta.get("cwd"),
        "workspace_kind": classify_workspace(meta.get("cwd")),
        "timestamp_start": meta.get("timestamp") or first.get("timestamp"),
        "usage": usage_total,
        "total_tokens": usage_total["total_tokens"],
        "input_output_ratio": compute_input_output_ratio({"usage": usage_total, "prompts": prompts}),
        "cached_output_ratio": compute_cached_output_ratio({"usage": usage_total, "prompts": prompts}),
        "prompt_count": len(prompts),
        "turn_count": turn_count,
        "base_instruction_chars": base_instruction_chars,
        "max_user_instruction_chars": max_user_instruction_chars,
        "instruction_chars": instruction_chars,
        "instruction_token_estimate": estimate_instruction_tokens(instruction_chars),
        "prompts": prompts,
        "final_message": final_message,
    }


def analyze_all() -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
]:
    """Analyze all Codex sessions."""
    projects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sessions_by_id: dict[str, dict[str, Any]] = {}
    cutoff = get_cutoff()

    for jsonl_file in iter_session_files():
        session = parse_session(jsonl_file)
        if not session:
            continue
        if session["total_tokens"] <= 0:
            continue
        if not session_in_range(session, cutoff):
            continue
        projects[session["project"]].append(session)
        sessions_by_id[session["session_id"]] = session

    children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sessions in projects.values():
        for session in sessions:
            parent_id = session.get("parent_session_id")
            if parent_id:
                children_by_parent[parent_id].append(session)

    return projects, children_by_parent, sessions_by_id


def summarize_projects(
    projects: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    summaries = []
    for project_name, sessions in projects.items():
        total = defaultdict(int)
        subagent_tokens = 0
        subagent_count = 0

        for session in sessions:
            for key, value in session["usage"].items():
                total[key] += value
            if session["is_subagent"]:
                subagent_tokens += session["total_tokens"]
                subagent_count += 1

        summaries.append(
            {
                "project": project_name,
                "sessions": len(sessions),
                "usage": dict(total),
                "total_tokens": total["total_tokens"],
                "subagent_tokens": subagent_tokens,
                "subagent_count": subagent_count,
            }
        )

    summaries.sort(key=lambda item: item["total_tokens"], reverse=True)
    return summaries


def find_costly_sessions(
    projects: dict[str, list[dict[str, Any]]], top_n: int = 20
) -> list[tuple[str, dict[str, Any]]]:
    all_sessions = []
    for project_name, sessions in projects.items():
        for session in sessions:
            if not session["is_subagent"]:
                all_sessions.append((project_name, session))

    all_sessions.sort(key=lambda item: item[1]["total_tokens"], reverse=True)
    return all_sessions[:top_n]


def find_costly_subagents(
    projects: dict[str, list[dict[str, Any]]], top_n: int = 20
) -> list[tuple[str, dict[str, Any]]]:
    all_subagents = []
    for project_name, sessions in projects.items():
        for session in sessions:
            if session["is_subagent"]:
                all_subagents.append((project_name, session))

    all_subagents.sort(key=lambda item: item[1]["total_tokens"], reverse=True)
    return all_subagents[:top_n]


def flatten_sessions(projects: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    all_sessions = []
    for sessions in projects.values():
        all_sessions.extend(sessions)
    return all_sessions


def compute_descendant_subagent_stats(
    session_id: str, children_by_parent: dict[str, list[dict[str, Any]]]
) -> tuple[int, int]:
    total_tokens = 0
    total_count = 0
    stack = list(children_by_parent.get(session_id, []))

    while stack:
        child = stack.pop()
        if child["is_subagent"]:
            total_count += 1
            total_tokens += child["total_tokens"]
        stack.extend(children_by_parent.get(child["session_id"], []))

    return total_count, total_tokens


def build_group_breakdown(
    sessions: list[dict[str, Any]], key_name: str
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, int]] = defaultdict(
        lambda: {"sessions": 0, "total_tokens": 0, "subagent_sessions": 0}
    )

    for session in sessions:
        key = session.get(key_name) or "unknown"
        grouped[key]["sessions"] += 1
        grouped[key]["total_tokens"] += session["total_tokens"]
        if session["is_subagent"]:
            grouped[key]["subagent_sessions"] += 1

    rows = []
    for key, values in grouped.items():
        rows.append({"name": key, **values})

    rows.sort(key=lambda row: row["total_tokens"], reverse=True)
    return rows


def find_input_output_ratio_outliers(
    projects: dict[str, list[dict[str, Any]]], top_n: int = 15
) -> list[tuple[str, dict[str, Any]]]:
    candidates = []
    for project_name, sessions in projects.items():
        for session in sessions:
            if session["is_subagent"]:
                continue
            if session["usage"].get("output_tokens", 0) <= 0:
                continue
            if session["total_tokens"] < 1_000_000:
                continue
            ratio = session.get("input_output_ratio")
            if ratio is not None:
                candidates.append((project_name, session))

    candidates.sort(
        key=lambda item: (
            item[1]["input_output_ratio"],
            item[1]["total_tokens"],
        ),
        reverse=True,
    )
    return candidates[:top_n]


def find_instruction_heavy_sessions(
    projects: dict[str, list[dict[str, Any]]], top_n: int = 15
) -> list[tuple[str, dict[str, Any]]]:
    candidates = []
    for project_name, sessions in projects.items():
        for session in sessions:
            if session["is_subagent"]:
                continue
            if session["instruction_chars"] <= 0:
                continue
            candidates.append((project_name, session))

    candidates.sort(
        key=lambda item: (
            item[1]["instruction_chars"],
            item[1]["total_tokens"],
        ),
        reverse=True,
    )
    return candidates[:top_n]


def find_subagent_overhead_outliers(
    projects: dict[str, list[dict[str, Any]]],
    children_by_parent: dict[str, list[dict[str, Any]]],
    top_n: int = 15,
) -> list[tuple[str, dict[str, Any], int, int]]:
    candidates = []
    for project_name, sessions in projects.items():
        for session in sessions:
            if session["is_subagent"]:
                continue
            descendant_count, descendant_tokens = compute_descendant_subagent_stats(
                session["session_id"], children_by_parent
            )
            if descendant_count <= 0:
                continue
            candidates.append((project_name, session, descendant_count, descendant_tokens))

    candidates.sort(key=lambda item: item[3], reverse=True)
    return candidates[:top_n]


def write_report(
    projects: dict[str, list[dict[str, Any]]],
    summaries: list[dict[str, Any]],
    children_by_parent: dict[str, list[dict[str, Any]]],
    sessions_by_id: dict[str, dict[str, Any]],
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / "token_report.md"

    cutoff = get_cutoff()
    date_range = f"Since {cutoff.strftime('%Y-%m-%d')}" if cutoff else "All time"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    grand_input = sum(s["usage"].get("input_tokens", 0) for s in summaries)
    grand_cached = sum(s["usage"].get("cached_input_tokens", 0) for s in summaries)
    grand_output = sum(s["usage"].get("output_tokens", 0) for s in summaries)
    grand_reasoning = sum(s["usage"].get("reasoning_output_tokens", 0) for s in summaries)
    grand_total = sum(s["total_tokens"] for s in summaries)
    total_sessions = sum(s["sessions"] for s in summaries)
    total_subagent_tokens = sum(s["subagent_tokens"] for s in summaries)
    total_subagent_count = sum(s["subagent_count"] for s in summaries)
    all_sessions = flatten_sessions(projects)
    originator_rows = build_group_breakdown(all_sessions, "originator")
    role_rows = build_group_breakdown(all_sessions, "agent_role")
    workspace_rows = build_group_breakdown(all_sessions, "workspace_kind")

    lines = [
        "# Codex Token Usage Analysis",
        "",
        f"Generated: {now} | Range: {date_range}",
        "",
        "## Grand Totals",
        "",
        f"- **Projects**: {len(summaries)}",
        f"- **Sessions**: {total_sessions:,}",
        f"- **Total tokens**: {format_tokens(grand_total)}",
        f"  - Input: {format_tokens(grand_input)}",
        f"  - Cached input: {format_tokens(grand_cached)}",
        f"  - Output: {format_tokens(grand_output)}",
        f"  - Reasoning output: {format_tokens(grand_reasoning)}",
        f"- **Subagent sessions**: {total_subagent_count:,} ({format_tokens(total_subagent_tokens)} tokens)",
        "",
        "## By Project",
        "",
        "| Project | Sessions | Total | Input | Cached Input | Output | Reasoning | Subagents |",
        "|---------|----------|-------|-------|--------------|--------|-----------|-----------|",
    ]

    for summary in summaries:
        usage = summary["usage"]
        lines.append(
            f"| {summary['project']} | {summary['sessions']} "
            f"| {format_tokens(summary['total_tokens'])} "
            f"| {format_tokens(usage.get('input_tokens', 0))} "
            f"| {format_tokens(usage.get('cached_input_tokens', 0))} "
            f"| {format_tokens(usage.get('output_tokens', 0))} "
            f"| {format_tokens(usage.get('reasoning_output_tokens', 0))} "
            f"| {summary['subagent_count']} ({format_tokens(summary['subagent_tokens'])}) |"
        )

    lines.extend(["", "## Most Costly Sessions", ""])

    for index, (project_name, session) in enumerate(find_costly_sessions(projects, top_n=25), 1):
        lines.append(
            f"### {index}. {project_name} — {format_tokens(session['total_tokens'])} tokens"
        )
        lines.append(f"- **Session**: `{session['session_id']}`")
        if session.get("timestamp_start"):
            lines.append(
                f"- **Started**: {session['timestamp_start'][:19].replace('T', ' ')}"
            )
        if session.get("cwd"):
            lines.append(f"- **CWD**: `{session['cwd']}`")
        child_count = len(children_by_parent.get(session["session_id"], []))
        lines.append(f"- **Direct subagents**: {child_count}")

        usage = session["usage"]
        lines.append(
            f"- **Tokens**: input={format_tokens(usage.get('input_tokens', 0))}, "
            f"cached_input={format_tokens(usage.get('cached_input_tokens', 0))}, "
            f"output={format_tokens(usage.get('output_tokens', 0))}, "
            f"reasoning={format_tokens(usage.get('reasoning_output_tokens', 0))}"
        )

        if session["prompts"]:
            first_prompt = session["prompts"][0]["text"][:400].replace("\n", " ")
            lines.append("- **First prompt**:")
            lines.append(f"  > {first_prompt}")
        lines.append("")

    lines.extend(
        [
            "## Highest Input/Output Ratios",
            "",
            "| # | Project | Session | Input/Output | Cached/Output | Total Tokens | First Prompt |",
            "|---|---------|---------|--------------|---------------|--------------|--------------|",
        ]
    )

    for index, (project_name, session) in enumerate(
        find_input_output_ratio_outliers(projects), 1
    ):
        lines.append(
            f"| {index} | {project_name} | `{session['session_id'][:8]}...` "
            f"| {format_ratio(session.get('input_output_ratio'))} "
            f"| {format_ratio(session.get('cached_output_ratio'))} "
            f"| {format_tokens(session['total_tokens'])} "
            f"| {get_first_prompt_text(session, limit=90)} |"
        )

    lines.extend(
        [
            "",
            "## Subagent Overhead Hotspots",
            "",
            "| # | Project | Parent Session | Descendant Subagents | Descendant Tokens | Overhead vs Parent | Parent Tokens | First Prompt |",
            "|---|---------|----------------|---------------------|-------------------|------------------|---------------|--------------|",
        ]
    )

    for index, (project_name, session, descendant_count, descendant_tokens) in enumerate(
        find_subagent_overhead_outliers(projects, children_by_parent), 1
    ):
        overhead_ratio = descendant_tokens / max(session["total_tokens"], 1)
        lines.append(
            f"| {index} | {project_name} | `{session['session_id'][:8]}...` "
            f"| {descendant_count} "
            f"| {format_tokens(descendant_tokens)} "
            f"| {format_percent(overhead_ratio * 100)} "
            f"| {format_tokens(session['total_tokens'])} "
            f"| {get_first_prompt_text(session, limit=90)} |"
        )

    lines.extend(
        [
            "## Most Costly Subagents",
            "",
            "| # | Project | Parent Session | Subagent | Role | Total Tokens | Input | Cached Input | Output |",
            "|---|---------|----------------|----------|------|--------------|-------|--------------|--------|",
        ]
    )

    for index, (project_name, session) in enumerate(find_costly_subagents(projects, top_n=20), 1):
        usage = session["usage"]
        lines.append(
            f"| {index} | {project_name} | `{(session.get('parent_session_id') or '?')[:8]}...` "
            f"| `{session.get('subagent_label') or '?'}` "
            f"| `{session.get('agent_role') or '?'}` "
            f"| {format_tokens(session['total_tokens'])} "
            f"| {format_tokens(usage.get('input_tokens', 0))} "
            f"| {format_tokens(usage.get('cached_input_tokens', 0))} "
            f"| {format_tokens(usage.get('output_tokens', 0))} |"
        )

    lines.extend(["", "## Subagent Usage By Project", ""])
    lines.append("| Project | Subagent Sessions | Subagent Tokens |")
    lines.append("|---------|-------------------|-----------------|")

    project_subagent_stats = []
    for project_name, sessions in projects.items():
        subagent_count = sum(1 for session in sessions if session["is_subagent"])
        subagent_tokens = sum(
            session["total_tokens"] for session in sessions if session["is_subagent"]
        )
        if subagent_count:
            project_subagent_stats.append((project_name, subagent_count, subagent_tokens))

    project_subagent_stats.sort(key=lambda item: item[2], reverse=True)
    for project_name, count, tokens in project_subagent_stats:
        lines.append(f"| {project_name} | {count} | {format_tokens(tokens)} |")

    lines.extend(
        [
            "",
            "## Usage By Originator",
            "",
            "| Originator | Sessions | Total Tokens | Subagent Sessions |",
            "|------------|----------|--------------|-------------------|",
        ]
    )

    for row in originator_rows:
        lines.append(
            f"| {row['name']} | {row['sessions']} | {format_tokens(row['total_tokens'])} | {row['subagent_sessions']} |"
        )

    lines.extend(
        [
            "",
            "## Usage By Agent Role",
            "",
            "| Agent Role | Sessions | Total Tokens | Subagent Sessions |",
            "|------------|----------|--------------|-------------------|",
        ]
    )

    for row in role_rows:
        lines.append(
            f"| {row['name']} | {row['sessions']} | {format_tokens(row['total_tokens'])} | {row['subagent_sessions']} |"
        )

    lines.extend(
        [
            "",
            "## Usage By Workspace Kind",
            "",
            "| Workspace Kind | Sessions | Total Tokens | Subagent Sessions |",
            "|----------------|----------|--------------|-------------------|",
        ]
    )

    for row in workspace_rows:
        lines.append(
            f"| {row['name']} | {row['sessions']} | {format_tokens(row['total_tokens'])} | {row['subagent_sessions']} |"
        )

    lines.extend(
        [
            "",
            "## Most Instruction-Heavy Sessions",
            "",
            "| # | Project | Session | Base Instr Chars | Max Turn Instr Chars | Combined Chars | Est. Tokens | First Prompt |",
            "|---|---------|---------|------------------|----------------------|----------------|-------------|--------------|",
        ]
    )

    for index, (project_name, session) in enumerate(
        find_instruction_heavy_sessions(projects), 1
    ):
        lines.append(
            f"| {index} | {project_name} | `{session['session_id'][:8]}...` "
            f"| {format_tokens(session['base_instruction_chars'])} "
            f"| {format_tokens(session['max_user_instruction_chars'])} "
            f"| {format_tokens(session['instruction_chars'])} "
            f"| ~{format_tokens(session['instruction_token_estimate'])} "
            f"| {get_first_prompt_text(session, limit=90)} |"
        )

    lines.extend(["", "## Likely Savings Opportunities", ""])

    top_non_subagent_sessions = find_costly_sessions(projects, top_n=5)
    top_non_subagent_total = sum(session["total_tokens"] for _, session in top_non_subagent_sessions)
    top_non_subagent_share = top_non_subagent_total / max(grand_total, 1)

    if total_subagent_tokens > 0:
        share = total_subagent_tokens / max(grand_total, 1)
        lines.append(
            f"- Subagent usage is a major cost center: {format_tokens(total_subagent_tokens)} of {format_tokens(grand_total)} total tokens ({format_percent(share * 100)}) are in subagent sessions."
        )

    if grand_output > 0:
        cached_output_ratio = grand_cached / grand_output
        input_output_ratio = grand_input / grand_output
        lines.append(
            f"- Context replay dominates output: input/output is {format_ratio(input_output_ratio)} and cached-input/output is {format_ratio(cached_output_ratio)} across the whole report window."
        )

    if top_non_subagent_sessions:
        lines.append(
            f"- A small number of sessions dominate spend: the top 5 non-subagent sessions account for {format_tokens(top_non_subagent_total)} tokens ({format_percent(top_non_subagent_share * 100)} of total usage)."
        )

    hottest_overhead = find_subagent_overhead_outliers(projects, children_by_parent, top_n=1)
    if hottest_overhead:
        project_name, parent_session, descendant_count, descendant_tokens = hottest_overhead[0]
        overhead_ratio = descendant_tokens / max(parent_session["total_tokens"], 1)
        lines.append(
            f"- The largest subagent hotspot is `{parent_session['session_id']}` in {project_name}: {descendant_count} descendant subagents consumed {format_tokens(descendant_tokens)} tokens, equal to {format_percent(overhead_ratio * 100)} of the parent session's own token count."
        )

    heaviest_instruction_sessions = find_instruction_heavy_sessions(projects, top_n=1)
    if heaviest_instruction_sessions:
        project_name, session = heaviest_instruction_sessions[0]
        lines.append(
            f"- The heaviest static instruction payload observed was in `{session['session_id']}` ({project_name}) at {format_tokens(session['instruction_chars'])} characters, or about ~{format_tokens(session['instruction_token_estimate'])} tokens before any repo/file context was added."
        )

    report_path.write_text("\n".join(lines) + "\n")
    print(f"Report written: {report_path}")
    return report_path


def write_prompts_by_project(projects: dict[str, list[dict[str, Any]]]) -> None:
    prompts_dir = OUTPUT_DIR / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    for project_name, sessions in projects.items():
        all_prompts = []
        for session in sessions:
            if session["is_subagent"]:
                continue
            for prompt in session["prompts"]:
                all_prompts.append(
                    {
                        "session_id": session["session_id"],
                        "timestamp": prompt.get("timestamp", ""),
                        "text": prompt["text"],
                    }
                )

        if not all_prompts:
            continue

        all_prompts.sort(key=lambda item: item["timestamp"] or "")
        safe_name = project_name.replace("/", "_").replace(" ", "_")[:80]
        out_path = prompts_dir / f"{safe_name}.md"

        lines = [
            f"# Prompts: {project_name}",
            "",
            f"{len(all_prompts)} prompts across {len(sessions)} sessions",
            "",
        ]

        for index, prompt in enumerate(all_prompts, 1):
            timestamp = prompt["timestamp"][:19].replace("T", " ") if prompt["timestamp"] else "unknown"
            lines.append(f"## {index}. [{timestamp}] Session `{prompt['session_id'][:8]}`")
            lines.append("")
            lines.append(prompt["text"])
            lines.append("")

        out_path.write_text("\n".join(lines))

    print(f"Prompt files written to: {prompts_dir}")


def print_summary(
    summaries: list[dict[str, Any]], projects: dict[str, list[dict[str, Any]]]
) -> None:
    grand_total = sum(summary["total_tokens"] for summary in summaries)
    total_sessions = sum(summary["sessions"] for summary in summaries)

    print(
        f"\nTotal: {format_tokens(grand_total)} tokens across {total_sessions} sessions "
        f"in {len(summaries)} projects\n"
    )
    print(f"{'Project':<32} {'Sessions':>8} {'Total Tokens':>14} {'Subagents':>10}")
    print("-" * 70)

    for summary in summaries[:30]:
        print(
            f"{summary['project']:<32} {summary['sessions']:>8,} "
            f"{format_tokens(summary['total_tokens']):>14} {summary['subagent_count']:>10,}"
        )

    print("\nTop 10 costliest sessions:")
    for project_name, session in find_costly_sessions(projects, top_n=10):
        started = session["timestamp_start"][:10] if session["timestamp_start"] else "?"
        first_prompt = ""
        if session["prompts"]:
            first_prompt = session["prompts"][0]["text"][:80].replace("\n", " ")
        print(
            f"  [{started}] {project_name}: {format_tokens(session['total_tokens'])} "
            f"— {first_prompt}"
        )


def main() -> int:
    print("Scanning Codex sessions...")
    projects, children_by_parent, sessions_by_id = analyze_all()
    summaries = summarize_projects(projects)

    print(f"Found {len(projects)} projects")
    print_summary(summaries, projects)

    report_path = write_report(projects, summaries, children_by_parent, sessions_by_id)
    write_prompts_by_project(projects)

    print(f"\nFull report: {report_path}")
    print(f"Prompts: {OUTPUT_DIR / 'prompts'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
