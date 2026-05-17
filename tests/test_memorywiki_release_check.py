from __future__ import annotations

import zipfile

from memorywiki_release_check import (
    _safe_skill_source_files,
    build_release_commands,
    summarize_results,
)


def test_release_check_builds_expected_core_commands():
    commands = build_release_commands(
        python="/venv/bin/python",
        test_python="/usr/bin/python3",
        repo_root="/repo",
        project_root="/repo/.agent_memory/project",
        global_root="/home/me/.agent_memory/global",
        config="/repo/.mcp.json",
        project_matrix_config="/repo/examples/project-matrix.example.json",
        mcp_contract="/repo/docs/memorywiki-mcp-v1-contract.json",
        skill_archive="memorywiki-v0.1.0.skill",
        backup_root="memorywiki-backups",
        backup_name="memorywiki-core",
        max_backup_age_hours=168,
        skip_tests=False,
        skip_smoke=False,
        skip_project_matrix=False,
    )
    joined = "\n".join(" ".join(command.argv) for command in commands)

    assert "memory_index_maintain.py" in joined
    assert "memory_health.py" in joined
    assert "memory_review.py" in joined
    assert "memorywiki_quality_report.py" in joined
    assert "memorywiki-golden-cases.json" in joined
    assert "memory_lifecycle.py" in joined
    assert "memorywiki_restore_check.py" in joined
    assert "memorywiki_ops_dashboard.py" in joined
    assert "memorywiki_knowledge_ops.py" in joined
    assert "--mcp-config /repo/.mcp.json" in joined
    assert "memorywiki_release_manifest.py" not in joined
    assert "memorywiki_mcp_doctor.py" in joined
    assert "memorywiki_mcp_contract.py --verify /repo/docs/memorywiki-mcp-v1-contract.json" in joined
    assert "retrieval_golden_eval.py" in joined
    assert "memorywiki_project_matrix.py" in joined
    assert "--backup-root memorywiki-backups --backup-name memorywiki-core" in joined
    assert "--max-backup-age-hours 168 --fail-on-backup-issue" in joined
    assert "zip -T memorywiki-v0.1.0.skill" in joined
    assert "git remote get-url origin" in joined
    assert "-m memorywiki_mcp.smoke_client" in joined
    assert "/usr/bin/python3 -m pytest tests -q" in joined
    assert "-m compileall -q ." in joined
    assert "git status --short . AGENTS.md .mcp.json pyproject.toml" in joined


def test_release_check_writes_manifest_when_requested(tmp_path, monkeypatch):
    import memorywiki_release_check

    def fake_run(argv, cwd=None, env=None, text=None, capture_output=None):
        return memorywiki_release_check.subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def fake_write_manifest(**kwargs):
        path = kwargs["out"]
        path.write_text("{}\n", encoding="utf-8")
        return path

    monkeypatch.setattr(memorywiki_release_check.subprocess, "run", fake_run)
    monkeypatch.setattr(memorywiki_release_check, "write_release_manifest", fake_write_manifest)

    payload = memorywiki_release_check.run_release_check(
        python="/venv/bin/python",
        test_python="/usr/bin/python3",
        repo_root=tmp_path,
        project_root=tmp_path / ".agent_memory" / "project",
        global_root=tmp_path / "global",
        config=tmp_path / ".mcp.json",
        skill_archive=None,
        backup_root=None,
        manifest_out=tmp_path / "manifest.json",
        skip_tests=True,
        skip_smoke=True,
        skip_project_matrix=True,
    )

    assert payload["status"] == "ok"
    assert payload["manifest_path"] == str(tmp_path / "manifest.json")
    assert any(result["name"] == "release-manifest" for result in payload["results"])


def test_release_check_summary_fails_when_any_required_command_fails():
    payload = summarize_results(
        [
            {"name": "ok", "returncode": 0, "required": True},
            {"name": "bad", "returncode": 1, "required": True},
        ]
    )

    assert payload["status"] == "fail"


def test_release_check_summary_warns_for_optional_failures():
    payload = summarize_results(
        [
            {"name": "ok", "returncode": 0, "required": True},
            {"name": "smoke", "returncode": 1, "required": False},
        ]
    )

    assert payload["status"] == "warn"


