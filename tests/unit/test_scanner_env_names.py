"""Tests for finding environment variable names. Values must never be kept.

All secret-looking values in this file are fake.
"""

import pytest

from deploy_agent.models import ScanWarningCode
from deploy_agent.scanner.env_names import (
    clean_env_names,
    names_from_javascript,
    names_from_python,
    names_from_template,
)
from deploy_agent.scanner.source import parse_javascript, parse_python


def python_names(code: str) -> set[str]:
    return set(names_from_python(parse_python(code)))


def javascript_names(code: str) -> set[str]:
    return set(names_from_javascript(parse_javascript(code)))


class TestPython:
    @pytest.mark.parametrize(
        "code",
        [
            'os.getenv("NAME")',
            'os.getenv("NAME", "fallback")',
            'getenv("NAME")',
            'os.environ.get("NAME")',
            'environ.get("NAME")',
            'os.environ["NAME"]',
            'environ["NAME"]',
            "os.getenv('NAME')",
        ],
    )
    def test_ways_of_reading_a_variable(self, code: str) -> None:
        assert python_names(code) == {"NAME"}

    @pytest.mark.parametrize(
        "code",
        [
            '# os.getenv("NAME")',
            '"""os.getenv("NAME")"""',
            "os.getenv(name)",
            'os.getenv(prefix + "_NAME")',
            'os.getenv(f"{prefix}_NAME")',
            'other.getenv("NAME")',
            'settings["NAME"]',
        ],
    )
    def test_things_that_are_not_reads(self, code: str) -> None:
        assert python_names(code) == set()

    def test_default_value_is_not_kept(self) -> None:
        assert python_names('os.getenv("NAME", "fake-default-value")') == {"NAME"}

    def test_broken_file_still_gives_what_it_can(self) -> None:
        assert "GOOD" in python_names('x = os.environ["GOOD"]\ndef broken(:\n')


class TestJavascript:
    @pytest.mark.parametrize(
        "code",
        [
            "process.env.NAME",
            'process.env["NAME"]',
            "process.env?.NAME",
            "import.meta.env.NAME",
            "const { NAME } = process.env;",
            "const { NAME: other } = process.env;",
            'const { NAME = "fallback" } = process.env;',
        ],
    )
    def test_ways_of_reading_a_variable(self, code: str) -> None:
        assert javascript_names(code) == {"NAME"}

    @pytest.mark.parametrize(
        "code",
        [
            "// process.env.NAME",
            "/* process.env.NAME */",
            '"process.env.NAME"',
            "process.env[name]",
            "other.env.NAME",
            "const { NAME } = settings;",
        ],
    )
    def test_things_that_are_not_reads(self, code: str) -> None:
        assert javascript_names(code) == set()

    @pytest.mark.parametrize(
        "code",
        [
            "const a: string = process.env.NAME;",
            "const a = process.env.NAME as string;",
            "const a = process.env.NAME!;",
            "interface Env { a: string }\nprocess.env.NAME;",
        ],
    )
    def test_typescript_syntax_does_not_hide_a_read(self, code: str) -> None:
        assert "NAME" in javascript_names(code)

    def test_broken_file_still_gives_what_it_can(self) -> None:
        assert "GOOD" in javascript_names("const a = process.env.GOOD;\nfunction broken( {\n")


class TestTemplate:
    def test_names_are_kept_and_values_are_dropped(self) -> None:
        text = (
            "# comment\nDATABASE_URL=postgres://fake:fake-password@db/app\n\nexport REDIS_URL=x\n"
        )

        assert names_from_template(text) == ("DATABASE_URL", "REDIS_URL")

    def test_base64_line_ending_in_equals_is_not_a_name(self) -> None:
        assert names_from_template("Zm9vYmFyYmF6cXV4ZmFrZQ=\n") == ()

    def test_lines_inside_a_multi_line_value_are_skipped(self) -> None:
        text = 'KEY="-----BEGIN\nFAKEFAKEFAKEFAKE=\n-----END"\nNEXT=1\n'

        assert names_from_template(text) == ("KEY", "NEXT")

    def test_quoted_value_on_one_line_does_not_start_a_multi_line_value(self) -> None:
        assert names_from_template('A="one"\nB=two\n') == ("A", "B")

    @pytest.mark.parametrize("text", ["", "no equals sign\n", "=value\n", "1BAD=value\n"])
    def test_lines_that_are_not_assignments(self, text: str) -> None:
        assert names_from_template(text) == ()


class TestCleanEnvNames:
    @pytest.mark.parametrize(
        "name",
        [
            "DATABASE_URL",
            "SECRET_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "GITHUB_TOKEN",
            "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY",
            "NODE_ENV",
        ],
    )
    def test_ordinary_names_are_kept(self, name: str) -> None:
        assert clean_env_names([name]).names == (name,)

    def test_names_are_sorted_and_deduplicated(self) -> None:
        assert clean_env_names(["B", "A", "B"]).names == ("A", "B")

    @pytest.mark.parametrize("name", ["has space", "a=b", "", "1BAD", "x" * 200])
    def test_invalid_names_are_dropped_quietly(self, name: str) -> None:
        assert clean_env_names([name]) == clean_env_names([])

    @pytest.mark.parametrize(
        "secret",
        ["sk_live_" + "fake" * 6 + "1234", "ghp_" + "fQ7xK2mPz9Lw" * 3],
    )
    def test_secret_used_by_mistake_as_a_name_is_dropped(self, secret: str) -> None:
        cleaned = clean_env_names([secret])

        assert cleaned.names == ()
        assert cleaned.warnings[0].code is ScanWarningCode.SUSPICIOUS_ENV_NAME
        assert cleaned.warnings[0].path is None
