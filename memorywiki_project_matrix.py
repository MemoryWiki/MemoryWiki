from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_index_maintain import maintain_indexes
from memorywiki_cross_project_install import install_cross_project_memory
from memorywiki_mcp_doctor import run_doctor
from retrieval_golden_eval import RetrievalCase, run_golden_eval

DEFAULT_PROJECTS: list[dict[str, Any]] = []


@dataclass
class ProjectTarget:
    name: str
    path: Path
    cases: list[dict[str, Any]] = field(default_factory=list)
    required_cases_min: int = 1
    required_cases_max: int = 3


def _case_from_dict(payload: dict[str, Any]) -> RetrievalCase:
    expected = payload.get("expected", [])
    if isinstance(expected, str):
        expected = [expected]
    return RetrievalCase(
        name=str(payload.get("name") or payload.get("query") or "case"),
        query=str(payload["query"]),
        expected=[str(item) for item in expected],
        expected_scope=str(payload.get("expected_scope", "")),
        expected_source=str(payload.get("expected_source", "")),
        tags=[str(item) for item in payload.get("tags", [])]
        if isinstance(payload.get("tags", []), list)
        else [],
        required=bool(payload.get("required", True)),
        min_rank=int(payload["min_rank"]) if payload.get("min_rank") is not None else None,
        severity=str(payload.get("severity", "core")),
        owner=str(payload.get("owner", "")),
        project=str(payload.get("project", "")),
    )


def _target_from_dict(payload: dict[str, Any]) -> ProjectTarget:
    return ProjectTarget(
        name=str(payload.get("name") or Path(str(payload["path"])).name),
        path=Path(str(payload["path"])).expanduser(),
        cases=list(payload.get("cases", [])),
        required_cases_min=int(payload.get("required_cases_min", 1)),
        required_cases_max=int(payload.get("required_cases_max", 3)),
    )


def _case_coverage(target: ProjectTarget) -> dict[str, Any]:
    case_count = len(target.cases)
    if case_count < target.required_cases_min:
        return {
            "status": "warn",
            "case_count": case_count,
            "required_cases_min": target.required_cases_min,
            "required_cases_max": target.required_cases_max,
            "message": f"project has {case_count} golden cases, below minimum {target.required_cases_min}",
        }
    if target.required_cases_max > 0 and case_count > target.required_cases_max:
        return {
            "status": "warn",
            "case_count": case_count,
            "required_cases_min": target.required_cases_min,
            "required_cases_max": target.required_cases_max,
            "message": f"project has {case_count} golden cases, above maximum {target.required_cases_max}",
        }
    return {
        "status": "ok",
        "case_count": case_count,
        "required_cases_min": target.required_cases_min,
        "required_cases_max": target.required_cases_max,
        "message": "project golden case coverage is within target",
    }


def load_project_targets(path: str | Path | None = None) -> list[ProjectTarget]:
    if not path:
        return [_target_from_dict(item) for item in DEFAULT_PROJECTS]
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Project matrix config must be a JSON list")
    return [_target_from_dict(item) for item in payload]


