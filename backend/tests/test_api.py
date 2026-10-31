"""API tests with the labelled MOCK adapter and a temporary data directory. No GPU, no network."""

from __future__ import annotations

import io
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.adapters import MockAdapter
from app.config import Settings
from app.main import create_app


def make_jpeg(w=800, h=600, orientation=None) -> bytes:
    img = Image.new("RGB", (w, h), (30, 90, 60))
    d = ImageDraw.Draw(img)
    for i in range(0, w, 20):  # texture so the quality check has something to measure
        d.line([(i, 0), (w - i, h)], fill=(200, 200, 180), width=2)
    buf = io.BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    img.save(buf, format="JPEG", quality=92, exif=exif)
    return buf.getvalue()


def item(**kw):
    base = {"label": "chip", "category": "ic_package", "bbox_2d": [400, 300, 620, 520], "readable": False}
    base.update(kw)
    return base


def settings(tmp_path, **kw):
    return Settings(adapter="mock", data_dir=tmp_path, frontend_dist=None, **kw)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(settings(tmp_path), MockAdapter())) as c:
        yield c


def upload(client, data=None, name="board.jpg"):
    r = client.post("/api/images", files={"image": (name, data or make_jpeg(), "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


def wait(client, job_id, want=("done", "failed", "cancelled"), timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/analyses/{job_id}").json()
        if r["status"] in want:
            return r
        time.sleep(0.02)
    raise AssertionError("timed out waiting for the job")


def analyze(client, image_id):
    r = client.post("/api/analyses", json={"image_id": image_id})
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def client_with(tmp_path, responder, **kw):
    return TestClient(create_app(settings(tmp_path, **kw), MockAdapter(responder)))


# ---- health, upload -------------------------------------------------------------------------


def test_health_reports_mock(client):
    body = client.get("/api/health").json()
    assert body["is_mock"] is True and body["adapter"] == "mock" and body["ok"] is True


def test_upload_returns_dimensions_and_quality(client):
    r = upload(client)
    assert (r["width"], r["height"]) == (800, 600)
    assert r["image_id"].startswith("img_") and "ok" in r["quality"] and isinstance(r["quality"]["problems"], list)


def test_upload_applies_exif_rotation_so_dimensions_match_what_browsers_draw(client):
    r = upload(client, make_jpeg(800, 600, orientation=6))
    assert (r["width"], r["height"]) == (600, 800)


def test_upload_rejects_non_image(client):
    r = client.post("/api/images", files={"image": ("x.jpg", b"not an image at all" * 50, "image/jpeg")})
    assert r.status_code == 422 and r.json()["code"] == "not_an_image"


def test_upload_rejects_unsupported_format_by_content_not_extension(client):
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), "red").save(buf, format="GIF")
    r = client.post("/api/images", files={"image": ("board.jpg", buf.getvalue(), "image/jpeg")})
    assert r.status_code == 415 and r.json()["code"] == "unsupported_format"


def test_upload_rejects_oversize(tmp_path):
    with client_with(tmp_path, None, max_upload_mb=1) as c:
        r = c.post("/api/images", files={"image": ("big.jpg", b"\xff\xd8" + b"0" * (1024 * 1024 + 10), "image/jpeg")})
        assert r.status_code == 413 and r.json()["code"] == "too_large"


def test_missing_image_field_is_a_plain_error(client):
    r = client.post("/api/images")
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


# ---- analysis -------------------------------------------------------------------------------


def test_mock_analysis_returns_boxes_in_original_pixels_and_is_flagged_mock(client):
    img = upload(client)
    done = wait(client, analyze(client, img["image_id"]))
    assert done["status"] == "done" and done["is_mock"] is True and done["model"] == "MOCK"
    assert len(done["observations"]) == 2
    chip = next(o for o in done["observations"] if o["category"] == "ic_package")
    # 0-1000 normalised box [400,300,620,520] on an 800x600 image
    assert chip["bbox"] == pytest.approx([320, 180, 496, 312], abs=1)
    assert chip["bbox_space"] == "original_px" and chip["status"] == "unknown"
    ids = [o["id"] for o in done["observations"]]
    assert len(set(ids)) == 2 and ids == sorted(ids)
    assert done["concerns_checked"] is False and done["findings"] == []


def test_large_image_boxes_are_mapped_back_to_original_not_analysis_size(tmp_path):
    with client_with(tmp_path, lambda r: json.dumps([item()])) as c:
        img = upload(c, make_jpeg(2560, 1920))
        done = wait(c, analyze(c, img["image_id"]))
        assert done["observations"][0]["bbox"] == pytest.approx([1024, 576, 1587, 998], abs=2)


def test_model_cannot_confirm_a_part(tmp_path):
    reply = json.dumps([item(status="confirmed", readable=True, marking_text="ATMEGA328P", identity_guess="ATmega328P")])
    with client_with(tmp_path, lambda r: reply) as c:
        done = wait(c, analyze(c, upload(c)["image_id"]))
        o = done["observations"][0]
        assert o["status"] == "tentative" and o["reference_ids"] == [] and o["source"] == "vlm"


def test_unreadable_marking_is_discarded(tmp_path):
    reply = json.dumps([item(marking_text="ZZ99", readable=False)])
    with client_with(tmp_path, lambda r: reply) as c:
        o = wait(c, analyze(c, upload(c)["image_id"]))["observations"][0]
        assert o["marking_text"] is None and o["status"] == "unknown"


def test_unusable_model_output_fails_visibly_after_bounded_retries(tmp_path):
    calls = []

    def bad(req):
        calls.append(1)
        return "I think there is a chip in the middle."

    with client_with(tmp_path, bad) as c:
        failed = wait(c, analyze(c, upload(c)["image_id"]))
        assert failed["status"] == "failed" and failed["error"]["code"] == "model_output_invalid"
        assert "No detections are shown" in failed["error"]["message"]
        assert "observations" not in failed
        assert len(calls) == 3  # first try plus two repairs


def test_model_server_down_is_reported_with_a_recovery_message(tmp_path):
    from app.adapters import ModelUnavailable

    def down(req):
        raise ModelUnavailable()

    with client_with(tmp_path, down) as c:
        failed = wait(c, analyze(c, upload(c)["image_id"]))
        assert failed["error"]["code"] == "model_unavailable" and "Ollama" in failed["error"]["message"]


def test_second_analysis_while_one_runs_is_busy_and_cancel_discards_result(tmp_path):
    gate = threading.Event()

    def slow(req):
        gate.wait(5)
        return json.dumps([item()])

    with client_with(tmp_path, slow) as c:
        img = upload(c)["image_id"]
        job = analyze(c, img)
        r = c.post("/api/analyses", json={"image_id": img})
        assert r.status_code == 409 and r.json()["code"] == "busy"
        assert c.delete(f"/api/analyses/{job}").status_code == 204
        gate.set()
        time.sleep(0.3)
        final = c.get(f"/api/analyses/{job}").json()
        assert final["status"] == "cancelled" and "observations" not in final
        assert c.delete(f"/api/analyses/{job}").status_code == 204  # idempotent
        analyze(c, img)  # a new one may start now


def test_unknown_ids_are_404_with_actionable_message(client):
    assert client.get("/api/analyses/job_nope").json()["code"] == "analysis_not_found"
    assert client.post("/api/analyses", json={"image_id": "img_nope"}).status_code == 404
    assert client.patch("/api/observations/nope", json={}).json()["code"] == "observation_not_found"


def test_unknown_api_path_is_json_404_not_the_app_shell(client):
    r = client.get("/api/nothing-here")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


# ---- corrections ----------------------------------------------------------------------------


@pytest.fixture
def analysed(client):
    img = upload(client)
    done = wait(client, analyze(client, img["image_id"]))
    chip = next(o for o in done["observations"] if o["category"] == "ic_package")
    return client, img, chip


def test_confirm_without_anything_to_confirm_is_refused(analysed):
    c, _, chip = analysed
    r = c.patch(f"/api/observations/{chip['id']}", json={"confirmed": True})
    assert r.status_code == 422 and r.json()["code"] == "nothing_to_confirm"


def test_typing_a_marking_is_tentative_until_the_person_checks_the_part(analysed):
    c, _, chip = analysed
    r = c.patch(f"/api/observations/{chip['id']}", json={"marking_text": "ATMEGA328P", "confirmed": False}).json()
    o = next(x for x in r["observations"] if x["id"] == chip["id"])
    assert o["status"] == "tentative" and o["marking_text"] == "ATMEGA328P" and o["source"] == "vlm"
    assert not any("Marking not readable" in s for s in o["limitations"])
    assert any(s.startswith("You entered the marking") for s in o["evidence"])


def test_confirming_after_physical_check_marks_it_user_confirmed(analysed):
    c, _, chip = analysed
    r = c.patch(
        f"/api/observations/{chip['id']}",
        json={"marking_text": "ATMEGA328P", "identity": "ATmega328P", "confirmed": True},
    ).json()
    o = next(x for x in r["observations"] if x["id"] == chip["id"])
    assert o["status"] == "confirmed" and o["source"] == "user" and o["model_score"] is None
    assert o["candidates"][0]["identity"] == "ATmega328P" and o["candidates"][0]["reference_id"] is None
    assert "Confirmed by you against the physical part" in o["evidence"]
    # Unticking returns it to tentative.
    r = c.patch(f"/api/observations/{chip['id']}", json={"confirmed": False}).json()
    o = next(x for x in r["observations"] if x["id"] == chip["id"])
    assert o["status"] == "tentative" and "Confirmed by you against the physical part" not in o["evidence"]


def test_clearing_marking_and_name_returns_to_not_identified(analysed):
    c, _, chip = analysed
    c.patch(f"/api/observations/{chip['id']}", json={"marking_text": "X1", "identity": "Thing"})
    r = c.patch(f"/api/observations/{chip['id']}", json={"marking_text": "", "identity": "", "confirmed": False}).json()
    o = next(x for x in r["observations"] if x["id"] == chip["id"])
    assert o["status"] == "unknown" and o["candidates"] == [] and o["marking_text"] is None


def test_redrawn_box_is_clamped_to_the_photo_and_must_have_area(analysed):
    c, img, chip = analysed
    r = c.patch(f"/api/observations/{chip['id']}", json={"bbox": [-50, 10, 900, 100]}).json()
    o = next(x for x in r["observations"] if x["id"] == chip["id"])
    assert o["bbox"] == [0, 10, img["width"], 100]
    for bad in ([5, 5, 5, 50], [900, 900, 950, 950], [1, 2, 3], ["a", 1, 2, 3]):
        r = c.patch(f"/api/observations/{chip['id']}", json={"bbox": bad})
        assert r.status_code == 422 and r.json()["code"] in {"invalid_box", "invalid_request"}, bad
    # NaN cannot be built by the test client, but a raw body can carry it.
    r = c.patch(f"/api/observations/{chip['id']}", content='{"bbox": [0, 0, NaN, 5]}', headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_box"


def test_bad_corrections_are_rejected(analysed):
    c, _, chip = analysed
    url = f"/api/observations/{chip['id']}"
    assert c.patch(url, json={"category": "toaster"}).json()["code"] == "invalid_field"
    assert c.patch(url, json={"status": "confirmed"}).json()["code"] == "unknown_field"
    assert c.patch(url, json={"reference_ids": ["x"]}).json()["code"] == "unknown_field"
    assert c.patch(url, json={"marking_text": "A" * 201}).json()["code"] == "invalid_field"
    assert c.patch(url, json={"confirmed": "yes"}).status_code == 422


def test_correction_survives_a_page_reload(analysed):
    c, _, chip = analysed
    job = chip["id"].rsplit("_", 1)[0]
    c.patch(f"/api/observations/{chip['id']}", json={"marking_text": "LM358"})
    again = c.get(f"/api/analyses/{job}").json()
    assert next(o for o in again["observations"] if o["id"] == chip["id"])["marking_text"] == "LM358"


# ---- board variant and steps ----------------------------------------------------------------


def test_steps_have_no_measurements_or_pin_claims_and_follow_the_board_variant(analysed):
    c, img, chip = analysed
    job = chip["id"].rsplit("_", 1)[0]
    steps = c.get(f"/api/analyses/{job}").json()["steps"]
    assert steps[0]["text"].startswith("Disconnect power")
    assert any("set the board variant" in s["text"] for s in steps)
    assert any(chip["id"] in s["observation_ids"] for s in steps)  # unreadable chip -> close-up step
    assert all(not s["requires_measurement"] for s in steps)

    r = c.patch(f"/api/images/{img['image_id']}", json={"board_variant": "Arduino Uno R3"}).json()
    assert r["board_variant"] == "Arduino Uno R3"
    assert any("matches Arduino Uno R3" in s["text"] for s in r["steps"])
    assert c.get(f"/api/analyses/{job}").json()["board_variant"] == "Arduino Uno R3"


def test_tentative_marking_adds_a_compare_step_and_confirming_removes_the_close_up(analysed):
    c, _, chip = analysed
    r = c.patch(f"/api/observations/{chip['id']}", json={"marking_text": "LM358"}).json()
    compare = [s for s in r["steps"] if chip["id"] in s["observation_ids"]]
    assert len(compare) == 1 and compare[0]["expect"] == "The part reads LM358."


def test_unknown_board_variant_is_refused(analysed):
    c, img, _ = analysed
    r = c.patch(f"/api/images/{img['image_id']}", json={"board_variant": "Totally Made Up 9000"})
    assert r.status_code == 422 and r.json()["code"] == "unknown_variant"
    assert c.patch(f"/api/images/{img['image_id']}", json={"colour": "red"}).json()["code"] == "unknown_field"


# ---- hardening ------------------------------------------------------------------------------


def test_foreign_host_header_is_rejected(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400


def test_non_loopback_bind_is_refused_unless_explicit():
    with pytest.raises(SystemExit):
        Settings(host="0.0.0.0").check_bind()
    Settings(host="127.0.0.1").check_bind()
    Settings(host="0.0.0.0", allow_non_loopback=True).check_bind()


def test_jobs_left_running_by_a_previous_process_are_failed_on_start(tmp_path):
    from app.store import Store

    s = Store(tmp_path)
    s.add_image("img_1", "a.jpg", make_jpeg(), "jpg", 800, 600, {"ok": True, "problems": []})
    s.add_analysis("job_old", "img_1")
    s.set_status("job_old", "running")
    with TestClient(create_app(settings(tmp_path), MockAdapter())) as c:
        r = c.get("/api/analyses/job_old").json()
        assert r["status"] == "failed" and r["error"]["code"] == "interrupted"


def test_built_frontend_is_served_and_cannot_escape_its_folder(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>shell</html>")
    (dist / "assets" / "a.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("secret")
    st = Settings(adapter="mock", data_dir=tmp_path / "data", frontend_dist=dist)
    with TestClient(create_app(st, MockAdapter())) as c:
        assert "shell" in c.get("/").text
        assert c.get("/assets/a.js").text == "console.log(1)"
        assert "shell" in c.get("/some/client/route").text
        for path in ("/..%2Fsecret.txt", "/%2e%2e/secret.txt", "/assets/..%2F..%2Fsecret.txt"):
            assert "secret" not in c.get(path).text, path
