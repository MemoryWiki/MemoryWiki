import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_project_profile_generates_markdown_from_local_evidence(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    (project / "README.md").write_text(
        "# Demo Project\n\nA local-first demo runtime.\n",
        encoding="utf-8",
    )
    (project / "package.json").write_text(
        json.dumps({"scripts": {"test": "node test.mjs", "build": "vite build"}}),
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "project_profile.py",
            "--project-root",
            str(project),
            "--format",
            "markdown",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "# Project Profile - Demo Project" in result.stdout
    assert "A local-first demo runtime." in result.stdout
    assert "`npm run test`" in result.stdout
    assert "`python3 -m pytest tests -q`" in result.stdout


def test_project_profile_write_rejects_symlink_output(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    memory = tmp_path / "memory"
    memory.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("keep", encoding="utf-8")
    target = memory / "PROJECT_PROFILE.md"
    target.symlink_to(outside)

    result = subprocess.run(
        [
            sys.executable,
            "project_profile.py",
            "--project-root",
            str(project),
            "--memory-root",
            str(memory),
            "--write",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert outside.read_text(encoding="utf-8") == "keep"


def test_project_profile_write_creates_memory_profile(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    (project / "README.md").write_text("# Demo\n\nProfile me.\n", encoding="utf-8")
    memory = tmp_path / "memory"

    subprocess.run(
        [
            sys.executable,
            "project_profile.py",
            "--project-root",
            str(project),
            "--memory-root",
            str(memory),
            "--write",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert (memory / "PROJECT_PROFILE.md").exists()
    assert "Profile me." in (memory / "PROJECT_PROFILE.md").read_text(encoding="utf-8")
    assert "PROJECT_PROFILE.md" in (memory / "INDEX.md").read_text(encoding="utf-8")
