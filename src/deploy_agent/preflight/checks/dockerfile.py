"""Dockerfile problems that are easy to spot without building the image."""

from deploy_agent.models.common import Severity
from deploy_agent.models.preflight import PreflightResult
from deploy_agent.preflight.context import PreflightContext
from deploy_agent.preflight.evidence import failed, listing, passed, skipped
from deploy_agent.scanner.docker_parser import BaseImage, ImageKind

NO_DOCKERFILE = "no Dockerfile in the project folder."


def _describe(image: BaseImage) -> str:
    return f"line {image.line} ({image.name or 'an image'})"


def dockerfile_base_image(context: PreflightContext) -> PreflightResult:
    name = "dockerfile_base_image"
    if not context.has_dockerfile:
        return skipped(name, NO_DOCKERFILE)
    images = context.docker.base_images
    if not images:
        return failed(
            name,
            Severity.ERROR,
            "The Dockerfile has no valid FROM line, so it cannot be built.",
            "Start the Dockerfile with a base image, for example `FROM python:3.12-slim`.",
        )

    external = [image for image in images if image.kind == ImageKind.EXTERNAL]
    loose = [image for image in external if not image.has_digest and image.tag in {"", "latest"}]
    if loose:
        return failed(
            name,
            Severity.WARNING,
            "Base image has no version tag or uses :latest at "
            f"{listing(_describe(image) for image in loose)}. It can change under you "
            "between builds.",
            "Pin a version tag, for example `python:3.12-slim` or `node:20-alpine`.",
        )
    return passed(name)


def dockerfile_start_command(context: PreflightContext) -> PreflightResult:
    name = "dockerfile_start_command"
    if not context.has_dockerfile:
        return skipped(name, NO_DOCKERFILE)
    if context.docker.has_start_command:
        return passed(name)
    return failed(
        name,
        Severity.WARNING,
        "The Dockerfile has no CMD or ENTRYPOINT line.",
        "Add a CMD that starts your app, for example "
        '`CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]`. Ignore this if the base '
        "image already starts your app.",
    )


def dockerfile_non_root(context: PreflightContext) -> PreflightResult:
    name = "dockerfile_non_root"
    if not context.has_dockerfile:
        return skipped(name, NO_DOCKERFILE)
    is_root = context.docker.final_user_is_root
    if is_root is False:
        return passed(name)
    evidence = (
        "The final stage switches to the root user."
        if is_root
        else "The final stage has no USER line, so the app runs as root by default."
    )
    return failed(
        name,
        Severity.WARNING,
        evidence,
        "Create a normal user and switch to it before CMD, for example "
        "`RUN useradd --create-home app` then `USER app`.",
    )


def dockerfile_no_baked_secrets(context: PreflightContext) -> PreflightResult:
    name = "dockerfile_no_baked_secrets"
    if not context.has_dockerfile:
        return skipped(name, NO_DOCKERFILE)
    found = context.docker.secret_assignments
    if not found:
        return passed(name)
    # Names and line numbers only. The values were dropped by the parser.
    return failed(
        name,
        Severity.ERROR,
        "ENV or ARG gives a value to a secret-looking name: "
        f"{listing(f'{var} (line {line})' for var, line in found)}. Values set this way are "
        "stored in the image and visible to anyone who can pull it.",
        "Remove the value from the Dockerfile and set the variable on the deploy target at "
        "run time, or use a build secret (`RUN --mount=type=secret`). If a real secret was "
        "committed, treat it as leaked and rotate it.",
    )


def dockerfile_dockerignore(context: PreflightContext) -> PreflightResult:
    name = "dockerfile_dockerignore"
    if not context.has_dockerfile:
        return skipped(name, NO_DOCKERFILE)
    if not context.docker.copies_whole_context or ".dockerignore" in context.root_files():
        return passed(name)
    return failed(
        name,
        Severity.WARNING,
        "The Dockerfile copies the whole folder (COPY . or ADD .) and there is no "
        ".dockerignore file.",
        "Add a .dockerignore listing at least .env, .git, node_modules and virtualenv "
        "folders, so local secrets and junk do not end up in the image.",
    )
