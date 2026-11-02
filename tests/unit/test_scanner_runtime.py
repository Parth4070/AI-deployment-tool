"""Tests for working out the required runtime version."""

import pytest

from deploy_agent.models import ScanWarningCode
from deploy_agent.scanner.docker_parser import parse_dockerfile
from deploy_agent.scanner.files import ProjectSnapshot
from deploy_agent.scanner.manifests import read_manifests
from deploy_agent.scanner.runtime import Runtime, detect_runtime, normalise_version


def runtime_of(language: str, **texts: str) -> Runtime:
    named = {name.replace("__", "."): text for name, text in texts.items()}
    snapshot = ProjectSnapshot(paths=tuple(named), texts=named)
    return detect_runtime(
        language,
        snapshot,
        read_manifests(snapshot),
        parse_dockerfile(named.get("Dockerfile", "")),
    )


def warning_codes(runtime: Runtime) -> set[ScanWarningCode]:
    return {warning.code for warning in runtime.warnings}


class TestNormaliseVersion:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("3.12.4\n", "3.12.4"),
            ("v20.11.1", "20.11.1"),
            ("python-3.12.1", "3.12.1"),
            (">= 3.12", ">=3.12"),
            (">=18 <21", ">=18,<21"),
            (">=3.10, <3.13", ">=3.10,<3.13"),
            ("20.x", "20.x"),
            ("^3.12", "^3.12"),
        ],
    )
    def test_accepted_forms(self, raw: str, expected: str) -> None:
        assert normalise_version(raw) == expected

    @pytest.mark.parametrize(
        "raw", ["lts/*", "node", "", ">=18 || <16", "x" * 200, "fake-secret value"]
    )
    def test_rejected_forms(self, raw: str) -> None:
        assert normalise_version(raw) is None


class TestPython:
    @pytest.mark.parametrize(
        ("name", "text", "expected"),
        [
            (".python-version", "3.12.4\n", "3.12.4"),
            ("pyproject.toml", '[project]\nrequires-python=">=3.11"', ">=3.11"),
            ("Pipfile", '[requires]\npython_version="3.11"', "3.11"),
            ("runtime.txt", "python-3.12.1\n", "3.12.1"),
            ("Dockerfile", "FROM python:3.12-slim\n", "3.12"),
        ],
    )
    def test_each_source(self, name: str, text: str, expected: str) -> None:
        assert runtime_of("python", **{name.replace(".", "__"): text}).version == expected

    def test_pinned_file_beats_a_range(self) -> None:
        runtime = runtime_of(
            "python",
            **{
                "__python-version": "3.12.4\n",
                "pyproject__toml": '[project]\nrequires-python=">=3.11"',
            },
        )

        assert runtime.version == "3.12.4"

    def test_dockerfile_uses_the_last_matching_stage(self) -> None:
        text = "FROM python:3.11 AS build\nFROM python:3.12\nFROM nginx\n"

        assert runtime_of("python", Dockerfile=text).version == "3.12"

    def test_image_with_no_version_is_ignored_quietly(self) -> None:
        runtime = runtime_of("python", Dockerfile="FROM python:latest\n")

        assert (runtime.version, runtime.warnings) == (None, ())

    def test_nothing_found(self) -> None:
        assert runtime_of("python").version is None


class TestNode:
    @pytest.mark.parametrize(
        ("name", "text", "expected"),
        [
            (".nvmrc", "20.11.1\n", "20.11.1"),
            (".node-version", "v20\n", "20"),
            ("package.json", '{"engines":{"node":">=20"}}', ">=20"),
            ("Dockerfile", "FROM node:20-alpine\n", "20"),
        ],
    )
    def test_each_source(self, name: str, text: str, expected: str) -> None:
        assert runtime_of("node", **{name.replace(".", "__"): text}).version == expected

    def test_invalid_file_warns_and_later_source_is_used(self) -> None:
        runtime = runtime_of("node", __nvmrc="lts/*\n", Dockerfile="FROM node:20\n")

        assert runtime.version == "20"
        assert ScanWarningCode.INVALID_RUNTIME_VERSION in warning_codes(runtime)
        assert runtime.warnings[0].path == ".nvmrc"


class TestConflicts:
    def test_different_pins_warn(self) -> None:
        runtime = runtime_of("node", __nvmrc="20\n", Dockerfile="FROM node:18\n")

        assert runtime.version == "20"
        assert ScanWarningCode.RUNTIME_CONFLICT in warning_codes(runtime)

    def test_more_exact_pin_of_the_same_version_is_fine(self) -> None:
        runtime = runtime_of("node", __nvmrc="20.11.1\n", Dockerfile="FROM node:20\n")

        assert runtime.warnings == ()

    def test_a_range_is_not_compared(self) -> None:
        runtime = runtime_of("node", __nvmrc="20\n", package__json='{"engines":{"node":">=18"}}')

        assert runtime.warnings == ()


def test_unknown_language_has_no_runtime() -> None:
    runtime = runtime_of("unknown", __nvmrc="20\n")

    assert (runtime.version, runtime.warnings) == (None, ())
