import json
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from replaypack.ui import UIServerConfig, start_ui_server


def _get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:  # noqa: S310 (local test server)
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    request = Request(  # noqa: S310 (local test server)
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.getcode(), json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8")
        return error.code, json.loads(body)


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
        assert "aria-label=\"Jump to first divergence\"" in html
        assert "aria-label=\"Show changed steps only\"" in html
        assert "aria-label=\"Previous changed field\"" in html
        assert "aria-label=\"Copy selected JSON path\"" in html
        assert "aria-label=\"Diff step list\"" in html
        assert "aria-label=\"Field-level change list\"" in html
        assert "function jumpToFirstDivergence()" in html
        assert "jumpButton.addEventListener(\"click\", jumpToFirstDivergence);" in html

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


def test_ui_server_rename_artifact_success_and_validation_errors(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "runs" / "manual"
    artifacts_dir.mkdir(parents=True)
    source = artifacts_dir / "capture.rpk"
    source.write_text("capture", encoding="utf-8")
    collision = artifacts_dir / "collision.rpk"
    collision.write_text("collision", encoding="utf-8")
    not_artifact = artifacts_dir / "notes.txt"
    not_artifact.write_text("notes", encoding="utf-8")

    config = UIServerConfig(host="127.0.0.1", port=0, base_dir=tmp_path)

    with start_ui_server(config) as (server, _thread):
        host, port = server.server_address
        base_url = f"http://{host}:{port}"

        status_code, payload = _post_json(
            base_url + "/api/fs/rename",
            {"path": "runs/manual/capture.rpk", "new_name": "renamed.rpk"},
        )
        assert status_code == 200
        assert payload["status"] == "ok"
        assert payload["old_path"] == "runs/manual/capture.rpk"
        assert payload["new_path"] == "runs/manual/renamed.rpk"
        assert not source.exists()
        assert (artifacts_dir / "renamed.rpk").exists()

        status_code, payload = _post_json(
            base_url + "/api/fs/rename",
            {"path": "runs/manual/renamed.rpk", "new_name": "collision.rpk"},
        )
        assert status_code == 400
        assert payload["status"] == "error"
        assert "Destination already exists" in payload["message"]

        status_code, payload = _post_json(
            base_url + "/api/fs/rename",
            {"path": "runs/manual/renamed.rpk", "new_name": "nested/invalid.rpk"},
        )
        assert status_code == 400
        assert payload["status"] == "error"
        assert "file name" in payload["message"]

        status_code, payload = _post_json(
            base_url + "/api/fs/rename",
            {"path": "runs/manual/notes.txt", "new_name": "still-not-artifact.txt"},
        )
        assert status_code == 400
        assert payload["status"] == "error"
        assert "Only .rpk and .bundle files" in payload["message"]
