"""Shared test helpers."""

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from deploy_agent.models import DeploymentTarget
from deploy_agent.preflight import PreflightContext, build_context

MakeContext = Callable[..., PreflightContext]


@pytest.fixture
def make_context(tmp_path: Path) -> MakeContext:
    """Write a small project to a temp folder and build a real preflight context from it.

    Usage: ``make_context({"Dockerfile": "FROM python:3.12\\n"}, port=8000)``.
    Keyword arguments become DeploymentTarget fields.
    """

    def build(files: Mapping[str, str], **target: object) -> PreflightContext:
        for relative, text in files.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return build_context(tmp_path, DeploymentTarget.model_validate(target))

    return build
