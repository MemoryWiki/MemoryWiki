import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


FORBIDDEN_MARKERS = [
    "lzd" + "5669",
    "/Users" + "/",
    "Documents/" + "CODEX",
    "personal" + "_memory_system",
    "personal" + "-memory" + "-system",
    "local" + "-memory" + "-system",
    "private" + "-git" + "-remotes",
    "private" + "-local",
    "." + "codex",
    "YOUR" + "_NAME",
    "personal-agent" + "-memory",
    "P" + "MS",
    "p" + "ms_",
    "p" + "ms-",
    "Field" + "Notes",
    "field" + "notes",
    "Codex" + " Trade" + " System",
    "tra" + "ding" + "-system",
    "Deep" + " Security" + " Hunter",
    "deep" + "-security" + "-hunter",
    "DS" + "H",
    "ds" + "h-",
    "Per" + "sona" + " Dist" + "iller",
    "persona" + "-distiller",
    "Paper" + "clip",
    "paper" + "clip",
]


SKIP_DIRS = {
    ".codegraph",
    ".git",
    ".idea",
    ".mypy_cache",
    ".pyrefly",
    ".pyrefly_cache",
    ".pytest_cache",
    ".qodercn",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "venv",
}
SKIP_FILE_PREFIXES = (".coverage", "codegraph-")
SKIP_SUFFIXES = {".pyc", ".pyo"}
ARCHIVE_SUFFIXES = {".skill", ".zip", ".whl", ".tar", ".gz", ".tgz"}
SECRET_PATTERNS = [
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"Bearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE),
]


def test_public_tree_has_no_private_or_legacy_markers():
    offenders = []
    allowed_marker_files = {Path("tests/test_public_clean.py")}
    for path in REPO_ROOT.rglob("*"):
        relative = path.relative_to(REPO_ROOT)
        if path.name == ".git" and path != REPO_ROOT / ".git":
            offenders.append(f"{relative} is a nested git repository")
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name.startswith(SKIP_FILE_PREFIXES):
            continue
        if path.suffix in SKIP_SUFFIXES or not path.is_file():
            continue
        if path.suffix in ARCHIVE_SUFFIXES:
            offenders.append(f"{relative} is an archive artifact")
            continue
        data = path.read_bytes()
        for marker in FORBIDDEN_MARKERS:
            if relative in allowed_marker_files:
                continue
            if marker.encode("utf-8") in data:
                offenders.append(f"{relative} contains {marker}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(data):
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains secret-like material")
    assert offenders == []


def test_git_history_has_no_private_or_legacy_markers():
    revs = subprocess.run(
        ["git", "rev-list", "--all"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    if not revs:
        return
    history_patterns = [
        "/Users" + "/",
        "Documents/" + "CODEX",
        "personal" + "_memory_system",
        "personal" + "-memory" + "-system",
        "personal-agent" + "-memory",
        "private" + "-git" + "-remotes",
        "private" + "-local",
        "lzd" + "5669",
        "deep" + "-security" + "-hunter",
        "ds" + "h-",
        "gh[pousr]_[A-Za-z0-9_]{20,}",
        "sk-(proj-)?[A-Za-z0-9_-]{20,}",
        "AKIA[A-Z0-9]{16}",
        "ASIA[A-Z0-9]{16}",
        "-----BEGIN .*" + "PRIVATE KEY-----",
    ]
    result = subprocess.run(
        ["git", "grep", "-I", "-l", "-E", "|".join(history_patterns), *revs],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    allowed = (
        ":memory_system/sanitizer.py",
        ":tests/test_sanitizer.py",
        ":tests/test_public_clean.py",
    )
    offenders = [
        line
        for line in result.stdout.splitlines()
        if line and not any(line.endswith(suffix) for suffix in allowed)
    ]
    paths = subprocess.run(
        ["git", "log", "--all", "--name-only", "--pretty=format:"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    path_markers = [
        "/Users" + "/",
        "Documents/" + "CODEX",
        "personal" + "_memory_system",
        "personal" + "-memory" + "-system",
        "personal-agent" + "-memory",
        "private" + "-git" + "-remotes",
        "private" + "-local",
        "lzd" + "5669",
        "deep" + "-security" + "-hunter",
        "ds" + "h-",
    ]
    path_pattern = re.compile("|".join(re.escape(marker) for marker in path_markers), re.IGNORECASE)
    offenders.extend(path for path in paths if path_pattern.search(path))
    assert offenders == []
