from memory_system.config import MemoryConfig, default_memory_timezone
from memory_system.paths import MemoryScopePaths


def test_default_config_uses_local_backend_and_scoped_roots(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("MEMORY_TIMEZONE", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = MemoryConfig.from_env()
    assert cfg.backend == "local"
    assert cfg.global_write_enabled is False
    assert cfg.sanitize_on_write is True
    assert cfg.secure_permissions is True
    assert cfg.chat_write_enabled is False
    assert cfg.project_storage_root == tmp_path / ".agent_memory" / "project"
    assert cfg.global_storage_root.name == "global"
    assert cfg.model == "gpt-5.4"
    assert cfg.compaction_threshold == 50
    assert cfg.recent_window == 20
    assert cfg.core_memory_char_limit == 3000
    assert cfg.user_memory_char_limit == 1500
    assert cfg.timezone == default_memory_timezone()
    assert cfg.canonical_user_memory_path.name == "USER.md"


def test_from_env_accepts_legacy_storage_root_alias(tmp_path):
    cfg = MemoryConfig.from_env(storage_root=tmp_path / "legacy-memory")
    assert cfg.project_storage_root == tmp_path / "legacy-memory"
    assert cfg.storage_root == tmp_path / "legacy-memory"


def test_from_env_reads_project_root_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PROJECT_ROOT", str(tmp_path / "project-env"))

    cfg = MemoryConfig.from_env()

    assert cfg.project_storage_root == tmp_path / "project-env"


def test_from_env_discovers_git_project_root_from_subdirectory(tmp_path, monkeypatch):
    project = tmp_path / "repo"
    nested = project / "src" / "package"
    nested.mkdir(parents=True)
    (project / ".git").mkdir()
    monkeypatch.chdir(nested)

    cfg = MemoryConfig.from_env()

    assert cfg.project_storage_root == project / ".agent_memory" / "project"


def test_from_env_reads_memorywiki_toml_relative_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMORY_TIMEZONE", raising=False)
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".memorywiki.toml").write_text(
        "\n".join(
            [
                "[memorywiki]",
                'project_root = "memory/project"',
                'global_root = "memory/global"',
                'timezone = "UTC"',
                'model = "gpt-test"',
                "chat_write_enabled = true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    cfg = MemoryConfig.from_env()

    assert cfg.project_storage_root == project / "memory" / "project"
    assert cfg.global_storage_root == project / "memory" / "global"
    assert cfg.timezone == "UTC"
    assert cfg.model == "gpt-test"
    assert cfg.chat_write_enabled is True


def test_from_env_reads_non_secret_openai_config_from_memorywiki_toml(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".memorywiki.toml").write_text(
        "\n".join(
            [
                "[memorywiki]",
                'backend = "openai"',
                'openai_base_url = "https://example.test/v1"',
                "openai_timeout_seconds = 45",
                "openai_max_retries = 4",
                "openai_max_output_tokens = 4096",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    cfg = MemoryConfig.from_env()

    assert cfg.backend == "openai"
    assert cfg.openai_base_url == "https://example.test/v1"
    assert cfg.openai_timeout_seconds == 45
    assert cfg.openai_max_retries == 4
    assert cfg.openai_max_output_tokens == 4096
    assert cfg.openai_api_key is None


def test_from_env_reads_canonical_user_memory_path(tmp_path, monkeypatch):
    canonical_user = tmp_path / "cowork" / "memory" / "USER.md"
    monkeypatch.setenv("MEMORY_CANONICAL_USER_PATH", str(canonical_user))

    cfg = MemoryConfig.from_env()

    assert cfg.canonical_user_memory_path == canonical_user


def test_default_canonical_user_memory_path_uses_current_home(tmp_path, monkeypatch):
    home = tmp_path / "home-now"
    monkeypatch.setenv("HOME", str(home))

    cfg = MemoryConfig(
        project_storage_root=tmp_path / "project",
        global_storage_root=tmp_path / "global",
        backend="local",
        openai_api_key=None,
        openai_base_url=None,
    )

    assert cfg.canonical_user_memory_path == (
        home / ".agent_memory" / "global" / "USER.md"
    )


def test_from_env_reads_explicit_chat_write_opt_in(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_CHAT_WRITE_ENABLED", "true")

    cfg = MemoryConfig.from_env(project_storage_root=tmp_path / "project")

    assert cfg.chat_write_enabled is True


def test_from_env_reports_invalid_integer_env_name(monkeypatch):
    monkeypatch.setenv("MEMORY_RECENT_WINDOW", "ten")

    try:
        MemoryConfig.from_env()
    except ValueError as exc:
        assert "MEMORY_RECENT_WINDOW" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid integer env")


def test_from_env_reports_invalid_boolean_env_name(monkeypatch):
    monkeypatch.setenv("MEMORY_SANITIZE_ON_WRITE", "maybe")

    try:
        MemoryConfig.from_env()
    except ValueError as exc:
        assert "MEMORY_SANITIZE_ON_WRITE" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid boolean env")


def test_from_env_rejects_out_of_range_numeric_env_values(monkeypatch):
    invalid_values = {
        "OPENAI_MAX_OUTPUT_TOKENS": "0",
        "MEMORY_CORE_CHAR_LIMIT": "-1",
        "OPENAI_MAX_RETRIES": "999",
        "MEMORY_RECENT_WINDOW": "10001",
    }

    for name, value in invalid_values.items():
        monkeypatch.setenv(name, value)
        try:
            MemoryConfig.from_env()
        except ValueError as exc:
            assert name in str(exc)
        else:
            raise AssertionError(f"Expected ValueError for {name}")
        monkeypatch.delenv(name)


def test_from_env_requires_compaction_threshold_greater_than_recent_window(monkeypatch):
    monkeypatch.setenv("MEMORY_COMPACTION_THRESHOLD", "4")
    monkeypatch.setenv("MEMORY_RECENT_WINDOW", "4")

    try:
        MemoryConfig.from_env()
    except ValueError as exc:
        assert "MEMORY_COMPACTION_THRESHOLD" in str(exc)
        assert "MEMORY_RECENT_WINDOW" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unsafe compaction window")


def test_memory_scope_paths_resolve_expected_files(tmp_path):
    scope = MemoryScopePaths.from_root(tmp_path / "scope", scope="project")
    assert scope.scope == "project"
    assert scope.root == tmp_path / "scope"
    assert scope.history == tmp_path / "scope" / "history.jsonl"
    assert scope.tokens == tmp_path / "scope" / "tokens.jsonl"
    assert scope.core_memory == tmp_path / "scope" / "MEMORY.md"
    assert scope.user_memory == tmp_path / "scope" / "USER.md"
    assert scope.episodic_for_date("2026-04-23") == tmp_path / "scope" / "2026-04-23.md"


def test_memory_scope_paths_resolve_v2_episode_and_session_files(tmp_path):
    scope = MemoryScopePaths.from_root(tmp_path / "scope", scope="project")

    assert scope.episodes_dir == tmp_path / "scope" / "episodes"
    assert scope.sessions_dir == tmp_path / "scope" / "sessions"
    assert scope.pending_dir == tmp_path / "scope" / "_pending"
    assert (
        scope.episode_for_date("2026-05-08")
        == tmp_path / "scope" / "episodes" / "2026-05-08.md"
    )
    assert (
        scope.session_file("session-20260508-101500")
        == tmp_path / "scope" / "sessions" / "session-20260508-101500.md"
    )
