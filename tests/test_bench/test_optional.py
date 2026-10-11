"""Without deriva.bench (the deriva-cli and deriva-studio packages) the CLI and the studio still work."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from deriva.services import about

REPO_ROOT = Path(__file__).resolve().parents[2]
WITHOUT_BENCH = "import sys\nsys.modules['deriva.bench'] = None\n"


def run_without_bench(code: str) -> list[str]:
    result = subprocess.run([sys.executable, "-c", WITHOUT_BENCH + code], cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_this_environment_has_benchmarking():
    assert about.features() == {"benchmark": True}


def test_the_cli_prints_the_install_hint_and_exits_1():
    lines = run_without_bench(
        "from typer.testing import CliRunner\n"
        "from deriva.cli.cli import app\n"
        "result = CliRunner().invoke(app, ['benchmark', 'run', '--repos', 'x', '--models', 'm'])\n"
        "print(result.exit_code)\n"
        "print(result.output.strip())\n"
    )
    assert lines[0] == "1"
    assert "uv tool install --python 3.14 deriva-dev" in lines[1]


def test_the_studio_serves_no_benchmark_api_and_says_so(tmp_path):
    lines = run_without_bench(
        "from pathlib import Path\n"
        "from fastapi.testclient import TestClient\n"
        "from deriva.studio.app import create_app\n"
        "from deriva.studio.provider import SessionProvider\n"
        "from tests.test_studio.conftest import FakeSession\n"
        f"app = create_app(provider=SessionProvider(factory=lambda: FakeSession()), static_dir=None, runs_dir=Path(r'{tmp_path}'))\n"
        "client = TestClient(app)\n"
        "print(client.get('/api/status').json()['features'])\n"
        "print(client.get('/api/benchmarks').status_code)\n"
    )
    assert lines == ["{'benchmark': False}", "404"]


def test_a_broken_bench_package_is_an_error_not_a_missing_feature(monkeypatch, tmp_path):
    from deriva.studio.app import create_app
    from deriva.studio.provider import SessionProvider
    from tests.test_studio.conftest import FakeSession

    monkeypatch.setitem(sys.modules, "deriva.bench.router", None)

    with pytest.raises(ImportError):
        create_app(provider=SessionProvider(factory=lambda: FakeSession()), static_dir=None, runs_dir=tmp_path)
