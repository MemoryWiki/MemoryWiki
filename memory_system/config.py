"""Environment and config-file resolution for MemoryWiki runtime settings."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memory_system.config_file import (
    default_project_memory_root,
    find_config_file,
    load_config_file,
)

OPENAI_TIMEOUT_RANGE = (1, 300)
OPENAI_MAX_RETRIES_RANGE = (0, 10)
OPENAI_MAX_OUTPUT_TOKENS_RANGE = (1, 200000)
MEMORY_WINDOW_RANGE = (1, 10000)
MEMORY_CHAR_LIMIT_RANGE = (1, 1000000)
DEFAULT_MEMORY_TIMEZONE = "local"
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


def default_memory_timezone() -> str:
    configured = os.getenv("TZ")
    if configured and _is_valid_timezone(configured):
        return configured
    localtime = _timezone_from_localtime()
    if localtime:
        return localtime
    tzinfo = datetime.now().astimezone().tzinfo
    key = getattr(tzinfo, "key", None)
    if key and _is_valid_timezone(str(key)):
        return str(key)
    name = time.tzname[0] if time.tzname else ""
    if name and _is_valid_timezone(name):
        return name
    return "UTC"


def _is_valid_timezone(value: str) -> bool:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return False
    return True


def _timezone_from_localtime() -> str | None:
    localtime = Path("/etc/localtime")
    try:
        target = localtime.resolve(strict=True)
    except OSError:
        return None
    parts = target.parts
    if "zoneinfo" not in parts:
        return None
    index = parts.index("zoneinfo")
    name = "/".join(parts[index + 1 :])
    return name if name and _is_valid_timezone(name) else None


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _config_bool(config: dict, name: str, default: bool) -> bool:
    value = config.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{name} must be a boolean")


def _config_int(config: dict, name: str, default: int) -> int:
    value = config.get(name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")


def _config_path(config: dict, name: str, base_dir: Path) -> Path | None:
    raw = config.get(name)
    if raw is None:
        return None
    path = _expand_user_path(str(raw))
    return path if path.is_absolute() else base_dir / path


def _validate_int_range(name: str, value: int, minimum: int, maximum: int) -> int:
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
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
        config_path = (
            Path(os.environ["MEMORY_CONFIG_PATH"]).expanduser()
            if os.getenv("MEMORY_CONFIG_PATH")
            else find_config_file(cwd)
        )
        file_config = load_config_file(config_path) if config_path else {}
        config_base = config_path.parent if config_path else cwd
        if project_storage_root is None and storage_root is not None:
            project_storage_root = storage_root
        if project_storage_root is None and os.getenv("MEMORY_PROJECT_ROOT"):
            project_storage_root = os.getenv("MEMORY_PROJECT_ROOT")
        if project_storage_root is None:
            project_storage_root = _config_path(
                file_config,
                "project_root",
                config_base,
            ) or _config_path(file_config, "project_storage_root", config_base)
        project_root = (
            _expand_user_path(project_storage_root)
            if project_storage_root is not None
            else default_project_memory_root(cwd)
        )
        global_root = (
            _expand_user_path(os.environ["MEMORY_GLOBAL_ROOT"])
            if os.getenv("MEMORY_GLOBAL_ROOT")
            else (
                _config_path(file_config, "global_root", config_base)
                or _config_path(file_config, "global_storage_root", config_base)
                or _expand_user_path("~/.agent_memory/global")
            )
        )
        openai_timeout_seconds = _env_int(
            "OPENAI_TIMEOUT_SECONDS",
            _config_int(file_config, "openai_timeout_seconds", 30),
        )
        openai_max_retries = _env_int(
            "OPENAI_MAX_RETRIES",
            _config_int(file_config, "openai_max_retries", 2),
        )
        openai_max_output_tokens = _env_int(
            "OPENAI_MAX_OUTPUT_TOKENS",
            _config_int(file_config, "openai_max_output_tokens", 2048),
        )
        compaction_threshold = _env_int(
            "MEMORY_COMPACTION_THRESHOLD",
            _config_int(file_config, "compaction_threshold", 50),
        )
        recent_window = _env_int(
            "MEMORY_RECENT_WINDOW",
            _config_int(file_config, "recent_window", 20),
        )
        core_memory_char_limit = _env_int(
            "MEMORY_CORE_CHAR_LIMIT",
            _config_int(file_config, "core_memory_char_limit", 3000),
        )
        user_memory_char_limit = _env_int(
            "MEMORY_USER_CHAR_LIMIT",
            _config_int(file_config, "user_memory_char_limit", 1500),
        )
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
            backend=os.getenv("MEMORY_BACKEND", str(file_config.get("backend", "local"))),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv(
                "OPENAI_BASE_URL", str(file_config.get("openai_base_url", "")) or None
            ),
            model=os.getenv("OPENAI_MODEL", str(file_config.get("model", "gpt-5.4"))),
            openai_timeout_seconds=openai_timeout_seconds,
            openai_max_retries=openai_max_retries,
            openai_max_output_tokens=openai_max_output_tokens,
            compaction_threshold=compaction_threshold,
            recent_window=recent_window,
            core_memory_char_limit=core_memory_char_limit,
            user_memory_char_limit=user_memory_char_limit,
            timezone=os.getenv(
                "MEMORY_TIMEZONE",
                str(file_config.get("timezone", default_memory_timezone())),
            ),
            global_write_enabled=_env_bool(
                "MEMORY_GLOBAL_WRITE_ENABLED",
                _config_bool(file_config, "global_write_enabled", False),
            ),
            chat_write_enabled=_env_bool(
                "MEMORY_CHAT_WRITE_ENABLED",
                _config_bool(file_config, "chat_write_enabled", False),
            ),
            sanitize_on_write=_env_bool(
                "MEMORY_SANITIZE_ON_WRITE",
                _config_bool(file_config, "sanitize_on_write", True),
            ),
            secure_permissions=_env_bool(
                "MEMORY_SECURE_PERMISSIONS",
                _config_bool(file_config, "secure_permissions", True),
            ),
            canonical_user_memory_path=_expand_user_path(
                os.getenv(
                    "MEMORY_CANONICAL_USER_PATH",
                    str(
                        _config_path(
                            file_config,
                            "canonical_user_memory_path",
                            config_base,
                        )
                        or DEFAULT_CANONICAL_USER_MEMORY_PATH
                    ),
                )
            ),
        )
