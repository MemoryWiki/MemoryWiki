from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union


OPENAI_TIMEOUT_RANGE = (1, 300)
OPENAI_MAX_RETRIES_RANGE = (0, 10)
OPENAI_MAX_OUTPUT_TOKENS_RANGE = (1, 200000)
MEMORY_WINDOW_RANGE = (1, 10000)
MEMORY_CHAR_LIMIT_RANGE = (1, 1000000)
DEFAULT_MEMORY_TIMEZONE = "Asia/Shanghai"
DEFAULT_CANONICAL_USER_MEMORY_PATH = "~/.agent_memory/global/USER.md"


def _expand_user_path(value: str | Path) -> Path:
    raw = str(value)
    if raw == "~" or raw.startswith("~/") or raw.startswith("~\\"):
        home = os.getenv("HOME") or os.path.expanduser("~")
        suffix = raw[2:] if len(raw) > 1 else ""
        return Path(home) / suffix if suffix else Path(home)
    return Path(os.path.expanduser(raw))


def _default_canonical_user_memory_path() -> Path:
    return _expand_user_path(DEFAULT_CANONICAL_USER_MEMORY_PATH)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError("%s must be an integer" % name)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("%s must be a boolean" % name)


def _validate_int_range(name: str, value: int, minimum: int, maximum: int) -> int:
    if value < minimum or value > maximum:
        raise ValueError("%s must be between %s and %s" % (name, minimum, maximum))
    return value


@dataclass
class MemoryConfig:
    project_storage_root: Path
    global_storage_root: Path
    backend: str
    openai_api_key: Optional[str]
    openai_base_url: Optional[str]
    model: str = "gpt-5.4"
    openai_timeout_seconds: int = 30
    openai_max_retries: int = 2
    openai_max_output_tokens: int = 2048
    compaction_threshold: int = 50
    recent_window: int = 20
    core_memory_char_limit: int = 3000
    user_memory_char_limit: int = 1500
    timezone: str = DEFAULT_MEMORY_TIMEZONE
    global_write_enabled: bool = False
    chat_write_enabled: bool = False
    sanitize_on_write: bool = True
    secure_permissions: bool = True
    canonical_user_memory_path: Path = field(
        default_factory=_default_canonical_user_memory_path
    )

    @property
    def storage_root(self) -> Path:
        return self.project_storage_root

    @classmethod
    def from_env(
        cls,
        project_storage_root: Union[str, Path, None] = None,
        storage_root: Union[str, Path, None] = None,
    ) -> "MemoryConfig":
        cwd = Path.cwd()
        if project_storage_root is None and storage_root is not None:
            project_storage_root = storage_root
        if project_storage_root is None and os.getenv("MEMORY_PROJECT_ROOT"):
            project_storage_root = os.getenv("MEMORY_PROJECT_ROOT")
        project_root = (
            Path(project_storage_root)
            if project_storage_root is not None
            else cwd / ".agent_memory" / "project"
        )
        global_root = _expand_user_path(
            os.getenv("MEMORY_GLOBAL_ROOT", "~/.agent_memory/global")
        )
        openai_timeout_seconds = _env_int("OPENAI_TIMEOUT_SECONDS", 30)
        openai_max_retries = _env_int("OPENAI_MAX_RETRIES", 2)
        openai_max_output_tokens = _env_int("OPENAI_MAX_OUTPUT_TOKENS", 2048)
        compaction_threshold = _env_int("MEMORY_COMPACTION_THRESHOLD", 50)
        recent_window = _env_int("MEMORY_RECENT_WINDOW", 20)
        core_memory_char_limit = _env_int("MEMORY_CORE_CHAR_LIMIT", 3000)
        user_memory_char_limit = _env_int("MEMORY_USER_CHAR_LIMIT", 1500)
        _validate_int_range(
            "OPENAI_TIMEOUT_SECONDS", openai_timeout_seconds, *OPENAI_TIMEOUT_RANGE
        )
        _validate_int_range(
            "OPENAI_MAX_RETRIES", openai_max_retries, *OPENAI_MAX_RETRIES_RANGE
        )
        _validate_int_range(
            "OPENAI_MAX_OUTPUT_TOKENS",
            openai_max_output_tokens,
            *OPENAI_MAX_OUTPUT_TOKENS_RANGE,
        )
        _validate_int_range(
            "MEMORY_COMPACTION_THRESHOLD",
            compaction_threshold,
            *MEMORY_WINDOW_RANGE,
        )
        _validate_int_range("MEMORY_RECENT_WINDOW", recent_window, *MEMORY_WINDOW_RANGE)
        _validate_int_range(
            "MEMORY_CORE_CHAR_LIMIT", core_memory_char_limit, *MEMORY_CHAR_LIMIT_RANGE
        )
        _validate_int_range(
            "MEMORY_USER_CHAR_LIMIT", user_memory_char_limit, *MEMORY_CHAR_LIMIT_RANGE
        )
        if compaction_threshold <= recent_window:
            raise ValueError(
                "MEMORY_COMPACTION_THRESHOLD must be greater than MEMORY_RECENT_WINDOW"
            )

        return cls(
            project_storage_root=project_root,
            global_storage_root=global_root,
            backend=os.getenv("MEMORY_BACKEND", "local"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL"),
            model=os.getenv("OPENAI_MODEL", "gpt-5.4"),
            openai_timeout_seconds=openai_timeout_seconds,
            openai_max_retries=openai_max_retries,
            openai_max_output_tokens=openai_max_output_tokens,
            compaction_threshold=compaction_threshold,
            recent_window=recent_window,
            core_memory_char_limit=core_memory_char_limit,
            user_memory_char_limit=user_memory_char_limit,
            timezone=os.getenv("MEMORY_TIMEZONE", DEFAULT_MEMORY_TIMEZONE),
            global_write_enabled=_env_bool("MEMORY_GLOBAL_WRITE_ENABLED", False),
            chat_write_enabled=_env_bool("MEMORY_CHAT_WRITE_ENABLED", False),
            sanitize_on_write=_env_bool("MEMORY_SANITIZE_ON_WRITE", True),
            secure_permissions=_env_bool("MEMORY_SECURE_PERMISSIONS", True),
            canonical_user_memory_path=_expand_user_path(
                os.getenv(
                    "MEMORY_CANONICAL_USER_PATH",
                    DEFAULT_CANONICAL_USER_MEMORY_PATH,
                )
            ),
        )
