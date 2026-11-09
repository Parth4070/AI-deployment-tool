"""Fake secret values in a project must never reach the plan or its rendered output.

All values here are fake.
"""

from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from deploy_agent.cli.main import app
from deploy_agent.models import Environment, PlanTarget
from deploy_agent.planner import build_plan, render_plan
from deploy_agent.preflight import build_context, run_preflight

FAKE_SECRETS = (
    "fake-dotenv-secret-6161",
    "fake-dockerfile-secret-6262",
    "fake-source-default-6363",
    "fake-conn-password-6464",
)


def write_leaky_project(root: Path) -> None:
    files = {
        ".env": f"API_KEY={FAKE_SECRETS[0]}\n",
        "Dockerfile": (
            "FROM python:3.12-slim\n"
            f"ENV STRIPE_SECRET={FAKE_SECRETS[1]}\n"
            'CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]\n'
        ),
        "pyproject.toml": '[project]\nname = "leaky"\nrequires-python = ">=3.12"\n',
        "app.py": (
            "import os\n"
            f"KEY = os.environ.get('API_KEY', '{FAKE_SECRETS[2]}')\n"
            f"DB = os.getenv('DATABASE_URL', 'postgres://admin:{FAKE_SECRETS[3]}@db/app')\n"
        ),
        "alembic.ini": "[alembic]\nscript_location = alembic\n",
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def assert_no_secret(text: str) -> None:
    for secret in FAKE_SECRETS:
        assert secret not in text


def test_no_secret_in_plan_model_or_rendering(tmp_path: Path) -> None:
    write_leaky_project(tmp_path)
    context = build_context(tmp_path)

    plan = build_plan(
        context.project,
        run_preflight(context),
        PlanTarget(environment=Environment.PRODUCTION),
    )
    console = Console(width=200, record=True, color_system=None)
    console.print(render_plan(plan))

    assert_no_secret(plan.model_dump_json())
    assert_no_secret(repr(plan))
    assert_no_secret(console.export_text())


def test_no_secret_in_plan_command_output(tmp_path: Path) -> None:
    write_leaky_project(tmp_path)

    result = CliRunner().invoke(app, ["plan", str(tmp_path), "--environment", "production"])

    assert result.exit_code in (0, 1)
    assert_no_secret(result.output)


def test_env_step_names_variables_without_values(tmp_path: Path) -> None:
    write_leaky_project(tmp_path)
    context = build_context(tmp_path)

    plan = build_plan(context.project, run_preflight(context))

    env_step = next(step for step in plan.steps if step.kind == "set_target_env_names")
    assert "API_KEY" in env_step.what
    assert_no_secret(env_step.what)
