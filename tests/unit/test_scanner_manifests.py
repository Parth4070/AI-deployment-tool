"""Tests for reading dependency files and Dockerfiles. Broken input must never crash."""

import pytest

from deploy_agent.models import ScanWarningCode
from deploy_agent.scanner.docker_parser import parse_dockerfile
from deploy_agent.scanner.files import ProjectSnapshot
from deploy_agent.scanner.manifests import Manifests, read_manifests


def manifests_of(**texts: str) -> Manifests:
    named = {name.replace("__", "."): text for name, text in texts.items()}
    return read_manifests(ProjectSnapshot(paths=tuple(named), texts=named))


class TestPythonManifests:
    def test_pyproject_dependencies_are_normalised(self) -> None:
        text = '[project]\nrequires-python=">=3.12"\ndependencies=["Flask_Migrate[x]>=4","Django"]'

        found = manifests_of(pyproject__toml=text)

        assert found.python_deps == {"flask-migrate", "django"}
        assert found.requires_python == ">=3.12"

    def test_poetry_dependencies_are_read(self) -> None:
        text = '[tool.poetry.dependencies]\npython="^3.12"\nflask="^3"'

        found = manifests_of(pyproject__toml=text)

        assert found.python_deps == {"flask"}
        assert found.requires_python == "^3.12"

    def test_requirements_skip_comments_options_and_blanks(self) -> None:
        text = "# note\n-r other.txt\n\nFastAPI==0.110  # pinned\nuvicorn[standard]\n"

        assert manifests_of(requirements__txt=text).python_deps == {"fastapi", "uvicorn"}

    def test_pipfile_is_read(self) -> None:
        text = '[packages]\nflask="*"\n[requires]\npython_version="3.12"\n'

        found = manifests_of(Pipfile=text)

        assert found.python_deps == {"flask"}
        assert found.pipfile_python == "3.12"

    @pytest.mark.parametrize(
        "text",
        [
            "not toml [",
            "project = 1",
            "[project]\ndependencies = 5",
            "[project]\nrequires-python = 3",
        ],
    )
    def test_bad_pyproject_gives_no_crash(self, text: str) -> None:
        found = manifests_of(pyproject__toml=text)

        assert found.python_deps == frozenset()
        assert found.requires_python is None

    def test_unparseable_pyproject_warns(self) -> None:
        found = manifests_of(pyproject__toml="not toml [")

        assert found.warnings[0].code is ScanWarningCode.INVALID_MANIFEST
        assert found.warnings[0].path == "pyproject.toml"


class TestPackageJson:
    def test_dependencies_scripts_and_engine_are_read(self) -> None:
        text = (
            '{"dependencies":{"Express":"4"},"devDependencies":{"prisma":"5"},'
            '"scripts":{"dev":"next dev -p 4000"},"engines":{"node":">=20"}}'
        )

        found = manifests_of(package__json=text)

        assert found.node_deps == {"express", "prisma"}
        assert found.node_scripts == ("next dev -p 4000",)
        assert found.engines_node == ">=20"

    @pytest.mark.parametrize("text", ["{ broken", "", "[]", "5", '"text"', "[" * 100_000, "null"])
    def test_bad_json_warns_without_crashing(self, text: str) -> None:
        found = manifests_of(package__json=text)

        assert found.node_deps == frozenset()
        assert found.warnings[0].code is ScanWarningCode.INVALID_MANIFEST

    @pytest.mark.parametrize(
        "text",
        [
            '{"dependencies":[]}',
            '{"scripts":5}',
            '{"scripts":{"a":1}}',
            '{"engines":"20"}',
            '{"engines":{"node":20}}',
        ],
    )
    def test_wrong_types_inside_are_ignored(self, text: str) -> None:
        found = manifests_of(package__json=text)

        assert found.node_deps == frozenset()
        assert found.node_scripts == ()
        assert found.engines_node is None


class TestDockerfile:
    def test_base_image_and_tag(self) -> None:
        assert parse_dockerfile("FROM python:3.12-slim\n").images == (("python", "3.12-slim"),)

    def test_registry_platform_and_stage_name_are_handled(self) -> None:
        text = "FROM --platform=linux/amd64 docker.io/library/node:20-alpine AS build\n"

        assert parse_dockerfile(text).images == (("node", "20-alpine"),)

    def test_every_stage_is_kept_in_order(self) -> None:
        text = "FROM node:20 AS build\nFROM nginx\n"

        assert parse_dockerfile(text).images == (("node", "20"), ("nginx", ""))

    def test_exposed_ports(self) -> None:
        assert parse_dockerfile("EXPOSE 8000 9000/tcp ${PORT} nope\n").ports == (8000, 9000)

    def test_env_keeps_names_only(self) -> None:
        text = 'ENV A=1 B="two words C=3" D=fake-value\nENV LEGACY some value\nARG TOKEN=fake\n'

        names = parse_dockerfile(text).env_names

        assert names == ("A", "B", "D", "LEGACY", "TOKEN")

    def test_continued_lines_are_joined(self) -> None:
        assert parse_dockerfile("ENV A=1 \\\n  B=2\n").env_names == ("A", "B")

    def test_comments_are_ignored(self) -> None:
        assert parse_dockerfile("# EXPOSE 80\n").ports == ()

    def test_commands_are_kept_for_port_search(self) -> None:
        text = 'CMD ["uvicorn", "main:app", "--port", "8000"]\n'

        assert "--port" in parse_dockerfile(text).commands[0]

    def test_env_lines_are_kept_for_port_search(self) -> None:
        assert "PORT=8080" in parse_dockerfile("ENV PORT=8080\n").commands[0]

    def test_other_env_lines_are_not_kept(self) -> None:
        assert parse_dockerfile("ENV TOKEN=fake-value\n").commands == ()

    def test_keywords_are_case_insensitive(self) -> None:
        assert parse_dockerfile("expose 80\n").ports == (80,)

    @pytest.mark.parametrize("text", ["", "FROM\n", "ENV\n", "EXPOSE\n", "ARG\n", "\\\n"])
    def test_broken_lines_do_not_crash(self, text: str) -> None:
        assert parse_dockerfile(text).images == ()
