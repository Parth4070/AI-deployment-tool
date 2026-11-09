"""Tests for the risky-migration check."""

import pytest

from deploy_agent.models import Severity
from deploy_agent.preflight.checks.migrations import (
    is_migration_file,
    risky_migrations,
    risky_operations,
)

SAFE_ALEMBIC = '''\
def upgrade():
    op.create_table("users", sa.Column("id", sa.Integer()))
    op.add_column("users", sa.Column("email", sa.String()))


def downgrade():
    op.drop_column("users", "email")
    op.drop_table("users")
'''

RISKY_ALEMBIC = '''\
def upgrade():
    op.drop_column("users", "legacy_flag")
    op.alter_column("users", "age",
                    type_=sa.BigInteger())


def downgrade():
    pass
'''


class TestRiskyOperations:
    @pytest.mark.parametrize(
        ("text", "label"),
        [
            ("DROP TABLE users;", "DROP TABLE"),
            ('ALTER TABLE "User" DROP COLUMN "name";', "DROP COLUMN"),
            ("truncate audit_log;", "TRUNCATE"),
            ("ALTER TABLE a RENAME COLUMN b TO c;", "RENAME"),
            ("ALTER TABLE a ALTER COLUMN b SET DATA TYPE bigint;", "column type change"),
            ("ALTER TABLE a ALTER COLUMN b SET NOT NULL;", "SET NOT NULL"),
            ("DELETE FROM sessions;", "DELETE without WHERE"),
        ],
    )
    def test_sql(self, text: str, label: str) -> None:
        assert label in risky_operations(text, ".sql")

    def test_delete_with_where_is_fine(self) -> None:
        assert risky_operations("DELETE FROM sessions WHERE expired = true;", ".sql") == []

    def test_sql_comments_are_ignored(self) -> None:
        text = "-- DROP TABLE users;\n/* TRUNCATE x; */\nCREATE TABLE y (id int);"
        assert risky_operations(text, ".sql") == []

    def test_alembic_downgrade_is_ignored(self) -> None:
        assert risky_operations(SAFE_ALEMBIC, ".py") == []

    def test_alembic_upgrade_is_flagged(self) -> None:
        labels = risky_operations(RISKY_ALEMBIC, ".py")
        assert "Alembic drop/rename" in labels
        assert "Alembic alter_column type/rename" in labels

    def test_django(self) -> None:
        text = "operations = [migrations.RemoveField(model_name='user', name='age')]"
        assert risky_operations(text, ".py") == ["Django remove/rename/alter"]

    def test_knex_down_is_ignored(self) -> None:
        text = (
            "exports.up = (knex) => knex.schema.createTable('a', t => t.increments());\n"
            "exports.down = (knex) => knex.schema.dropTable('a');\n"
        )
        assert risky_operations(text, ".js") == []

    def test_knex_up_drop_is_flagged(self) -> None:
        text = "export async function up(knex) { await knex.schema.dropTable('a'); }\n"
        assert risky_operations(text, ".ts") == ["Knex drop/rename"]

    def test_dbmate_down_marker(self) -> None:
        text = "-- migrate:up\nCREATE TABLE a (id int);\n-- migrate:down\nDROP TABLE a;\n"
        assert risky_operations(text, ".sql") == []


class TestIsMigrationFile:
    @pytest.mark.parametrize(
        ("path", "tool", "expected"),
        [
            ("prisma/migrations/20240101_init/migration.sql", "prisma", True),
            ("app/migrations/0002_auto.py", "django", True),
            ("app/migrations/__init__.py", "django", False),
            ("alembic/versions/abc_add.py", "alembic", True),
            ("src/versions/x.py", None, False),
            ("db/migrations/001.down.sql", None, False),
            ("src/server.ts", "prisma", False),
        ],
    )
    def test_paths(self, path: str, tool: str | None, expected: bool) -> None:
        assert is_migration_file(path, tool) is expected


PRISMA_PACKAGE = '{"name": "x", "dependencies": {"@prisma/client": "^5"}}'


class TestRiskyMigrationsCheck:
    def test_passes_for_safe_migrations(self, make_context) -> None:
        context = make_context(
            {
                "package.json": PRISMA_PACKAGE,
                "prisma/migrations/1_init/migration.sql": 'CREATE TABLE "User" (id int);',
            }
        )
        result = risky_migrations(context)

        assert result.passed
        assert "Checked 1 migration file" in (result.evidence or "")

    def test_flags_destructive_sql_with_path_and_label(self, make_context) -> None:
        context = make_context(
            {
                "package.json": PRISMA_PACKAGE,
                "prisma/migrations/1_init/migration.sql": 'CREATE TABLE "User" (id int);',
                "prisma/migrations/2_drop/migration.sql": 'ALTER TABLE "User" DROP COLUMN "x";',
            }
        )
        result = risky_migrations(context)

        assert not result.passed
        assert result.severity == Severity.WARNING
        assert "prisma/migrations/2_drop/migration.sql (DROP COLUMN)" in (result.evidence or "")
        assert "1_init" not in (result.evidence or "")
        assert "manual" in (result.evidence or "")

    def test_flags_alembic_upgrade(self, make_context) -> None:
        context = make_context(
            {
                "pyproject.toml": '[project]\nname = "x"\ndependencies = ["alembic"]\n',
                "alembic/versions/a1_drop.py": RISKY_ALEMBIC,
                "alembic/versions/a0_init.py": SAFE_ALEMBIC,
            }
        )
        result = risky_migrations(context)

        assert not result.passed
        assert "alembic/versions/a1_drop.py" in (result.evidence or "")
        assert "a0_init" not in (result.evidence or "")

    def test_skips_without_migrations(self, make_context) -> None:
        result = risky_migrations(make_context({"package.json": "{}"}))
        assert result.passed and (result.evidence or "").startswith("Skipped")

    def test_sql_outside_migration_folders_is_not_read(self, make_context) -> None:
        context = make_context({"package.json": "{}", "seed/data.sql": "DROP TABLE x;"})
        assert "seed/data.sql" not in context.snapshot.texts
