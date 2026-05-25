from __future__ import annotations

from pathlib import Path

from memory_system.config import MemoryConfig
from memory_system.manager import MemoryManager
from memory_system.paths import validate_episodic_date


def parse_command(text):
    stripped = text.strip()
    if not stripped.startswith("/"):
        return "", stripped
    parts = stripped[1:].split(" ", 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1].strip()


def build_manager():
    config = MemoryConfig.from_env()
    if config.backend == "openai" and not config.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required when MEMORY_BACKEND=openai")
    return MemoryManager.build(config=config, source_project=Path.cwd().name)


def handle_command(manager, command, value):
    if command == "memory":
        return manager.overlay_store.project_store.read_core_memory()
    if command == "user":
        return manager.overlay_store.project_store.read_user_memory()
    if command == "index":
        manager.overlay_store.project_store.refresh_index()
        return manager.overlay_store.project_store.read_index()
    if command == "sessions":
        sessions = manager.recent_session_summaries(limit=10)
        if not sessions:
            return "No session summaries found."
        return "\n".join(
            f"[{session.ts[:19]}] {session.session_id} - {session.summary}"
            for session in sessions
        )
    if command == "day":
        try:
            validate_episodic_date(value)
        except ValueError as exc:
            return str(exc)
        return manager.overlay_store.project_store.read_episodic(value)
    if command == "scope":
        return f"backend={manager.config.backend} global={manager.overlay_store.global_store.paths.root} project={manager.overlay_store.project_store.paths.root}"
    if command == "promote":
        parts = value.split()
        if len(parts) != 2 or parts[1] != "confirm" or parts[0] not in ("user", "memory"):
            return "Type /promote user confirm or /promote memory confirm to write project memory into global memory."
        try:
            if parts[0] == "user":
                manager.promotion.promote_user_memory()
                return "Promoted project user memory into global memory."
            manager.promotion.promote_core_memory()
            return "Promoted project core memory into global memory."
        except PermissionError as exc:
            return str(exc)
    if command == "search-global":
        return manager.retrieve_memories(keyword=value, source="all", scope="global")
    if command == "search-project":
        return manager.retrieve_memories(keyword=value, source="all", scope="project")
    if command == "search":
        return manager.retrieve_memories(keyword=value, source="all", scope="all")
    return None


def read_user_text(prompt="you> "):
    try:
        return input(prompt).strip()
    except EOFError:
        return None


def main():
    manager = build_manager()
    print(
        "Agent memory demo. Chat is read-only unless MEMORY_CHAT_WRITE_ENABLED=true. "
        "Type /memory, /user, /index, /sessions, /day YYYY-MM-DD, /scope, "
        "/promote user confirm, /search keyword, or /quit."
    )
    while True:
        user_text = read_user_text()
        if user_text is None:
            break
        if user_text in ("/quit", "/exit"):
            break

        command, value = parse_command(user_text)
        command_result = handle_command(manager, command, value)
        if command_result is not None:
            if hasattr(command_result, "hits"):
                result = command_result
                for hit in result.hits[:10]:
                    print(
                        f"[{hit.scope}/{hit.source}] {hit.identifier}: {hit.excerpt}"
                    )
            else:
                print(command_result)
            continue

        reply = manager.run_turn(user_text)
        print(f"assistant> {reply}")


if __name__ == "__main__":
    main()
