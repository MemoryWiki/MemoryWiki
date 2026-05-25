from demo_chat import handle_command, parse_command, read_user_text


def test_parse_memory_command():
    command, value = parse_command("/memory")
    assert command == "memory"
    assert value == ""


def test_parse_day_command():
    command, value = parse_command("/day 2026-04-23")
    assert command == "day"
    assert value == "2026-04-23"


def test_parse_search_command():
    command, value = parse_command("/search timezone")
    assert command == "search"
    assert value == "timezone"


def test_parse_promote_command():
    command, value = parse_command("/promote user")
    assert command == "promote"
    assert value == "user"


def test_parse_scope_command():
    command, value = parse_command("/scope")
    assert command == "scope"
    assert value == ""


def test_parse_index_command():
    command, value = parse_command("/index")
    assert command == "index"
    assert value == ""


class FakePromotion:
    def __init__(self):
        self.calls = []

    def promote_user_memory(self):
        self.calls.append("user")

    def promote_core_memory(self):
        self.calls.append("memory")


class FakeManager:
    def __init__(self):
        self.promotion = FakePromotion()
        self.overlay_store = type(
            "Overlay",
            (),
            {
                "project_store": type(
                "ProjectStore",
                (),
                    {
                        "read_episodic": staticmethod(lambda date_text: f"day {date_text}"),
                        "refresh_index": staticmethod(lambda: None),
                        "read_index": staticmethod(lambda: "# Memory Index"),
                    },
                )()
            },
        )()

    def recent_session_summaries(self, limit=10):
        return []


def test_promote_command_requires_explicit_confirmation():
    manager = FakeManager()

    result = handle_command(manager, "promote", "user")

    assert "confirm" in result.lower()
    assert manager.promotion.calls == []


def test_promote_command_runs_after_confirmation():
    manager = FakeManager()

    result = handle_command(manager, "promote", "user confirm")

    assert "Promoted project user memory" in result
    assert manager.promotion.calls == ["user"]


def test_day_command_requires_date_value():
    result = handle_command(FakeManager(), "day", "")

    assert "YYYY-MM-DD" in result


def test_index_command_reads_project_index():
    result = handle_command(FakeManager(), "index", "")

    assert result == "# Memory Index"


def test_sessions_command_handles_empty_list():
    result = handle_command(FakeManager(), "sessions", "")

    assert "No session summaries" in result


def test_read_user_text_returns_none_on_eof(monkeypatch):
    def raise_eof(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    assert read_user_text() is None
