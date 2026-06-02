"""Minimal TOML config reader and writer for `.memorywiki.toml`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # pragma: no cover - Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10 fallback
    tomllib = None


CONFIG_FILE_NAME = ".memorywiki.toml"


def discover_project_base(start: str | Path | None = None) -> Path:
    cursor = Path(start or Path.cwd()).expanduser().resolve()
    if cursor.is_file():
        cursor = cursor.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / ".git").exists():
            return candidate
    return cursor


def default_project_memory_root(start: str | Path | None = None) -> Path:
    return discover_project_base(start) / ".agent_memory" / "project"


def find_config_file(start: str | Path | None = None) -> Path | None:
    cursor = Path(start or Path.cwd()).expanduser().resolve()
    if cursor.is_file():
        cursor = cursor.parent
    for candidate in (cursor, *cursor.parents):
        path = candidate / CONFIG_FILE_NAME
        if path.exists():
            return path
    return None


def load_config_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    if config_path.is_symlink() or not config_path.is_file():
        raise ValueError(f"Config file must be a real file: {config_path}")
    raw = config_path.read_bytes()
    if len(raw) > 200_000:
        raise ValueError(f"Config file is too large: {config_path}")
    payload = (
        tomllib.loads(raw.decode("utf-8"))
        if tomllib is not None
        else _parse_minimal_toml(raw.decode("utf-8"))
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Config file must contain a TOML table: {config_path}")
    table = payload.get("memorywiki", payload)
    if not isinstance(table, dict):
        raise ValueError("[memorywiki] must be a TOML table")
    return dict(table)


def write_default_config(path: str | Path, *, overwrite: bool = False) -> Path:
    config_path = Path(path).expanduser()
    if config_path.exists() and not overwrite:
        raise ValueError(f"Config file already exists: {config_path}")
    if config_path.exists() and (config_path.is_symlink() or not config_path.is_file()):
        raise ValueError(f"Config file path must be a real file: {config_path}")
    _assert_safe_parent(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "# MemoryWiki local-first configuration.",
                "# CLI flags and environment variables override these file defaults.",
                "[memorywiki]",
                "",
                "# Project-local memory defaults to the nearest Git repository.",
                'project_root = ".agent_memory/project"',
                'global_root = "~/.agent_memory/global"',
                "",
                "# Use backend = \"openai\" only when OPENAI_API_KEY is supplied explicitly.",
                'backend = "local"',
                'model = "gpt-5.4"',
                "# openai_base_url = \"https://api.openai.com/v1\"",
                "# openai_timeout_seconds = 30",
                "# openai_max_retries = 2",
                "# openai_max_output_tokens = 2048",
                "# Never store OPENAI_API_KEY here; keep secrets in environment variables.",
                "",
                "# Keep timezone unset to use the local machine timezone automatically.",
                "# timezone = \"UTC\"",
                "",
                "# Compaction and recall windows. compaction_threshold must exceed recent_window.",
                "compaction_threshold = 50",
                "recent_window = 20",
                "core_memory_char_limit = 3000",
                "user_memory_char_limit = 1500",
                "",
                "# Writes are opt-in. Leave both false for read-mostly startup flows.",
                "chat_write_enabled = false",
                "global_write_enabled = false",
                "sanitize_on_write = true",
                "secure_permissions = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _assert_safe_parent(path: Path) -> None:
    cursor = path.parent
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError(f"Config parent may not be a symlink: {cursor}")
    for ancestor in cursor.parents:
        if ancestor.exists() and ancestor.is_symlink():
            raise ValueError(f"Config parent may not be below a symlink: {ancestor}")


def _parse_minimal_toml(text: str) -> dict[str, Any]:
    current: dict[str, Any] = {}
    root: dict[str, Any] = {}
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if not section:
                raise ValueError(f"Invalid TOML section at line {lineno}")
            current = root.setdefault(section, {})
            if not isinstance(current, dict):
                raise ValueError(f"Invalid TOML table at line {lineno}")
            continue
        if "=" not in line:
            raise ValueError(f"Invalid TOML assignment at line {lineno}")
        key, value = [part.strip() for part in line.split("=", 1)]
        current[key] = _parse_minimal_value(value, lineno)
    return root


def _parse_minimal_value(value: str, lineno: int) -> Any:
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Unsupported TOML value at line {lineno}: {value}")