def test_release_check_fails_when_scoped_git_status_is_dirty(tmp_path, monkeypatch):
    import memorywiki_release_check

    def fake_run(argv, cwd=None, env=None, text=None, capture_output=None):
        stdout = " M README.md\n" if argv[:3] == ["git", "status", "--short"] else ""
        return memorywiki_release_check.subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(memorywiki_release_check.subprocess, "run", fake_run)

    payload = memorywiki_release_check.run_release_check(
        python="/venv/bin/python",
        test_python="/usr/bin/python3",
        repo_root=tmp_path,
        project_root=tmp_path / ".agent_memory" / "project",
        global_root=tmp_path / "global",
        config=tmp_path / ".mcp.json",
        skill_archive=None,
        backup_root=None,
        skip_tests=True,
        skip_smoke=True,
        skip_project_matrix=True,
    )

    git_status = next(item for item in payload["results"] if item["name"] == "git-status")
    assert payload["status"] == "fail"
    assert "git-status" in payload["required_failures"]
    assert git_status["returncode"] == 1
    assert "dirty" in git_status["stderr"]


def test_release_check_allow_dirty_keeps_dirty_status_explicit(tmp_path, monkeypatch):
    import memorywiki_release_check

    def fake_run(argv, cwd=None, env=None, text=None, capture_output=None):
        stdout = " M README.md\n" if argv[:3] == ["git", "status", "--short"] else ""
        return memorywiki_release_check.subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(memorywiki_release_check.subprocess, "run", fake_run)

    payload = memorywiki_release_check.run_release_check(
        python="/venv/bin/python",
        test_python="/usr/bin/python3",
        repo_root=tmp_path,
        project_root=tmp_path / ".agent_memory" / "project",
        global_root=tmp_path / "global",
        config=tmp_path / ".mcp.json",
        skill_archive=None,
        backup_root=None,
        skip_tests=True,
        skip_smoke=True,
        skip_project_matrix=True,
        allow_dirty=True,
    )

    git_status = next(item for item in payload["results"] if item["name"] == "git-status")
    assert payload["status"] == "ok"
    assert git_status["returncode"] == 0
    assert "dirty allowed" in git_status["stderr"]


def test_release_check_skips_mcp_smoke_on_python_without_mcp_extra(tmp_path, monkeypatch):
    import memorywiki_release_check

    def fake_run(argv, cwd=None, env=None, text=None, capture_output=None):
        assert "-m memorywiki_mcp.smoke_client" not in " ".join(argv)
        return memorywiki_release_check.subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(memorywiki_release_check.subprocess, "run", fake_run)
    monkeypatch.setattr(memorywiki_release_check, "_mcp_extra_supported", lambda python: False)

    payload = memorywiki_release_check.run_release_check(
        python="/venv/bin/python",
        test_python="/usr/bin/python3",
        repo_root=tmp_path,
        project_root=tmp_path / ".agent_memory" / "project",
        global_root=tmp_path / "global",
        config=tmp_path / ".mcp.json",
        skill_archive=None,
        backup_root=None,
        skip_tests=True,
        skip_project_matrix=True,
    )

    mcp_smoke = next(item for item in payload["results"] if item["name"] == "mcp-smoke")
    assert payload["status"] == "ok"
    assert mcp_smoke["returncode"] == 0
    assert mcp_smoke["skipped"] is True
    assert "Python >=3.10" in mcp_smoke["stdout"]


