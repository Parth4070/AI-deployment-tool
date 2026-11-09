"""Fake secrets placed all over a project must never appear in preflight output."""

from pathlib import Path

from typer.testing import CliRunner

from deploy_agent.cli.main import app
from deploy_agent.models import DeploymentTarget
from deploy_agent.preflight import build_context, run_preflight

FAKE_SECRETS = {
    "dockerfile_env": "fake-env-secret-1111",
    "dockerfile_legacy_env": "fake-legacy-secret-2222",
    "dockerfile_arg": "fake-arg-secret-3333",
    "requirements_url": "fake-req-token-4444",
    "migration_literal": "fake-sql-password-5555",
    "private_env_file": "fake-dotenv-secret-6666",
    "start_command": "fake-cmd-secret-7777",
    "healthcheck_url": "fake-health-token-8888",
}


def write_leaky_project(root: Path) -> None:
    s = FAKE_SECRETS
    files = {
        "Dockerfile": (
            "FROM python:latest\n"
            f"ENV MODE=prod STRIPE_SECRET={s['dockerfile_env']}\n"
            f"ENV DB_PASSWORD {s['dockerfile_legacy_env']}\n"
            f"ARG GITHUB_TOKEN={s['dockerfile_arg']}\n"
            "COPY . .\n"
            f"HEALTHCHECK CMD curl http://user:{s['healthcheck_url']}@localhost/missing\n"
            f"CMD uvicorn app:app --host 127.0.0.1 --api-key {s['start_command']}\n"
        ),
        "requirements.txt": (
            f"flask\nprivate-lib @ https://{s['requirements_url']}@example.invalid/x.whl\n"
        ),
        "app.py": "import os\nKEY = os.environ['API_KEY']\n",
        "migrations/0001.sql": (
            f"INSERT INTO users VALUES ('admin', '{s['migration_literal']}');\nDROP TABLE old;\n"
        ),
        ".env": f"API_KEY={s['private_env_file']}\n",
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_no_secret_in_report(tmp_path: Path) -> None:
    write_leaky_project(tmp_path)
    target = DeploymentTarget(
        runtime_version="3.12", port=9999, provided_env_names=(), health_check_path="/x"
    )
    output = run_preflight(build_context(tmp_path, target)).model_dump_json()

    for where, secret in FAKE_SECRETS.items():
        assert secret not in output, f"secret from {where} leaked into the report"


def test_the_checks_did_fire(tmp_path: Path) -> None:
    """Guard against a false pass: the leak test means nothing if nothing was reported."""
    write_leaky_project(tmp_path)
    report = run_preflight(build_context(tmp_path))
    failed = {result.check_name for result in report.failures}

    assert {"dockerfile_no_baked_secrets", "listen_address", "risky_migrations"} <= failed


def test_no_secret_in_cli_output(tmp_path: Path) -> None:
    write_leaky_project(tmp_path)
    result = CliRunner().invoke(app, ["preflight", str(tmp_path), "--port", "9999"])

    for where, secret in FAKE_SECRETS.items():
        assert secret not in result.output, f"secret from {where} leaked into CLI output"


def test_rejected_cli_input_is_not_echoed(tmp_path: Path) -> None:
    """Someone may type NAME=value by mistake. The value must not be printed back."""
    write_leaky_project(tmp_path)
    result = CliRunner().invoke(
        app, ["preflight", str(tmp_path), "--env-name", "API_KEY=fake-typed-value-9999"]
    )

    assert result.exit_code == 2
    assert "fake-typed-value-9999" not in result.output
    assert "--env-name" in result.output
