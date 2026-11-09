"""Tests for the env-var, port, listen-address and health-check checks."""

import pytest

from deploy_agent.models import Severity
from deploy_agent.preflight.checks.env_vars import env_vars_provided
from deploy_agent.preflight.checks.network import (
    binds_localhost,
    health_check_path,
    listen_address,
    port_consistent,
)

APP = {
    "package.json": '{"name": "x", "dependencies": {"express": "^4"}}',
    "server.js": (
        'const app = require("express")();\n'
        "const key = process.env.API_KEY;\n"
        "const db = process.env.DATABASE_URL;\n"
        'app.get("/healthz", (req, res) => res.send("ok"));\n'
        "app.listen(3000);\n"
    ),
}


class TestEnvVarsProvided:
    def test_passes_when_all_names_provided(self, make_context) -> None:
        context = make_context(APP, provided_env_names=("API_KEY", "DATABASE_URL", "EXTRA"))
        assert env_vars_provided(context).passed

    def test_fails_listing_missing_names(self, make_context) -> None:
        result = env_vars_provided(make_context(APP, provided_env_names=("API_KEY",)))

        assert not result.passed
        assert result.severity == Severity.WARNING
        assert "DATABASE_URL" in (result.evidence or "")
        assert "API_KEY" not in (result.evidence or "")

    def test_empty_tuple_means_nothing_provided(self, make_context) -> None:
        result = env_vars_provided(make_context(APP, provided_env_names=()))
        assert not result.passed and "2 variable(s)" in (result.evidence or "")

    def test_skips_when_target_names_unknown(self, make_context) -> None:
        result = env_vars_provided(make_context(APP))
        assert result.passed and (result.evidence or "").startswith("Skipped")


class TestPortConsistent:
    def test_passes_when_target_matches(self, make_context) -> None:
        assert port_consistent(make_context(APP, port=3000)).passed

    def test_fails_when_target_differs(self, make_context) -> None:
        result = port_consistent(make_context(APP, port=8080))

        assert not result.passed
        assert result.severity == Severity.ERROR
        assert "3000" in (result.evidence or "") and "8080" in (result.evidence or "")

    def test_warns_on_several_ports(self, make_context) -> None:
        files = {**APP, "Dockerfile": "FROM node:20\nEXPOSE 8000\n"}
        result = port_consistent(make_context(files))

        assert not result.passed
        assert result.severity == Severity.WARNING
        assert "3000, 8000" in (result.evidence or "")

    def test_skips_with_no_port_anywhere(self, make_context) -> None:
        assert port_consistent(make_context({"package.json": "{}"})).passed


class TestListenAddress:
    @pytest.mark.parametrize(
        "command",
        [
            "uvicorn app:app --host 127.0.0.1",
            '["gunicorn", "-b", "localhost:8000", "app:app"]',
            "next start -H localhost",
            "HOST=127.0.0.1 node server.js",
        ],
    )
    def test_detects_local_binds(self, command: str) -> None:
        assert binds_localhost(command)

    @pytest.mark.parametrize(
        "command", ["uvicorn app:app --host 0.0.0.0", "node server.js", "--host localhost.dev"]
    )
    def test_ignores_public_binds(self, command: str) -> None:
        assert not binds_localhost(command)

    def test_passes_with_public_bind(self, make_context) -> None:
        dockerfile = 'FROM python:3.12\nCMD ["uvicorn", "app:app", "--host", "0.0.0.0"]\n'
        assert listen_address(make_context({"Dockerfile": dockerfile})).passed

    def test_fails_with_local_bind_without_quoting_command(self, make_context) -> None:
        dockerfile = "FROM python:3.12\nCMD uvicorn app:app --host 127.0.0.1 --fake-flag-xyz\n"
        result = listen_address(make_context({"Dockerfile": dockerfile}))

        assert not result.passed
        assert result.severity == Severity.ERROR
        assert "Dockerfile" in (result.evidence or "")
        assert "fake-flag-xyz" not in result.model_dump_json()

    def test_skips_without_commands(self, make_context) -> None:
        assert listen_address(make_context({"app.py": "x = 1\n"})).passed


class TestHealthCheckPath:
    def test_passes_when_route_exists(self, make_context) -> None:
        assert health_check_path(make_context(APP, health_check_path="/healthz")).passed

    def test_finds_django_style_route(self, make_context) -> None:
        files = {"urls.py": 'urlpatterns = [path("health/", views.health)]\n'}
        assert health_check_path(make_context(files, health_check_path="/health")).passed

    def test_fails_when_route_missing(self, make_context) -> None:
        result = health_check_path(make_context(APP, health_check_path="/status"))

        assert not result.passed
        assert result.severity == Severity.WARNING
        assert "/status" in (result.evidence or "")

    def test_fails_for_malformed_path_without_echoing_it(self, make_context) -> None:
        result = health_check_path(make_context(APP, health_check_path="health?token=fake123"))

        assert not result.passed
        assert "fake123" not in result.model_dump_json()

    def test_reads_path_from_dockerfile_healthcheck(self, make_context) -> None:
        dockerfile = (
            "FROM node:20\nHEALTHCHECK CMD curl -f http://localhost:3000/missing || exit 1\n"
        )
        result = health_check_path(make_context({**APP, "Dockerfile": dockerfile}))

        assert not result.passed
        assert "Dockerfile HEALTHCHECK" in (result.evidence or "")

    def test_skips_without_path(self, make_context) -> None:
        assert health_check_path(make_context(APP)).passed
