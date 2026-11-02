"""Tests for reading a project folder safely.

All secret-looking values in this file are fake.
"""

import os
from pathlib import Path

import pytest

from deploy_agent.models import ScanWarningCode
from deploy_agent.scanner import files
from deploy_agent.scanner.files import is_private_env_file, load_snapshot

FAKE_VALUE = "fake-value-that-must-never-be-read"


def codes(root: Path) -> set[ScanWarningCode]:
    return {warning.code for warning in load_snapshot(root).warnings}


class TestPrivateEnvFiles:
    @pytest.mark.parametrize(
        "name",
        [".env", ".ENV", ".env.local", ".env.production", ".envrc", "production.env"],
    )
    def test_real_env_files_are_private(self, name: str) -> None:
        assert is_private_env_file(name)

    @pytest.mark.parametrize(
        "name",
        [".env.example", ".env.sample", ".env.template", ".ENV.EXAMPLE", "env.py", "environ.js"],
    )
    def test_templates_and_ordinary_files_are_not_private(self, name: str) -> None:
        assert not is_private_env_file(name)


class TestLoadSnapshot:
    def test_private_env_file_is_never_listed_or_read(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text(f"SECRET={FAKE_VALUE}\n", encoding="utf-8")

        snapshot = load_snapshot(tmp_path)

        assert ".env" not in snapshot.paths
        assert ".env" not in snapshot.texts

    def test_env_template_is_read(self, tmp_path: Path) -> None:
        (tmp_path / ".env.example").write_text("NAME=\n", encoding="utf-8")

        assert "NAME=" in load_snapshot(tmp_path).texts[".env.example"]

    def test_unrelated_files_are_listed_but_not_read(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text(FAKE_VALUE, encoding="utf-8")

        snapshot = load_snapshot(tmp_path)

        assert "notes.txt" in snapshot.paths
        assert "notes.txt" not in snapshot.texts

    def test_config_file_in_a_subfolder_is_not_read(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "package.json").write_text("{}", encoding="utf-8")

        snapshot = load_snapshot(tmp_path)

        assert "sub/package.json" in snapshot.paths
        assert "sub/package.json" not in snapshot.texts

    def test_source_in_a_subfolder_is_read_with_forward_slashes(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "deep").mkdir(parents=True)
        (tmp_path / "src" / "deep" / "app.py").write_text("x = 1\n", encoding="utf-8")

        assert "src/deep/app.py" in load_snapshot(tmp_path).texts

    @pytest.mark.parametrize("folder", ["node_modules", ".venv", ".git", "tests", "__pycache__"])
    def test_tool_and_test_folders_are_skipped(self, tmp_path: Path, folder: str) -> None:
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "thing.js").write_text("x\n", encoding="utf-8")

        assert load_snapshot(tmp_path).paths == ()

    def test_paths_are_sorted(self, tmp_path: Path) -> None:
        for name in ("b.py", "a.py", "c.py"):
            (tmp_path / name).write_text("", encoding="utf-8")

        assert load_snapshot(tmp_path).paths == ("a.py", "b.py", "c.py")

    def test_empty_folder_gives_empty_snapshot(self, tmp_path: Path) -> None:
        snapshot = load_snapshot(tmp_path)

        assert (snapshot.paths, snapshot.warnings) == ((), ())

    def test_byte_order_mark_is_removed(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_bytes(b"\xef\xbb\xbf{}")

        assert load_snapshot(tmp_path).texts["package.json"] == "{}"

    def test_invalid_utf8_does_not_crash(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_bytes(b"x = '\xff\xfe'\n")

        assert "x = " in load_snapshot(tmp_path).texts["app.py"]

    def test_binary_file_is_skipped_with_a_warning(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_bytes(b"\x00\x01\x02")

        snapshot = load_snapshot(tmp_path)

        assert "app.py" not in snapshot.texts
        assert ScanWarningCode.UNREADABLE_FILE in {w.code for w in snapshot.warnings}

    def test_file_over_the_size_limit_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(files, "MAX_FILE_BYTES", 4)
        (tmp_path / "app.py").write_text("x = 12345\n", encoding="utf-8")

        snapshot = load_snapshot(tmp_path)

        assert "app.py" not in snapshot.texts
        assert ScanWarningCode.FILE_TOO_LARGE in {w.code for w in snapshot.warnings}

    def test_file_count_limit_stops_the_walk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(files, "MAX_FILES", 2)
        for name in ("a.py", "b.py", "c.py"):
            (tmp_path / name).write_text("", encoding="utf-8")

        snapshot = load_snapshot(tmp_path)

        assert len(snapshot.paths) == 2
        assert ScanWarningCode.LIMIT_REACHED in {w.code for w in snapshot.warnings}

    def test_depth_limit_stops_the_walk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(files, "MAX_DEPTH", 1)
        (tmp_path / "one" / "two").mkdir(parents=True)
        (tmp_path / "one" / "two" / "app.py").write_text("", encoding="utf-8")

        assert ScanWarningCode.LIMIT_REACHED in codes(tmp_path)

    def test_total_read_limit_stops_reading(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(files, "MAX_TOTAL_BYTES", 5)
        (tmp_path / "a.py").write_text("1234", encoding="utf-8")
        (tmp_path / "b.py").write_text("1234", encoding="utf-8")

        snapshot = load_snapshot(tmp_path)

        assert list(snapshot.texts) == ["a.py"]
        assert ScanWarningCode.LIMIT_REACHED in {w.code for w in snapshot.warnings}

    def test_unusual_file_name_is_left_out_with_a_warning(self, tmp_path: Path) -> None:
        (tmp_path / "we$ird.py").write_text("", encoding="utf-8")

        snapshot = load_snapshot(tmp_path)

        assert snapshot.paths == ()
        warning = snapshot.warnings[0]
        assert (warning.code, warning.path) == (ScanWarningCode.UNUSUAL_PATH, None)

    def test_symlink_is_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        project = tmp_path / "project"
        outside.mkdir()
        project.mkdir()
        (outside / "stolen.py").write_text(FAKE_VALUE, encoding="utf-8")
        try:
            os.symlink(outside / "stolen.py", project / "link.py")
        except OSError:
            pytest.skip("This machine does not allow creating symlinks")

        snapshot = load_snapshot(project)

        assert "link.py" not in snapshot.texts
        assert ScanWarningCode.SYMLINK_SKIPPED in {w.code for w in snapshot.warnings}
