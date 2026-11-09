"""Tests for the Dockerfile parser additions and the Dockerfile checks."""

import pytest

from deploy_agent.models import Severity
from deploy_agent.preflight.checks.dockerfile import (
    dockerfile_base_image,
    dockerfile_dockerignore,
    dockerfile_no_baked_secrets,
    dockerfile_non_root,
    dockerfile_start_command,
)
from deploy_agent.scanner.docker_parser import (
    ImageKind,
    logical_lines,
    looks_like_secret_name,
    parse_dockerfile,
)

GOOD = """\
FROM node:20-alpine AS build
COPY . .
RUN npm ci && npm run build
FROM node:20-alpine
COPY --from=build /app /app
USER node
CMD ["node", "/app/server.js"]
"""


class TestParserAdditions:
    def test_line_numbers_survive_continuations(self) -> None:
        assert list(logical_lines("A \\\n  b\nC\n")) == [(1, "A    b"), (3, "C")]

    def test_stage_reference_and_scratch_are_not_external(self) -> None:
        info = parse_dockerfile("FROM node:20 AS build\nFROM build\nFROM scratch\nFROM ${B}\n")
        kinds = [image.kind for image in info.base_images]
        assert kinds == [ImageKind.EXTERNAL, ImageKind.STAGE, ImageKind.SCRATCH, ImageKind.VARIABLE]

    def test_digest_counts_as_pinned(self) -> None:
        image = parse_dockerfile("FROM python@sha256:abc123\n").base_images[0]
        assert image.has_digest

    def test_user_resets_each_stage(self) -> None:
        info = parse_dockerfile("FROM a:1\nUSER app\nFROM b:1\n")
        assert info.final_user_is_root is None

    @pytest.mark.parametrize("user", ["root", "0", "root:root", "0:0"])
    def test_root_user_forms(self, user: str) -> None:
        assert parse_dockerfile(f"FROM a:1\nUSER {user}\n").final_user_is_root is True

    def test_secret_assignment_keeps_name_and_line_only(self) -> None:
        info = parse_dockerfile("FROM a:1\nENV MODE=prod API_TOKEN=fake-value-123\n")
        assert info.secret_assignments == (("API_TOKEN", 2),)
        assert "fake-value-123" not in repr(info.secret_assignments)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("ARG NPM_TOKEN\n", ()),  # no default value: supplied at build time
            ("ENV SECRET_KEY=\n", ()),  # empty
            ('ENV SECRET_KEY=""\n', ()),
            ("ENV SECRET_KEY_FILE=/run/secrets/key\n", ()),  # points at a secret
            ("ENV DB_PASSWORD hunter2-fake\n", (("DB_PASSWORD", 1),)),  # legacy form
            ("ARG GITHUB_TOKEN=fake\n", (("GITHUB_TOKEN", 1),)),
        ],
    )
    def test_secret_assignment_cases(
        self, text: str, expected: tuple[tuple[str, int], ...]
    ) -> None:
        assert parse_dockerfile(text).secret_assignments == expected

    @pytest.mark.parametrize(
        ("name", "expected"),
        [("STRIPE_API_KEY", True), ("KEY", True), ("MONKEY", False), ("APP_MODE", False)],
    )
    def test_secret_names(self, name: str, expected: bool) -> None:
        assert looks_like_secret_name(name) is expected

    @pytest.mark.parametrize(
        ("line", "expected"),
        [("COPY . .", True), ("COPY ./ /app", True), ('COPY [".", "/app"]', True),
         ("COPY --chown=app . /app", True), ("COPY src /app", False),
         ("COPY --from=build . /app", False)],
    )
    def test_copies_whole_context(self, line: str, expected: bool) -> None:
        assert parse_dockerfile(f"FROM a:1\n{line}\n").copies_whole_context is expected

    def test_healthcheck_path(self) -> None:
        text = "HEALTHCHECK --interval=30s CMD wget -qO- http://127.0.0.1:8000/healthz\n"
        assert parse_dockerfile(text).healthcheck_path == "/healthz"


def dockerfile(make_context, text: str, **extra: str):  # type: ignore[no-untyped-def]
    return make_context({"Dockerfile": text, **extra})


class TestBaseImage:
    def test_passes_with_tags_and_stage_references(self, make_context) -> None:
        assert dockerfile_base_image(dockerfile(make_context, GOOD)).passed

    @pytest.mark.parametrize("line", ["FROM python", "FROM node:latest", "FROM ghcr.io/x/app"])
    def test_fails_for_untagged_or_latest(self, make_context, line: str) -> None:
        result = dockerfile_base_image(dockerfile(make_context, f"{line}\n"))

        assert not result.passed
        assert result.severity == Severity.WARNING
        assert "line 1" in (result.evidence or "")

    def test_fails_without_from(self, make_context) -> None:
        result = dockerfile_base_image(dockerfile(make_context, "RUN echo hi\n"))
        assert not result.passed and result.severity == Severity.ERROR

    def test_skips_without_dockerfile(self, make_context) -> None:
        result = dockerfile_base_image(make_context({"app.py": ""}))
        assert result.passed and (result.evidence or "").startswith("Skipped")


class TestStartCommand:
    def test_passes_with_cmd(self, make_context) -> None:
        assert dockerfile_start_command(dockerfile(make_context, GOOD)).passed

    def test_fails_without_cmd(self, make_context) -> None:
        result = dockerfile_start_command(dockerfile(make_context, "FROM node:20\n"))
        assert not result.passed and result.severity == Severity.WARNING


class TestNonRoot:
    def test_passes_with_user(self, make_context) -> None:
        assert dockerfile_non_root(dockerfile(make_context, GOOD)).passed

    def test_fails_without_user(self, make_context) -> None:
        result = dockerfile_non_root(dockerfile(make_context, "FROM node:20\nCMD x\n"))
        assert not result.passed and "no USER line" in (result.evidence or "")

    def test_fails_with_explicit_root(self, make_context) -> None:
        result = dockerfile_non_root(dockerfile(make_context, "FROM node:20\nUSER root\n"))
        assert not result.passed and "root user" in (result.evidence or "")


class TestNoBakedSecrets:
    def test_passes_without_secret_values(self, make_context) -> None:
        text = "FROM node:20\nENV NODE_ENV=production\nARG NPM_TOKEN\n"
        assert dockerfile_no_baked_secrets(dockerfile(make_context, text)).passed

    def test_fails_naming_variable_but_not_value(self, make_context) -> None:
        text = "FROM node:20\nENV NODE_ENV=production \\\n    STRIPE_SECRET=sk_fake_abc123\n"
        result = dockerfile_no_baked_secrets(dockerfile(make_context, text))

        assert not result.passed
        assert result.severity == Severity.ERROR
        assert "STRIPE_SECRET (line 2)" in (result.evidence or "")
        assert "sk_fake_abc123" not in result.model_dump_json()


class TestDockerignore:
    def test_passes_with_dockerignore(self, make_context) -> None:
        context = dockerfile(make_context, GOOD, **{".dockerignore": ".env\n"})
        assert dockerfile_dockerignore(context).passed

    def test_passes_when_not_copying_everything(self, make_context) -> None:
        text = "FROM node:20\nCOPY src /app\n"
        assert dockerfile_dockerignore(dockerfile(make_context, text)).passed

    def test_fails_copying_everything_without_dockerignore(self, make_context) -> None:
        result = dockerfile_dockerignore(dockerfile(make_context, GOOD))
        assert not result.passed and result.severity == Severity.WARNING