def _status_from_row(row: dict[str, Any]) -> str:
    if row.get("error"):
        return "fail"
    statuses = [
        row.get("doctor", {}).get("status"),
        row.get("golden_eval", {}).get("status"),
    ]
    if row.get("mcp_smoke"):
        statuses.append(row["mcp_smoke"].get("status"))
    statuses.append(row.get("case_coverage", {}).get("status"))
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _overall(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "ok"
    statuses = {_status_from_row(row) for row in rows}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _run_project_smoke(
    *,
    python: str | Path,
    memory_home: Path,
    project_root: Path,
    global_root: Path,
    query: str,
) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(memory_home)
    completed = subprocess.run(
        [
            str(python),
            "-m",
            "memorywiki_mcp.smoke_client",
            "--python",
            str(python),
            "--repo-root",
            str(memory_home.parent),
            "--project-root",
            str(project_root),
            "--global-root",
            str(global_root),
            "--query",
            query,
        ],
        cwd=memory_home.parent,
        env=env,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        return {
            "status": "fail",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        }
    return {
        "status": "ok",
        "returncode": 0,
        "payload": json.loads(completed.stdout or "{}"),
    }


def run_project_matrix(
    *,
    projects: list[ProjectTarget],
    memory_system_home: str | Path,
    python: str | Path,
    global_root: str | Path,
    install: bool = False,
    update_existing_agents: bool = False,
    write_indexes: bool = False,
    smoke: bool = False,
    min_pass_rate: float = 0.75,
) -> dict[str, Any]:
    memory_home = Path(memory_system_home).expanduser()
    global_memory = Path(global_root).expanduser()
    rows: list[dict[str, Any]] = []
    for target in projects:
        row: dict[str, Any] = {
            "name": target.name,
            "path": str(target.path),
            "project_root": str(target.path / ".agent_memory" / "project"),
        }
        try:
            if install:
                row["install"] = install_cross_project_memory(
                    project_root=target.path,
                    memory_system_home=memory_home,
                    python=python,
                    global_root=global_memory,
                    write=True,
                    update_existing_agents=update_existing_agents,
                )
            index_payload = maintain_indexes(
                project_root=target.path / ".agent_memory" / "project",
                global_root=global_memory,
                scope="project",
                write=write_indexes,
                agent="memorywiki-project-matrix",
            )
            row["index"] = index_payload
            row["case_coverage"] = _case_coverage(target)
            row["doctor"] = run_doctor(
                repo_root=memory_home,
                python=python,
                project_root=target.path / ".agent_memory" / "project",
                global_root=global_memory,
                config_path=target.path / ".mcp.json",
            )
            cases = [_case_from_dict(item) for item in target.cases]
            if cases:
                row["golden_eval"] = run_golden_eval(
                    project_root=target.path / ".agent_memory" / "project",
                    global_root=global_memory,
                    cases=cases,
                    min_pass_rate=min_pass_rate,
                )
            else:
                row["golden_eval"] = {
                    "status": "warn",
                    "passed": 0,
                    "failed": 0,
                    "total": 0,
                    "pass_rate": 1.0,
                    "cases": [],
                }
            if smoke:
                query = cases[0].query if cases else "MemoryWiki MCP retrieval enhancement"
                row["mcp_smoke"] = _run_project_smoke(
                    python=python,
                    memory_home=memory_home,
                    project_root=target.path / ".agent_memory" / "project",
                    global_root=global_memory,
                    query=query,
                )
        except Exception as exc:
            row["error"] = str(exc)
        row["status"] = _status_from_row(row)
        rows.append(row)
    return {
        "status": _overall(rows),
        "install": install,
        "write_indexes": write_indexes,
        "smoke": smoke,
        "projects": rows,
    }


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Project Matrix",
        "",
        "Status: {}".format(payload["status"]),
        "Install: %s" % ("yes" if payload["install"] else "no"),
        "Write indexes: %s" % ("yes" if payload["write_indexes"] else "no"),
        "MCP smoke: %s" % ("yes" if payload.get("smoke") else "no"),
        "",
        "| Project | Status | Doctor | Index | Golden | Smoke |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["projects"]:
        index_status = "error"
        if row.get("index", {}).get("roots"):
            index_status = row["index"]["roots"][0]["status"]
        golden = row.get("golden_eval", {})
        golden_text = "{}/{}".format(golden.get("passed", 0), golden.get("total", 0))
        lines.append(
            "| {name} | {status} | {doctor} | {index} | {golden} | {smoke} |".format(
                name=row["name"],
                status=row["status"],
                doctor=row.get("doctor", {}).get("status", "error"),
                index=index_status,
                golden=golden_text,
                smoke=row.get("mcp_smoke", {}).get("status", "skipped"),
            )
        )
        if row.get("error"):
            lines.append("")
            lines.append("Error for {}: {}".format(row["name"], row["error"]))
        coverage = row.get("case_coverage", {})
        if coverage.get("status") == "warn":
            lines.append("")
            lines.append("Golden coverage for {}: {}".format(row["name"], coverage.get("message", "")))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MemoryWiki rollout/doctor/golden matrix across projects.")
    parser.add_argument("--config", help="JSON project target list. See examples/project-matrix.example.json.")
    parser.add_argument("--memory-system-home", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--update-existing-agents", action="store_true")
    parser.add_argument("--write-indexes", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Run a real read-only MCP smoke for each project.")
    parser.add_argument("--min-pass-rate", type=float, default=0.75)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_project_matrix(
            projects=load_project_targets(args.config),
            memory_system_home=args.memory_system_home,
            python=args.python,
            global_root=args.global_root,
            install=args.install,
            update_existing_agents=args.update_existing_agents,
            write_indexes=args.write_indexes,
            smoke=args.smoke,
            min_pass_rate=args.min_pass_rate,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0 if payload["status"] in {"ok", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
