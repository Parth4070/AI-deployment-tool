"""Flags database migrations that can lose data or lock tables, for a person to review.

This never runs a migration and never connects to a database. Without a database it cannot
know which migrations are still pending, so it checks every migration in the repo.
Only the "up" direction is checked: rollback code is supposed to drop things.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from deploy_agent.models.common import Severity
from deploy_agent.models.preflight import PreflightResult
from deploy_agent.preflight.context import PreflightContext
from deploy_agent.preflight.evidence import failed, listing, passed, skipped
from deploy_agent.scanner.files import in_migration_folder

_I = re.IGNORECASE


@dataclass(frozen=True)
class Rule:
    label: str  # fixed text written here; this is all that reaches the evidence
    pattern: re.Pattern[str]


RULES: tuple[Rule, ...] = (
    Rule("DROP TABLE", re.compile(r"\bDROP\s+TABLE\b", _I)),
    Rule("DROP COLUMN", re.compile(r"\bDROP\s+COLUMN\b", _I)),
    Rule("DROP SCHEMA/DATABASE", re.compile(r"\bDROP\s+(?:SCHEMA|DATABASE)\b", _I)),
    Rule("TRUNCATE", re.compile(r"\bTRUNCATE\b", _I)),
    Rule("RENAME", re.compile(r"\bRENAME\s+(?:TO|COLUMN)\b", _I)),
    Rule(
        "column type change", re.compile(r"\bALTER\s+COLUMN\s+\S+\s+(?:SET\s+DATA\s+)?TYPE\b", _I)
    ),
    Rule("SET NOT NULL", re.compile(r"\bSET\s+NOT\s+NULL\b", _I)),
    Rule("Alembic drop/rename", re.compile(r"\bop\.(?:drop_table|drop_column|rename_table)\b")),
    Rule(
        "Alembic alter_column type/rename",
        re.compile(r"\bop\.alter_column\([^)]*\b(?:type_|new_column_name)\s*="),
    ),
    Rule(
        "Django remove/rename/alter",
        re.compile(
            r"\bmigrations\.(?:RemoveField|DeleteModel|RenameField|RenameModel|AlterField)\b"
        ),
    ),
    Rule(
        "Knex drop/rename",
        re.compile(r"\.(?:dropTable|dropTableIfExists|dropColumns?|renameColumn|renameTable)\s*\("),
    ),
    Rule("Knex column alter", re.compile(r"\.alter\(\s*\)")),
)
DELETE_WITHOUT_WHERE = "DELETE without WHERE"

# Where the rollback ("down") half of a file starts. Everything after it is ignored.
_DOWN_SECTION = re.compile(
    r"^\s*(?:async\s+)?def\s+downgrade\b"  # Alembic
    r"|(?:module\.)?exports\.down\b"  # Knex / Sequelize (CommonJS)
    r"|export\s+(?:async\s+)?(?:function|const)\s+down\b"  # Knex (ES modules)
    r"|^\s*(?:async\s+)?down\s*[:(]"  # object method: down(knex) { ... } or down: ...
    r"|^--\s*\+?migrate[: ]\s*down\b",  # dbmate / sql-migrate markers
    re.MULTILINE | _I,
)
_COMMENTS = {
    ".sql": re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL),
    ".py": re.compile(r"^\s*#[^\n]*", re.MULTILINE),
    "js": re.compile(r"^\s*//[^\n]*|/\*.*?\*/", re.MULTILINE | re.DOTALL),
}
_DELETE = re.compile(r"\bDELETE\s+FROM\b", _I)
_WHERE = re.compile(r"\bWHERE\b", _I)


def up_section(text: str) -> str:
    match = _DOWN_SECTION.search(text)
    return text[: match.start()] if match else text


def strip_comments(text: str, suffix: str) -> str:
    pattern = _COMMENTS.get(suffix) or _COMMENTS["js"]
    return pattern.sub(" ", text)


def risky_operations(text: str, suffix: str) -> list[str]:
    """Return the labels of risky operations in the "up" half of a migration file."""
    code = strip_comments(up_section(text), suffix)
    labels = [rule.label for rule in RULES if rule.pattern.search(code)]
    statements = code.split(";")
    if any(_DELETE.search(part) and not _WHERE.search(part) for part in statements):
        labels.append(DELETE_WITHOUT_WHERE)
    return labels


def is_migration_file(path: str, migration_tool: str | None) -> bool:
    file = Path(path)
    if file.name == "__init__.py" or ".down." in file.name:
        return False
    if in_migration_folder(path):
        return True
    return migration_tool == "alembic" and "versions" in file.parts[:-1]


def risky_migrations(context: PreflightContext) -> PreflightResult:
    name = "risky_migrations"
    tool = context.project.migration_tool
    files = sorted(path for path in context.snapshot.texts if is_migration_file(path, tool))
    if not files:
        return skipped(name, "no migration files were found.")

    flagged: list[str] = []
    for path in files:
        labels = risky_operations(context.snapshot.texts[path], Path(path).suffix.lower())
        if labels:
            flagged.append(f"{path} ({', '.join(labels)})")

    if not flagged:
        return passed(name, f"Checked {len(files)} migration file(s); none look destructive.")
    return failed(
        name,
        Severity.WARNING,
        f"{len(flagged)} migration file(s) need manual review: {listing(flagged)}.",
        "Review these by hand before deploying. Back up the database first, check that each "
        "change can be undone, and plan for table locks on large tables. deploy-agent will "
        "not run migrations for you.",
    )
