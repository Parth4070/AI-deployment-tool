"""Tests for the runtime-version and lockfile checks."""

import pytest

from deploy_agent.models import Severity
from deploy_agent.preflight.checks.lockfile import count_unpinned, lockfile_present
from deploy_agent.preflight.checks.runtime import (
    pins_agree,
    runtime_version_mismatch,
    satisfies,
)

PYPROJECT = '[project]\nname = "x"\nrequires-python = ">=3.12"\ndependencies = ["fastapi"]\n'


class TestVersionHelpers:
    @pytest.mark.parametrize(
        ("first", "second", "agree"),
        [("3.12", "3.12.4", True), ("3.12.1", "3.12.4", False), ("20", "20.11.1", True)],
    )
    def test_pins_agree(self, first: str, second: str, agree: bool) -> None:
        assert pins_agree(first, second) is agree

    @pytest.mark.parametrize(
        ("pin", "version_range", "expected"),
        [
            ("3.12.4", ">=3.12", True),
            ("3.11", ">=3.12", False),
            ("3.12", ">=3.12,<3.13", True),
            ("3.13", ">=3.12,<3.13", False),
            ("3.12", ">=3.12.4", None),  # depends on the patch release
            ("20.1", "^20", None),  # caret ranges are not understood, so no guess
        ],
    )
    def test_satisfies(self, pin: str, version_range: str, expected: bool | None) -> None:
        assert satisfies(pin, version_range) is expected


class TestRuntimeVersionMismatch:
    def test_passes_when_files_agree(self, make_context) -> None:
        context = make_context(
            {".python-version": "3.12.4\n", "pyproject.toml": PYPROJECT,
             "Dockerfile": "FROM python:3.12-slim\n"}
        )
        assert runtime_version_mismatch(context).passed

    def test_fails_when_pins_disagree(self, make_context) -> None:
        context = make_context(
            {".python-version": "3.11\n", "pyproject.toml": '[project]\nname = "x"\n',
             "Dockerfile": "FROM python:3.12-slim\n"}
        )
        result = runtime_version_mismatch(context)

        assert not result.passed
        assert result.severity == Severity.ERROR
        assert ".python-version says 3.11 but Dockerfile says 3.12" in (result.evidence or "")

    def test_fails_when_pin_is_outside_range(self, make_context) -> None:
        context = make_context({".python-version": "3.11\n", "pyproject.toml": PYPROJECT})
        result = runtime_version_mismatch(context)

        assert not result.passed
        assert "outside pyproject.toml (>=3.12)" in (result.evidence or "")

    def test_fails_when_target_differs(self, make_context) -> None:
        context = make_context(
            {".nvmrc": "20.11.1\n", "package.json": '{"name": "x"}'}, runtime_version="22"
        )
        result = runtime_version_mismatch(context)

        assert not result.passed
        assert "the deploy target says 22" in (result.evidence or "")

    def test_passes_when_target_matches(self, make_context) -> None:
        context = make_context(
            {".nvmrc": "20.11.1\n", "package.json": '{"name": "x"}'}, runtime_version="20"
        )
        assert runtime_version_mismatch(context).passed

    def test_warns_when_nothing_is_declared(self, make_context) -> None:
        result = runtime_version_mismatch(make_context({"package.json": '{"name": "x"}'}))

        assert not result.passed
        assert result.severity == Severity.WARNING
        assert ".nvmrc" in (result.suggested_fix or "")

    def test_skips_without_a_project(self, make_context) -> None:
        result = runtime_version_mismatch(make_context({"README.md": "hi"}))
        assert result.passed and (result.evidence or "").startswith("Skipped")


class TestLockfilePresent:
    def test_passes_with_npm_lock(self, make_context) -> None:
        context = make_context({"package.json": "{}", "package-lock.json": "{}"})
        assert lockfile_present(context).passed

    def test_passes_with_uv_lock(self, make_context) -> None:
        context = make_context({"pyproject.toml": PYPROJECT, "uv.lock": ""})
        assert lockfile_present(context).passed

    def test_passes_with_fully_pinned_requirements(self, make_context) -> None:
        context = make_context(
            {"pyproject.toml": PYPROJECT, "requirements.txt": "fastapi==0.110.0\n-r base.txt\n"}
        )
        assert lockfile_present(context).passed

    def test_fails_for_package_json_alone(self, make_context) -> None:
        result = lockfile_present(make_context({"package.json": "{}"}))

        assert not result.passed
        assert result.severity == Severity.WARNING
        assert "package.json has no lockfile" in (result.evidence or "")

    def test_fails_for_pipfile_without_lock(self, make_context) -> None:
        result = lockfile_present(make_context({"Pipfile": "[packages]\n"}))
        assert not result.passed and "Pipfile.lock" in (result.evidence or "")

    def test_fails_for_pyproject_without_lock(self, make_context) -> None:
        result = lockfile_present(make_context({"pyproject.toml": PYPROJECT}))
        assert not result.passed and "pyproject.toml" in (result.evidence or "")

    def test_counts_unpinned_requirements_without_quoting_them(self, make_context) -> None:
        text = "flask\nrequests>=2\nprivate @ https://fake-token@example.invalid/x.whl\n"
        result = lockfile_present(make_context({"requirements.txt": text}))

        assert not result.passed
        assert "2 of 3 lines in requirements.txt" in (result.evidence or "")
        assert "fake-token" not in result.model_dump_json()

    def test_skips_without_manifest(self, make_context) -> None:
        assert lockfile_present(make_context({"README.md": "hi"})).passed

    def test_count_unpinned_ignores_options_and_comments(self) -> None:
        assert count_unpinned("# c\n-r a.txt\nx==1  # pinned\ny\n") == (1, 2)
