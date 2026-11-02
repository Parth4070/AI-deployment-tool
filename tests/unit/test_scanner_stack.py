"""Tests for working out language, framework and migration tool."""

import pytest

from deploy_agent.models import ScanWarningCode
from deploy_agent.scanner.docker_parser import parse_dockerfile
from deploy_agent.scanner.files import ProjectSnapshot
from deploy_agent.scanner.manifests import read_manifests
from deploy_agent.scanner.stack import Stack, detect_stack


def stack_of(*paths: str, **texts: str) -> Stack:
    named = {name.replace("__", "."): text for name, text in texts.items()}
    snapshot = ProjectSnapshot(paths=tuple(sorted({*paths, *named})), texts=named)
    return detect_stack(
        snapshot, read_manifests(snapshot), parse_dockerfile(named.get("Dockerfile", ""))
    )


def warning_codes(stack: Stack) -> set[ScanWarningCode]:
    return {warning.code for warning in stack.warnings}


class TestLanguage:
    def test_python_manifest(self) -> None:
        assert stack_of(requirements__txt="flask\n").language == "python"

    def test_node_manifest(self) -> None:
        assert stack_of(package__json="{}").language == "node"

    def test_empty_project_is_unknown(self) -> None:
        stack = stack_of()

        assert stack.language == "unknown"
        assert warning_codes(stack) == {ScanWarningCode.NO_PROJECT_FOUND}

    def test_dockerfile_alone_gives_the_language(self) -> None:
        stack = stack_of(Dockerfile="FROM node:20\n")

        assert stack.language == "node"
        assert ScanWarningCode.MISSING_MANIFEST in warning_codes(stack)

    def test_source_files_alone_give_the_language(self) -> None:
        stack = stack_of("app.py")

        assert stack.language == "python"
        assert ScanWarningCode.MISSING_MANIFEST in warning_codes(stack)

    def test_manifest_beats_source_files(self) -> None:
        assert stack_of("static/site.js", requirements__txt="flask\n").language == "python"

    def test_framework_decides_a_mixed_project(self) -> None:
        stack = stack_of(
            requirements__txt="requests\n", package__json='{"dependencies":{"next":"1"}}'
        )

        assert (stack.language, stack.framework) == ("node", "next")
        assert ScanWarningCode.MIXED_LANGUAGES in warning_codes(stack)

    @pytest.mark.parametrize(
        ("requirements", "package"),
        [("flask\n", '{"dependencies":{"express":"4"}}'), ("requests\n", "{}")],
        ids=["both-have-a-framework", "neither-has-a-framework"],
    )
    def test_python_wins_a_tie_with_a_warning(self, requirements: str, package: str) -> None:
        stack = stack_of(requirements__txt=requirements, package__json=package)

        assert stack.language == "python"
        assert ScanWarningCode.MIXED_LANGUAGES in warning_codes(stack)

    def test_projects_only_in_subfolders_are_unknown(self) -> None:
        stack = stack_of("frontend/package.json", "frontend/src/app.js", "backend/requirements.txt")

        assert stack.language == "unknown"
        assert ScanWarningCode.NESTED_PROJECTS in warning_codes(stack)


class TestFramework:
    @pytest.mark.parametrize(
        ("deps", "framework"),
        [
            ("django\n", "django"),
            ("fastapi\n", "fastapi"),
            ("flask\n", "flask"),
            ("requests\n", None),
        ],
    )
    def test_python_frameworks(self, deps: str, framework: str | None) -> None:
        assert stack_of(requirements__txt=deps).framework == framework

    @pytest.mark.parametrize(
        ("dep", "framework"),
        [
            ("next", "next"),
            ("nuxt", "nuxt"),
            ("@nestjs/core", "nestjs"),
            ("fastify", "fastify"),
            ("koa", "koa"),
            ("express", "express"),
            ("left-pad", None),
        ],
    )
    def test_node_frameworks(self, dep: str, framework: str | None) -> None:
        text = f'{{"dependencies":{{"{dep}":"1"}}}}'

        assert stack_of(package__json=text).framework == framework

    def test_more_specific_framework_wins(self) -> None:
        text = '{"dependencies":{"express":"4","@nestjs/core":"10"}}'

        assert stack_of(package__json=text).framework == "nestjs"


class TestMigrationTool:
    @pytest.mark.parametrize("deps", ["alembic\n", "flask-migrate\n"])
    def test_alembic_from_dependencies(self, deps: str) -> None:
        assert stack_of(requirements__txt=deps).migration_tool == "alembic"

    def test_alembic_from_its_config_file(self) -> None:
        assert stack_of("alembic.ini", requirements__txt="x\n").migration_tool == "alembic"

    def test_django_with_migrations_folder(self) -> None:
        stack = stack_of("shop/migrations/__init__.py", requirements__txt="django\n")

        assert stack.migration_tool == "django"

    def test_django_without_migrations_has_no_tool(self) -> None:
        assert stack_of(requirements__txt="django\n").migration_tool is None

    @pytest.mark.parametrize(
        ("dep", "tool"),
        [
            ("prisma", "prisma"),
            ("@prisma/client", "prisma"),
            ("drizzle-kit", "drizzle"),
            ("knex", "knex"),
            ("sequelize-cli", "sequelize"),
            ("typeorm", "typeorm"),
            ("sequelize", None),
        ],
    )
    def test_node_tools(self, dep: str, tool: str | None) -> None:
        text = f'{{"dependencies":{{"{dep}":"1"}}}}'

        assert stack_of(package__json=text).migration_tool == tool

    def test_prisma_from_its_schema_file(self) -> None:
        assert stack_of("prisma/schema.prisma", package__json="{}").migration_tool == "prisma"


class TestDetectedFiles:
    def test_only_marker_files_are_listed(self) -> None:
        stack = stack_of("uv.lock", "src/app.py", "notes.txt", requirements__txt="x\n")

        assert stack.detected_files == ("requirements.txt", "uv.lock")