def test_release_check_fails_stale_skill_archive_against_source(tmp_path, monkeypatch):
    import memorywiki_release_check

    source = tmp_path / "memorywiki-skill"
    (source / "agents").mkdir(parents=True)
    (source / "SKILL.md").write_text("current skill\n", encoding="utf-8")
    (source / "agents" / "openai.yaml").write_text("current agent\n", encoding="utf-8")
    archive = tmp_path / "memorywiki-skill.skill"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("memorywiki-skill/SKILL.md", "stale skill\n")
        handle.writestr("memorywiki-skill/agents/openai.yaml", "current agent\n")

    def fake_run(argv, cwd=None, env=None, text=None, capture_output=None):
        return memorywiki_release_check.subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(memorywiki_release_check.subprocess, "run", fake_run)

    payload = memorywiki_release_check.run_release_check(
        python="/venv/bin/python",
        test_python="/usr/bin/python3",
        repo_root=tmp_path,
        project_root=tmp_path / ".agent_memory" / "project",
        global_root=tmp_path / "global",
        config=tmp_path / ".mcp.json",
        skill_archive=archive,
        skill_source_dir=source,
        backup_root=None,
        skip_tests=True,
        skip_smoke=True,
        skip_project_matrix=True,
    )

    archive_source = next(item for item in payload["results"] if item["name"] == "skill-archive-source")
    assert payload["status"] == "fail"
    assert "skill-archive-source" in payload["required_failures"]
    assert archive_source["returncode"] == 1
    assert "mismatch" in archive_source["stderr"]


def test_release_check_requires_explicit_skill_source_dir(tmp_path, monkeypatch):
    import memorywiki_release_check

    archive = tmp_path / "memorywiki-skill.skill"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("memorywiki-skill/SKILL.md", "current skill\n")

    def fake_run(argv, cwd=None, env=None, text=None, capture_output=None):
        return memorywiki_release_check.subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(memorywiki_release_check.subprocess, "run", fake_run)

    payload = memorywiki_release_check.run_release_check(
        python="/venv/bin/python",
        test_python="/usr/bin/python3",
        repo_root=tmp_path,
        project_root=tmp_path / ".agent_memory" / "project",
        global_root=tmp_path / "global",
        config=tmp_path / ".mcp.json",
        skill_archive=archive,
        backup_root=None,
        skip_tests=True,
        skip_smoke=True,
        skip_project_matrix=True,
    )

    archive_source = next(item for item in payload["results"] if item["name"] == "skill-archive-source")
    assert payload["status"] == "fail"
    assert archive_source["returncode"] == 1
    assert "--skill-source-dir is required" in archive_source["stderr"]


def test_release_check_rejects_symlink_in_skill_source(tmp_path, monkeypatch):
    import memorywiki_release_check

    outside = tmp_path / "outside.yaml"
    outside.write_text("external\n", encoding="utf-8")
    source = tmp_path / "memorywiki-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("current skill\n", encoding="utf-8")
    (source / "linked-agent.yaml").symlink_to(outside)
    archive = tmp_path / "memorywiki-skill.skill"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("memorywiki-skill/SKILL.md", "current skill\n")

    def fake_run(argv, cwd=None, env=None, text=None, capture_output=None):
        return memorywiki_release_check.subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(memorywiki_release_check.subprocess, "run", fake_run)

    payload = memorywiki_release_check.run_release_check(
        python="/venv/bin/python",
        test_python="/usr/bin/python3",
        repo_root=tmp_path,
        project_root=tmp_path / ".agent_memory" / "project",
        global_root=tmp_path / "global",
        config=tmp_path / ".mcp.json",
        skill_archive=archive,
        skill_source_dir=source,
        backup_root=None,
        skip_tests=True,
        skip_smoke=True,
        skip_project_matrix=True,
    )

    archive_source = next(item for item in payload["results"] if item["name"] == "skill-archive-source")
    assert payload["status"] == "fail"
    assert archive_source["returncode"] == 1
    assert "symlink" in archive_source["stderr"]


def test_safe_skill_source_files_skips_generated_and_private_dirs(tmp_path):
    source = tmp_path / "memorywiki-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("current skill\n", encoding="utf-8")
    for dirname, filename in [
        (".git", "config"),
        (".agent_memory", "MEMORY.md"),
        ("__pycache__", "module.pyc"),
        (".pytest_cache", "README.md"),
        ("dist", "package.whl"),
        ("release_manifests", "manifest.json"),
        ("memorywiki.egg-info", "PKG-INFO"),
    ]:
        directory = source / dirname
        directory.mkdir(parents=True)
        (directory / filename).write_text("generated\n", encoding="utf-8")

    rows = _safe_skill_source_files(source)

    assert set(rows) == {"SKILL.md"}
