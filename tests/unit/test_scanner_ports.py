"""Tests for finding the ports an app seems to use."""

import pytest

from deploy_agent.scanner.ports import (
    clean_ports,
    ports_from_command,
    ports_from_javascript,
    ports_from_python,
)
from deploy_agent.scanner.source import parse_javascript, parse_python


class TestCommands:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("uvicorn main:app --port 8000", [8000]),
            ("uvicorn main:app --port=8001", [8001]),
            ("gunicorn app:app --bind 0.0.0.0:8002", [8002]),
            ("gunicorn app:app -b :8003", [8003]),
            ("next dev -p 4000", [4000]),
            ("python manage.py runserver 0.0.0.0:8004", [8004]),
            ("python manage.py runserver 8005", [8005]),
            ("PORT=3001 node server.js", [3001]),
            ('["uvicorn", "main:app", "--port", "8006"]', [8006]),
        ],
    )
    def test_port_forms(self, command: str, expected: list[int]) -> None:
        assert ports_from_command(command) == expected

    @pytest.mark.parametrize(
        "command",
        ["node server.js", "uvicorn main:app --port $PORT", "tsc -p tsconfig.json", "echo 8000"],
    )
    def test_commands_with_no_port(self, command: str) -> None:
        assert ports_from_command(command) == []


class TestPython:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("app.run(port=5000)", [5000]),
            ('app.run(host="0.0.0.0", port=5001)', [5001]),
            ("uvicorn.run(app, port=8000)", [8000]),
            ('port = int(os.environ.get("PORT", 5002))', [5002]),
            ('port = int(os.getenv("PORT", "5003"))', [5003]),
            ("PORT = 5004", [5004]),
            ("APP_PORT = 5005", [5005]),
        ],
    )
    def test_port_forms(self, code: str, expected: list[int]) -> None:
        assert ports_from_python(parse_python(code)) == expected

    @pytest.mark.parametrize(
        "code",
        [
            "DB_PORT = 5432",
            'os.getenv("DB_PORT", 5432)',
            "connect(port=5432)",
            'os.getenv("PORT")',
            "app.run(port=chosen)",
        ],
    )
    def test_other_numbers_are_ignored(self, code: str) -> None:
        assert ports_from_python(parse_python(code)) == []


class TestJavascript:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("app.listen(3000)", [3000]),
            ("server.listen({ port: 3001 })", [3001]),
            ("const port = process.env.PORT || 3002;", [3002]),
            ("const port = process.env.PORT ?? 3003;", [3003]),
            ('const port = process.env.PORT || "3004";', [3004]),
            ("app.listen(process.env.PORT || 3005)", [3005]),
            ("const PORT = 3006;", [3006]),
            ("const PORT: number = Number(process.env.PORT || 3007);", [3007]),
        ],
    )
    def test_port_forms(self, code: str, expected: list[int]) -> None:
        assert ports_from_javascript(parse_javascript(code)) == expected

    @pytest.mark.parametrize(
        "code",
        [
            "const DB_PORT = 5432;",
            "process.env.DB_PORT || 5432",
            "client.connect({ port: 5432 })",
            "app.listen(chosen)",
        ],
    )
    def test_other_numbers_are_ignored(self, code: str) -> None:
        assert ports_from_javascript(parse_javascript(code)) == []


class TestCleanPorts:
    def test_sorted_and_deduplicated(self) -> None:
        assert clean_ports([8000, 3000, 8000]) == (3000, 8000)

    @pytest.mark.parametrize("port", [0, 65536, 99999])
    def test_out_of_range_ports_are_dropped(self, port: int) -> None:
        assert clean_ports([port]) == ()
