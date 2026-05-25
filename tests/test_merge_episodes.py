import subprocess
import sys
from pathlib import Path

import merge_episodes as merge_module
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore
from merge_episodes import merge_episodes

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_merge_episodes_imports_flat_cowork_daily_files_to_v2(tmp_path):
    src = tmp_path / "cowork" / "memory"
    dst = tmp_path / "global"
    src.mkdir(parents=True)
    fake_key = "sk-proj-" + "abc1234567890abcdef1234567890abcdef"
    (src / "2026-05-08.md").write_text(
        f"## 09:00 Cowork note\n\n- Imported fact {fake_key}\n",
        encoding="utf-8",
    )

    merged = merge_episodes(src_dir=src, dst_root=dst, scope="global")
    second = merge_episodes(src_dir=src, dst_root=dst, scope="global")
    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(dst, scope="global"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    episode = store.read_episode("2026-05-08")

    assert merged == [store.paths.episode_for_date("2026-05-08")]
    assert second == []
    assert episode is not None
    assert "Cowork import" in episode.body
    assert "Imported fact" in episode.body
    assert fake_key not in episode.body
    assert "[REDACTED_OPENAI_KEY]" in episode.body
    assert episode.body.count("source: cowork:2026-05-08") == 1


def test_merge_episodes_skips_symlinked_source_files(tmp_path):
    src = tmp_path / "cowork" / "memory"
    dst = tmp_path / "global"
    outside = tmp_path / "outside.md"
    src.mkdir(parents=True)
    outside.write_text("## 09:00 Unsafe\n\n- Should not import\n", encoding="utf-8")
    (src / "2026-05-08.md").symlink_to(outside)

    merged = merge_episodes(src_dir=src, dst_root=dst, scope="global")

    assert merged == []
    assert not (dst / "episodes" / "2026-05-08.md").exists()


def test_merge_episodes_rechecks_source_file_after_safe_listing(tmp_path, monkeypatch):
    src = tmp_path / "cowork" / "memory"
    dst = tmp_path / "global"
    outside = tmp_path / "outside.md"
    src.mkdir(parents=True)
    outside.write_text("## 09:00 Unsafe\n\n- Should not import\n", encoding="utf-8")
    source = src / "2026-05-08.md"
    source.symlink_to(outside)
    monkeypatch.setattr(merge_module, "_safe_daily_files", lambda src_dir: [source])

    merged = merge_episodes(src_dir=src, dst_root=dst, scope="global")

    assert merged == []
    assert not (dst / "episodes" / "2026-05-08.md").exists()


def test_merge_episodes_skips_unreadable_source_files(tmp_path):
    src = tmp_path / "cowork" / "memory"
    dst = tmp_path / "global"
    src.mkdir(parents=True)
    (src / "2026-05-07.md").write_bytes(b"\xff\xfe\x00")
    (src / "2026-05-08.md").write_text(
        "## 09:00 Readable\n\n- Should import\n", encoding="utf-8"
    )

    merged = merge_episodes(src_dir=src, dst_root=dst, scope="global")

    assert merged == [MemoryScopePaths.from_root(dst, "global").episode_for_date("2026-05-08")]
    assert not (dst / "episodes" / "2026-05-07.md").exists()


def test_merge_episodes_cli_reports_imported_count(tmp_path):
    src = tmp_path / "cowork" / "memory"
    dst = tmp_path / "global"
    src.mkdir(parents=True)
    (src / "2026-05-08.md").write_text(
        "## 09:00 Cowork note\n\n- CLI import\n", encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "merge_episodes.py",
            "--src",
            str(src),
            "--dst",
            str(dst),
            "--scope",
            "global",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Imported 1 episode" in result.stdout
