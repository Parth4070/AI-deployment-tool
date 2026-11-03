"""Are dependencies locked, so the deploy installs the same versions you tested?"""

from deploy_agent.models.common import Severity
from deploy_agent.models.preflight import PreflightResult
from deploy_agent.preflight.context import PreflightContext
from deploy_agent.preflight.evidence import failed, passed, skipped

NODE_LOCKFILES = frozenset(
    {
        "bun.lock",
        "bun.lockb",
        "npm-shrinkwrap.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
)
PYTHON_LOCKFILES = frozenset({"Pipfile.lock", "pdm.lock", "poetry.lock", "uv.lock"})


def count_unpinned(requirements_text: str) -> tuple[int, int]:
    """Return (unpinned, total) requirement lines. Only counts leave this function.

    A line is pinned if it uses == or a direct reference (@). Option lines such as -r or
    --hash are not requirements and are ignored.
    """
    unpinned = total = 0
    for raw in requirements_text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith(("#", "-")):
            continue
        total += 1
        if "==" not in line and "@" not in line:
            unpinned += 1
    return unpinned, total


def lockfile_present(context: PreflightContext) -> PreflightResult:
    name = "lockfile_present"
    files = context.root_files()
    has_python_lock = not PYTHON_LOCKFILES.isdisjoint(files)
    problems: list[str] = []

    requirements_ok = False
    if "requirements.txt" in files:
        unpinned, total = count_unpinned(context.snapshot.texts.get("requirements.txt", ""))
        requirements_ok = unpinned == 0
        if unpinned and not has_python_lock:
            problems.append(f"{unpinned} of {total} lines in requirements.txt are not pinned")

    if "package.json" in files and NODE_LOCKFILES.isdisjoint(files):
        problems.append("package.json has no lockfile next to it")
    if "Pipfile" in files and "Pipfile.lock" not in files:
        problems.append("Pipfile has no Pipfile.lock")
    elif "pyproject.toml" in files and not (has_python_lock or requirements_ok):
        problems.append("pyproject.toml has no lockfile (uv.lock, poetry.lock or pdm.lock)")

    if not ({"package.json", "Pipfile", "pyproject.toml", "requirements.txt"} & files):
        return skipped(name, "no dependency manifest was found.")
    if problems:
        return failed(
            name,
            Severity.WARNING,
            "; ".join(problems) + ".",
            "Generate a lockfile with your package manager (for example `npm install`, "
            "`uv lock` or `poetry lock`) and commit it, or pin every requirement with ==.",
        )
    return passed(name)
