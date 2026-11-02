"""Honest record of what the scanner does NOT find.

Each test states the behavior we might want and is marked as an expected failure.
``strict=True`` turns a fixed gap into a failure, which is the prompt to remove the case.

These gaps can only make the scan incomplete. None of them can put a secret value in the
result. Preflight checks that use this data must not treat "not found" as "not needed".
"""

from pathlib import Path

import pytest

from deploy_agent.scanner import scan_project


def scan_source(tmp_path: Path, name: str, code: str, manifest: str = "requirements.txt"):  # type: ignore[no-untyped-def]
    (tmp_path / manifest).write_text("{}" if manifest == "package.json" else "", encoding="utf-8")
    (tmp_path / name).write_text(code, encoding="utf-8")
    return scan_project(tmp_path).project


@pytest.mark.xfail(strict=True, reason="Only direct, literal reads are recognised")
@pytest.mark.parametrize(
    "code",
    [
        'import os\nname = "HIDDEN"\nos.getenv(name)\n',
        'import os as system\nsystem.getenv("HIDDEN")\n',
        'import os\nvalues = os.environ\nvalues["HIDDEN"]\n',
        'from decouple import config\nconfig("HIDDEN")\n',
        "class Settings(BaseSettings):\n    hidden: str\n",
    ],
    ids=[
        "name-in-variable",
        "module-alias",
        "environ-alias",
        "config-library",
        "pydantic-settings",
    ],
)
def test_indirect_python_read(tmp_path: Path, code: str) -> None:
    project = scan_source(tmp_path, "app.py", code)

    assert {"HIDDEN", "hidden"} & set(project.env_var_names)


@pytest.mark.xfail(strict=True, reason="Only direct, literal reads are recognised")
@pytest.mark.parametrize(
    "code",
    [
        "const name = 'HIDDEN';\nprocess.env[name];\n",
        "const env = process.env;\nenv.HIDDEN;\n",
    ],
    ids=["name-in-variable", "env-alias"],
)
def test_indirect_javascript_read(tmp_path: Path, code: str) -> None:
    project = scan_source(tmp_path, "app.js", code, manifest="package.json")

    assert "HIDDEN" in project.env_var_names


@pytest.mark.xfail(strict=True, reason="Deliberate: private .env files are never opened")
def test_name_that_exists_only_in_a_private_env_file(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text("HIDDEN=fake\n", encoding="utf-8")

    assert "HIDDEN" in scan_project(tmp_path).project.env_var_names


@pytest.mark.xfail(strict=True, reason="docker-compose.yml is not read")
def test_port_set_in_docker_compose(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(
        'services:\n  web:\n    ports:\n      - "9000:9000"\n', encoding="utf-8"
    )

    assert 9000 in scan_project(tmp_path).project.ports


@pytest.mark.xfail(strict=True, reason="Framework default ports are not assumed")
def test_framework_default_port(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies":{"next":"15"}}', encoding="utf-8")

    assert 3000 in scan_project(tmp_path).project.ports


@pytest.mark.xfail(strict=True, reason="Only the project root is treated as a project")
def test_project_inside_a_subfolder(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text("{}", encoding="utf-8")

    assert scan_project(tmp_path).project.language == "node"
