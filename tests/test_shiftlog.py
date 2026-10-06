"""Shift log persistence and the local desk API."""

import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.serve import serve
from src.shiftlog import add_page, get_page, list_pages, update_page
from src.triage import build_card


def _card(text="payments-db-01 in prod is out of disk space"):
    return build_card(
        text,
        retrieve_fn=lambda _query, _filters: [],
        answer_fn=lambda _query, _hits: "",
    ).to_dict()


def test_pages_round_trip_status_and_checks(tmp_path):
    path = tmp_path / "shift.sqlite"
    page = add_page(path, _card())
    assert page["status"] == "open"
    assert page["checks"] == [False] * len(page["card"]["checklist"])
    assert page["title"] == "payments-db-01 · disk full"
    listed = list_pages(path)
    assert [item["id"] for item in listed] == [page["id"]]
    checks = page["checks"][:]
    checks[0] = True
    updated = update_page(path, page["id"], status="resolved", checks=checks)
    assert updated["status"] == "resolved"
    assert updated["checks"][0] is True
    assert get_page(path, page["id"])["status"] == "resolved"


def test_desk_api_triages_and_updates(tmp_path):
    path = tmp_path / "shift.sqlite"

    def build(text):
        return build_card(
            text,
            retrieve_fn=lambda _query, _filters: [],
            answer_fn=lambda _query, _hits: "",
        )

    server = serve(shift_path=path, build=build, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        page = b""
        for _attempt in range(50):
            try:
                with urlopen(base + "/", timeout=1) as home:
                    page = home.read()
                break
            except OSError:
                time.sleep(0.02)
        assert b"On-call desk" in page
        body = json.dumps({"text": "payments-db-01 in prod is out of disk space"}).encode()
        with urlopen(
            Request(base + "/api/triage", data=body, headers={"Content-Type": "application/json"})
        ) as response:
            created = json.loads(response.read())
        assert created["card"]["runbook"] == "disk-full"
        assert created["status"] == "open"
        with urlopen(base + "/api/shift") as response:
            listing = json.loads(response.read())
        assert listing["pages"][0]["id"] == created["id"]
        checks = [True] + [False] * (len(created["checks"]) - 1)
        update = json.dumps({"status": "acknowledged", "checks": checks}).encode()
        with urlopen(
            Request(
                base + f"/api/shift/{created['id']}",
                data=update,
                headers={"Content-Type": "application/json"},
            )
        ) as response:
            saved = json.loads(response.read())
        assert saved["status"] == "acknowledged"
        assert saved["checks"][0] is True
        try:
            urlopen(
                Request(base + "/api/triage", data=b"{}", headers={"Content-Type": "application/json"})
            )
        except HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("empty triage should be rejected")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
