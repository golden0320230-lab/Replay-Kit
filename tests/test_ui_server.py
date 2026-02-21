import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from replaypack.ui import UIServerConfig, start_ui_server


def _get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:  # noqa: S310 (local test server)
        return json.loads(response.read().decode("utf-8"))


def test_ui_server_smoke_and_core_render_path() -> None:
    config = UIServerConfig(host="127.0.0.1", port=0, base_dir=Path.cwd())

    with start_ui_server(config) as (server, _thread):
        host, port = server.server_address
        base_url = f"http://{host}:{port}"

        with urlopen(base_url + "/", timeout=5) as response:  # noqa: S310
            html = response.read().decode("utf-8")

        assert "<h1>ReplayKit Local Diff UI</h1>" in html
        assert "for=\"leftArtifact\"" in html
        assert "for=\"rightArtifact\"" in html

        files_payload = _get_json(base_url + "/api/files")
        assert "files" in files_payload
        assert any(item.endswith(".rpk") for item in files_payload["files"])

        left = quote("examples/runs/m2_capture_boundaries.rpk")
        right = quote("examples/runs/m4_diverged_from_m2.rpk")
        diff_payload = _get_json(base_url + f"/api/diff?left={left}&right={right}")

        assert diff_payload["first_divergence"]["index"] == 3
        assert diff_payload["summary"]["changed"] >= 1


def test_ui_server_empty_state_lists_no_files(tmp_path: Path) -> None:
    config = UIServerConfig(host="127.0.0.1", port=0, base_dir=tmp_path)

    with start_ui_server(config) as (server, _thread):
        host, port = server.server_address
        base_url = f"http://{host}:{port}"

        files_payload = _get_json(base_url + "/api/files")
        assert files_payload["files"] == []
