from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from memorywiki_cross_project_install import install_cross_project_memory


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cross_project_install_dry_run_reports_agents_and_mcp_without_writing(tmp_path):
    project = tmp_path / "target"
    project.mkdir()

    payload = install_cross_project_memory(
        project_root=project,
        memory_system_home=REPO_ROOT,
        python="/usr/bin/python3.12",
        write=False,
    )

    assert payload["dry_run"] is True
    assert {item["path"] for item in payload["actions"]} == {"AGENTS.md", ".mcp.json"}
    assert not (project / "AGENTS.md").exists()
    assert not (project / ".mcp.json").exists()


def test_cross_project_install_write_creates_agents_and_read_only_mcp_config(tmp_path):
    project = tmp_path / "target"
    project.mkdir()

    payload = install_cross_project_memory(
        project_root=project,
        memory_system_home=REPO_ROOT,
        python="/usr/bin/python3.12",
        write=True,
    )

    assert payload["dry_run"] is False
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    config = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    env = config["mcpServers"]["memorywiki-memory"]["env"]
    assert "MCP Memory Bridge" in agents
    assert "/usr/bin/python3.12" in agents
    assert "--python \"$MEMORYWIKI_MCP_PYTHON\"" in agents
    assert env["MEMORY_PROJECT_ROOT"] == str(project / ".agent_memory" / "project")
    assert env["MEMORY_BACKEND"] == "local"
    assert "MEMORY_MCP_WRITE_ENABLED" not in env
    assert "MEMORY_GLOBAL_WRITE_ENABLED" not in env


def test_cross_project_install_merges_existing_mcp_config_without_clobbering(tmp_path):
    project = tmp_path / "target"
    project.mkdir()
    (project / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"existing": {"command": "echo"}}}),
        encoding="utf-8",
    )

    install_cross_project_memory(
        project_root=project,
        memory_system_home=REPO_ROOT,
        python="/usr/bin/python3.12",
        write=True,
    )

    payload = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    assert set(payload["mcpServers"]) == {"existing", "memorywiki-memory"}


def test_cross_project_install_refuses_existing_agents_without_force(tmp_path):
    project = tmp_path / "target"
    project.mkdir()
    (project / "AGENTS.md").write_text("keep me\n", encoding="utf-8")

    payload = install_cross_project_memory(
        project_root=project,
        memory_system_home=REPO_ROOT,
        python="/usr/bin/python3.12",
        write=True,
    )

    assert payload["actions"][0]["status"] == "skipped_exists"
    assert (project / "AGENTS.md").read_text(encoding="utf-8") == "keep me\n"


def test_cross_project_install_can_update_existing_agents_with_managed_block(tmp_path):
    project = tmp_path / "target"
    project.mkdir()
    target = project / "AGENTS.md"
    target.write_text("# Existing\n\nKeep this section.\n", encoding="utf-8")

    payload = install_cross_project_memory(
        project_root=project,
        memory_system_home=REPO_ROOT,
        python="/usr/bin/python3.12",
        write=True,
        update_existing_agents=True,
    )
    text = target.read_text(encoding="utf-8")

    assert payload["actions"][0]["status"] == "updated"
    assert "Keep this section." in text
    assert "BEGIN MemoryWiki MCP BRIDGE" in text
    assert "memorywiki_mcp_doctor.py" in text
    assert "memory_health.py" in text
    assert "memorywiki_quality_report.py" in text
    assert "memorywiki_knowledge_ops.py" in text
    assert "--mcp-config \"$(pwd)/.mcp.json\"" in text
    assert "Top Next Actions" in text
    assert "--stage-candidates" in text
    assert "memorywiki_ops_dashboard.py" in text
    assert "Recommended Actions" in text
    assert "memory_feedback.py" in text
    assert "memory_review.py" in text
    assert "memory_lifecycle.py" in text
    assert "memorywiki_restore_check.py" in text
    assert "memorywiki_release_manifest.py" in text
    assert "memorywiki_mcp_contract.py" in text
    assert "--promote-golden-candidate" in text
    assert "--fill-golden-candidate" in text
    assert "--reject-golden-candidate" in text
    assert "retrieval baseline comparison" in text
    assert "local embedding readiness" in text
    assert "cross-project reliability" in text
    assert "/usr/bin/python3.12" in text
    assert "${MEMORYWIKI_MCP_PYTHON:-'" not in text


def test_cross_project_install_updates_existing_managed_block_in_place(tmp_path):
    project = tmp_path / "target"
    project.mkdir()
    target = project / "AGENTS.md"
    target.write_text(
        "# Existing\n\n<!-- BEGIN MemoryWiki MCP BRIDGE -->\nold\n<!-- END MemoryWiki MCP BRIDGE -->\n",
        encoding="utf-8",
    )

    install_cross_project_memory(
        project_root=project,
        memory_system_home=REPO_ROOT,
        python="/usr/bin/python3.12",
        write=True,
        update_existing_agents=True,
    )
    text = target.read_text(encoding="utf-8")

    assert "\nold\n" not in text
    assert text.count("BEGIN MemoryWiki MCP BRIDGE") == 1


def test_cross_project_install_rejects_symlinked_mcp_config(tmp_path):
    project = tmp_path / "target"
    project.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    (project / ".mcp.json").symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        install_cross_project_memory(
            project_root=project,
            memory_system_home=REPO_ROOT,
            python="/usr/bin/python3.12",
            write=True,
        )


def test_cross_project_install_rejects_broken_symlinked_mcp_config(tmp_path):
    project = tmp_path / "target"
    project.mkdir()
    (project / ".mcp.json").symlink_to(tmp_path / "missing.json")

    with pytest.raises(ValueError, match="symlink"):
        install_cross_project_memory(
            project_root=project,
            memory_system_home=REPO_ROOT,
            python="/usr/bin/python3.12",
            write=True,
        )


def test_cross_project_install_rejects_project_below_symlinked_parent(tmp_path):
    real_parent = tmp_path / "real-parent"
    project = real_parent / "target"
    project.mkdir(parents=True)
    link_parent = tmp_path / "link-parent"
    link_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        install_cross_project_memory(
            project_root=link_parent / "target",
            memory_system_home=REPO_ROOT,
            python="/usr/bin/python3.12",
            write=True,
        )

    assert not (project / "AGENTS.md").exists()
    assert not (project / ".mcp.json").exists()


def test_cross_project_install_cli_outputs_json(tmp_path):
    project = tmp_path / "target"
    project.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "memorywiki_cross_project_install.py",
            "--project-root",
            str(project),
            "--python",
            "/usr/bin/python3.12",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["project_root"] == str(project)
    assert payload["dry_run"] is True
