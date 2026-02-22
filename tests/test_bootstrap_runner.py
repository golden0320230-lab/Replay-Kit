import os
from pathlib import Path
import subprocess
import sys

from replaypack.artifact import read_artifact


def _run_bootstrap(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "replaykit.bootstrap", *args],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=env,
        check=False,
    )


def test_bootstrap_runs_script_and_writes_artifact(tmp_path: Path) -> None:
    script_path = tmp_path / "script_target.py"
    script_path.write_text(
        "\n".join(
            [
                "import json",
                "import threading",
                "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer",
                "import httpx",
                "import requests",
                "",
                "class Handler(BaseHTTPRequestHandler):",
                "    def do_GET(self):",
                "        self.send_response(200)",
                "        self.send_header('Content-Type', 'application/json')",
                "        self.end_headers()",
                "        self.wfile.write(json.dumps({'ok': True, 'path': self.path}).encode('utf-8'))",
                "",
                "    def log_message(self, fmt, *args):",
                "        return",
                "",
                "server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)",
                "thread = threading.Thread(target=server.serve_forever, daemon=True)",
                "thread.start()",
                "host, port = server.server_address",
                "base_url = f'http://{host}:{port}'",
                "try:",
                "    requests.get(f'{base_url}/requests', timeout=5)",
                "    httpx.get(f'{base_url}/httpx', timeout=5)",
                "finally:",
                "    server.shutdown()",
                "    server.server_close()",
                "    thread.join(timeout=2)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "script.rpk"

    result = _run_bootstrap(["--out", str(out_path), "--", str(script_path)])

    assert result.returncode == 0, result.stderr
    assert out_path.exists()
    run = read_artifact(out_path)
    assert len(run.steps) >= 2
    assert {step.type for step in run.steps}.issuperset({"tool.request", "tool.response"})


def test_bootstrap_runs_module_mode(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "samplepkg"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")

    output_flag = tmp_path / "module-executed.txt"
    (pkg_dir / "entry.py").write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "",
                "Path(sys.argv[1]).write_text('ok', encoding='utf-8')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    out_path = tmp_path / "module.rpk"
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        f"{tmp_path}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    )
    result = _run_bootstrap(
        [
            "--out",
            str(out_path),
            "--",
            "-m",
            "samplepkg.entry",
            str(output_flag),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert out_path.exists()
    assert output_flag.read_text(encoding="utf-8") == "ok"


def test_bootstrap_forwards_target_exit_code(tmp_path: Path) -> None:
    script_path = tmp_path / "exit_7.py"
    script_path.write_text("raise SystemExit(7)\n", encoding="utf-8")
    out_path = tmp_path / "exit.rpk"

    result = _run_bootstrap(["--out", str(out_path), "--", str(script_path)])

    assert result.returncode == 7
    assert out_path.exists()
