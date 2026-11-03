"""Do the project's files, and the deploy target, agree on the runtime version?"""

import re

from deploy_agent.models.common import Severity
from deploy_agent.models.preflight import PreflightResult
from deploy_agent.preflight.context import PreflightContext
from deploy_agent.preflight.evidence import failed, listing, passed, skipped

_PIN = re.compile(r"\d+(?:\.\d+)*")
_CLAUSE = re.compile(r"(>=|<=|==|!=|>|<)(\d+(?:\.\d+)*)")


def _parts(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def is_pin(version: str) -> bool:
    """An exact version like 3.12 or 20.11.1, as opposed to a range like >=3.12."""
    return _PIN.fullmatch(version) is not None


def pins_agree(first: str, second: str) -> bool:
    """Compare only as far as both go, so 3.12 agrees with 3.12.4."""
    return all(a == b for a, b in zip(_parts(first), _parts(second), strict=False))


def _clause_holds(pin: tuple[int, ...], operator: str, bound: tuple[int, ...]) -> bool | None:
    shared = min(len(pin), len(bound))
    if operator in {"==", "!="}:
        same = pin[:shared] == bound[:shared]
        return same if operator == "==" else not same
    if pin[:shared] == bound[:shared] and len(pin) < len(bound):
        return None  # 3.12 against >=3.12.4: depends on the patch release, so do not judge
    width = max(len(pin), len(bound))
    left = pin + (0,) * (width - len(pin))
    right = bound + (0,) * (width - len(bound))
    return {">=": left >= right, ">": left > right, "<=": left <= right, "<": left < right}[
        operator
    ]


def satisfies(pin: str, version_range: str) -> bool | None:
    """Does the pin fall inside the range? None means "cannot tell", which is never a failure.

    Only plain comparisons (>=, >, <=, <, ==, !=) joined by commas are understood. Anything
    else, like ^20 or ~=3.12, returns None rather than a guess.
    """
    results: list[bool | None] = []
    for clause in version_range.split(","):
        match = _CLAUSE.fullmatch(clause)
        if match is None:
            return None
        results.append(_clause_holds(_parts(pin), match.group(1), _parts(match.group(2))))
    if False in results:
        return False
    return None if None in results else True


def _conflict(a_source: str, a: str, b_source: str, b: str) -> str | None:
    """Describe the disagreement between two versions, or return None if they fit."""
    if is_pin(a) and is_pin(b):
        return None if pins_agree(a, b) else f"{a_source} says {a} but {b_source} says {b}"
    if is_pin(a) and satisfies(a, b) is False:
        return f"{a_source} says {a}, which is outside {b_source} ({b})"
    if is_pin(b) and satisfies(b, a) is False:
        return f"{b_source} says {b}, which is outside {a_source} ({a})"
    return None


def runtime_version_mismatch(context: PreflightContext) -> PreflightResult:
    name = "runtime_version_mismatch"
    if context.project.language not in {"python", "node"}:
        return skipped(name, "no Python or Node project was found.")

    sources = list(context.runtime_sources)
    if not sources:
        version_file = ".python-version" if context.project.language == "python" else ".nvmrc"
        return failed(
            name,
            Severity.WARNING,
            "No runtime version is declared in any project file.",
            f"Pin the version you test with, for example in a {version_file} file, so the "
            "deploy uses the same one.",
        )

    target = context.target.runtime_version
    if target is not None:
        sources.append(("the deploy target", target))

    problems: list[str] = []
    for index, (a_source, a) in enumerate(sources):
        for b_source, b in sources[index + 1 :]:
            problem = _conflict(a_source, a, b_source, b)
            if problem:
                problems.append(problem)

    if problems:
        return failed(
            name,
            Severity.ERROR,
            "Runtime versions disagree: " + listing(problems) + ".",
            "Choose one version and use it everywhere: version files, the manifest, the "
            "Dockerfile base image and the deploy target.",
        )
    return passed(name, "Versions agree: " + listing(f"{s} {v}" for s, v in sources) + ".")
