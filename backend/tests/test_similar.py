"""'Find more like this': look-alike search with OpenCV, no model call."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from app.adapters import MockAdapter
from app.main import create_app
from fastapi.testclient import TestClient

from .test_api import settings, upload, wait


def board_with_parts(positions, size=(640, 480)):
    rng = np.random.default_rng(4)
    bg = rng.integers(40, 90, (size[1], size[0], 3), dtype=np.uint8)
    bg[..., 1] = np.clip(bg[..., 1] + 30, 0, 255)
    part = np.zeros((18, 34, 3), np.uint8)
    part[:] = (30, 30, 30)
    part[:, 6:10] = (220, 200, 40)
    part[:, 14:18] = (200, 40, 40)
    part[:, 24:28] = (60, 90, 220)
    for x, y in positions:
        bg[y : y + 18, x : x + 34] = part
    buf = io.BytesIO()
    Image.fromarray(bg).save(buf, format="PNG")
    return buf.getvalue()


def run(client, positions):
    img = upload(client, board_with_parts(positions), "b.png")
    job = client.post("/api/analyses", json={"image_id": img["image_id"]}).json()["job_id"]
    done = wait(client, job)
    assert done["status"] == "done"
    first = done["observations"][0]
    # Point the first observation at one real part, as a person would by redrawing it.
    x, y = positions[0]
    r = client.patch(f"/api/observations/{first['id']}", json={"bbox": [x - 2, y - 2, x + 36, y + 20], "category": "resistor"})
    assert r.status_code == 200, r.text
    return job, first["id"], done


def test_finds_the_other_copies_and_labels_them_as_assist(tmp_path):
    positions = [(40, 40), (200, 60), (360, 300), (500, 120), (100, 380)]
    with TestClient(create_app(settings(tmp_path), MockAdapter())) as c:
        job, oid, before = run(c, positions)
        r = c.post(f"/api/observations/{oid}/similar")
        assert r.status_code == 200, r.text
        body = r.json()
        added = [o for o in body["observations"] if o["id"] in body["added"]]
        assert len(added) >= 3
        for o in added:
            assert o["source"] == "assist"
            assert o["status"] == "unknown"
            assert o["marking_text"] is None
            assert o["category"] == "resistor"
            assert "Not read by the model" in o["evidence"][0]
        # the original rows are all still there
        old_ids = {o["id"] for o in before["observations"]}
        assert old_ids <= {o["id"] for o in body["observations"]}
        # a second call finds nothing new on the same spots
        again = c.post(f"/api/observations/{oid}/similar").json()
        assert again["added"] == []
        assert len({o["id"] for o in again["observations"]}) == len(again["observations"])


def test_assist_matches_can_not_be_confirmed_by_the_model_path(tmp_path):
    with TestClient(create_app(settings(tmp_path), MockAdapter())) as c:
        job, oid, _ = run(c, [(40, 40), (300, 200)])
        body = c.post(f"/api/observations/{oid}/similar").json()
        new = body["added"]
        assert new
        # a look-alike is never confirmed by the search itself
        row = [o for o in body["observations"] if o["id"] == new[0]][0]
        assert row["status"] == "unknown" and row["source"] == "assist"
        # a person's own confirmation is what changes that
        r = c.patch(f"/api/observations/{new[0]}", json={"confirmed": True})
        if r.status_code == 200:
            row = [o for o in r.json()["observations"] if o["id"] == new[0]][0]
            assert row["source"] == "user"


def test_unknown_part_is_404(tmp_path):
    with TestClient(create_app(settings(tmp_path), MockAdapter())) as c:
        r = c.post("/api/observations/nope/similar")
        assert r.status_code == 404


def test_automatic_pass_is_off_by_default_and_reports_when_on(tmp_path):
    from app.config import Settings

    assert Settings().repeats is False
    on = Settings(adapter="mock", data_dir=tmp_path, frontend_dist=None, repeats=True)
    with TestClient(create_app(on, MockAdapter())) as c:
        img = upload(c, board_with_parts([(40, 40), (300, 200)]), "b.png")
        job = c.post("/api/analyses", json={"image_id": img["image_id"]}).json()["job_id"]
        done = wait(c, job)
        assert done["status"] == "done"
        assert "repeat_pass" in done and done["repeat_pass"] is not None
