"""End-to-end scanner tests against the sample projects."""

from pathlib import Path

import pytest

from deploy_agent.models import ScanResult, ScanWarningCode
from deploy_agent.scanner import ScanError, scan_project

FIXTURES = Path(__file__).parent.parent / "fixtures" / "projects"


def warning_codes(result: ScanResult) -> set[ScanWarningCode]:
    return {warning.code for warning in result.warnings}


class TestPythonApp:
    @pytest.fixture
    def result(self) -> ScanResult:
        return scan_project(FIXTURES / "python_app")

    def test_stack(self, result: ScanResult) -> None:
        project = result.project

        assert (project.language, project.framework) == ("python", "fastapi")
        assert project.migration_tool == "alembic"

    def test_runtime(self, result: ScanResult) -> None:
        assert result.project.runtime_version == "3.12.4"

    def test_ports(self, result: ScanResult) -> None:
        assert result.project.ports == (8000,)

    def test_env_names_come_from_code_templates_and_dockerfile(self, result: ScanResult) -> None:
        assert result.project.env_var_names == (
            "APP_MODE",
            "DATABASE_URL",
            "LOG_LEVEL",
            "REDIS_URL",
            "SECRET_KEY",
        )

    def test_detected_files(self, result: ScanResult) -> None:
        assert result.project.detected_files == (
            ".env.example",
            ".python-version",
            "Dockerfile",
            "alembic.ini",
            "alembic/env.py",
            "pyproject.toml",
            "uv.lock",
        )

    def test_no_warnings(self, result: ScanResult) -> None:
        assert result.warnings == ()


class TestNodeApp:
    @pytest.fixture
    def result(self) -> ScanResult:
        return scan_project(FIXTURES / "node_app")

    def test_stack(self, result: ScanResult) -> None:
        project = result.project

        assert (project.language, project.framework) == ("node", "express")
        assert project.migration_tool == "prisma"

    def test_runtime(self, result: ScanResult) -> None:
        assert result.project.runtime_version == "20.11.1"

    def test_ports_come_from_code_and_scripts(self, result: ScanResult) -> None:
        assert result.project.ports == (3000, 4000)

    def test_env_names_include_typescript_reads(self, result: ScanResult) -> None:
        assert result.project.env_var_names == ("AUTH_TOKEN", "MAIL_HOST", "PORT", "STRIPE_KEY")

    def test_no_warnings(self, result: ScanResult) -> None:
        assert result.warnings == ()


class TestBrokenApp:
    @pytest.fixture
    def result(self) -> ScanResult:
        return scan_project(FIXTURES / "broken_app")

    def test_language_still_comes_from_the_broken_manifest(self, result: ScanResult) -> None:
        assert result.project.language == "node"

    def test_what_cannot_be_known_is_empty(self, result: ScanResult) -> None:
        project = result.project

        assert (project.framework, project.runtime_version, project.ports) == (None, None, ())

    def test_broken_source_still_gives_names(self, result: ScanResult) -> None:
        assert result.project.env_var_names == ("STILL_FOUND",)

    def test_each_problem_is_reported(self, result: ScanResult) -> None:
        assert warning_codes(result) == {
            ScanWarningCode.INVALID_MANIFEST,
            ScanWarningCode.INVALID_RUNTIME_VERSION,
        }


class TestEdgeCases:
    def test_empty_folder(self, tmp_path: Path) -> None:
        result = scan_project(tmp_path)

        assert result.project.language == "unknown"
        assert warning_codes(result) == {ScanWarningCode.NO_PROJECT_FOUND}

    def test_missing_folder_gives_a_clear_error(self, tmp_path: Path) -> None:
        with pytest.raises(ScanError, match="Check the path"):
            scan_project(tmp_path / "missing")

    def test_a_file_is_not_a_project(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("x", encoding="utf-8")

        with pytest.raises(ScanError, match="Check the path"):
            scan_project(target)

    def test_accepts_a_plain_string_path(self) -> None:
        assert scan_project(str(FIXTURES / "node_app")).project.language == "node"

    def test_mixed_project_reads_env_names_from_both_languages(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
        (tmp_path / "app.py").write_text('import os\nos.getenv("FROM_PY")\n', encoding="utf-8")
        (tmp_path / "ui.js").write_text("process.env.FROM_JS\n", encoding="utf-8")

        assert scan_project(tmp_path).project.env_var_names == ("FROM_JS", "FROM_PY")

    def test_nested_project_does_not_guess(self, tmp_path: Path) -> None:
        (tmp_path / "web").mkdir()
        (tmp_path / "web" / "package.json").write_text("{}", encoding="utf-8")
        (tmp_path / "web" / "app.js").write_text("process.env.HIDDEN\n", encoding="utf-8")

        result = scan_project(tmp_path)

        assert (result.project.language, result.project.env_var_names) == ("unknown", ())
        assert warning_codes(result) == {ScanWarningCode.NESTED_PROJECTS}

    def test_procfile_ports_are_found(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
        (tmp_path / "Procfile").write_text("web: gunicorn app:app -b 0.0.0.0:8100\n", "utf-8")

        assert scan_project(tmp_path).project.ports == (8100,)

    def test_dockerfile_port_setting_is_found(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM node:20\nENV PORT=8200\n", encoding="utf-8")

        assert scan_project(tmp_path).project.ports == (8200,)

    def test_repeated_warnings_are_merged(self, tmp_path: Path) -> None:
        fake_key = "sk_live_" + "fake" * 6  # Built in pieces so secret scanners do not flag it.
        (tmp_path / "a.py").write_text(f'os.getenv("{fake_key}1")\n', "utf-8")
        (tmp_path / "b.py").write_text(f'os.getenv("{fake_key}2")\n', "utf-8")

        codes = [warning.code for warning in scan_project(tmp_path).warnings]

        assert codes.count(ScanWarningCode.SUSPICIOUS_ENV_NAME) == 1


@pytest.mark.parametrize("name", ["python_app", "node_app", "broken_app"])
def test_same_input_gives_the_same_output(name: str) -> None:
    assert scan_project(FIXTURES / name) == scan_project(FIXTURES / name)
