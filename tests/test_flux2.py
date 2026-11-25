"""FLUX.2 klein with reference images: multipart form, input_image_N slots, every image under 512x512.
No network: requests.post is faked."""
import base64
import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from pipeline import config, keyframes, providers

FIXTURE = Path(__file__).parent / "fixtures" / "storyboard.valid.json"
FLUX2 = "@cf/black-forest-labs/flux-2-klein-4b"


def _png(w, h, color=(120, 80, 40)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def flux2(monkeypatch, tmp_path):
    monkeypatch.setitem(config.MODELS, "image", FLUX2)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    monkeypatch.setattr(providers.C, "FAKE", False)
    sent = {}

    def fake_post(url, headers=None, files=None, timeout=None, **kw):
        sent.update(url=url, files=files)
        body = {"result": {"image": base64.b64encode(_png(64, 64)).decode()}, "success": True}
        return SimpleNamespace(status_code=200, headers={"content-type": "application/json"},
                               json=lambda: body, text=json.dumps(body), content=b"")

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    big = tmp_path / "big.jpg"
    Image.new("RGB", (1280, 720), (10, 20, 30)).save(big)
    return SimpleNamespace(sent=sent, ref=str(big))


def _sb_two_people(ref_a, ref_b=None):
    sb = json.loads(FIXTURE.read_text(encoding="utf-8"))
    a = copy.deepcopy(sb["characters"][0])
    a.update(id="ermias", description="a slim young man in a navy jacket", reference_image=ref_a)
    b = copy.deepcopy(sb["characters"][0])
    b.update(id="brother", description="a young man in an olive jacket", reference_image=ref_b)
    sb["characters"] = [a, b]
    sb["shots"][1]["characters"] = ["brother", "ermias"]  # listed in the other order on purpose
    return sb


def test_multipart_fields_and_reference_size(flux2):
    data, usage = providers.cf_image("two brothers in a cafe", 7, 4, FLUX2, [flux2.ref])
    files = flux2.sent["files"]
    assert flux2.sent["url"].endswith("/ai/run/" + FLUX2)
    assert files["prompt"] == (None, "two brothers in a cafe")
    assert files["steps"] == (None, "4")
    name, png, mime = files["input_image_0"]
    w, h = Image.open(io.BytesIO(png)).size
    assert mime == "image/png" and w < 512 and h < 512
    assert usage == {"images": 1, "reference_images": 1}
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_more_than_four_references_is_refused(flux2):
    with pytest.raises(ValueError):
        providers.cf_image("x", 1, 4, FLUX2, [flux2.ref] * 5)


def test_slots_follow_character_list_not_shot_order(flux2):
    sb = _sb_two_people(flux2.ref, flux2.ref)
    shot = sb["shots"][1]
    prompt = keyframes.build_prompt(sb, shot)
    assert prompt.index("navy jacket, with exactly the face of the person in image 0") < \
        prompt.index("olive jacket, with exactly the face of the person in image 1")
    assert keyframes.reference_images(sb, shot) == [flux2.ref, flux2.ref]


def test_person_without_reference_gets_no_slot(flux2):
    sb = _sb_two_people(flux2.ref, None)
    prompt = keyframes.build_prompt(sb, sb["shots"][1])
    assert "image 0" in prompt and "image 1" not in prompt


def test_schnell_prompts_never_mention_images(monkeypatch, flux2):
    monkeypatch.setitem(config.MODELS, "image", "@cf/black-forest-labs/flux-1-schnell")
    sb = _sb_two_people(flux2.ref, flux2.ref)
    assert "image 0" not in keyframes.build_prompt(sb, sb["shots"][1])


def test_new_reference_photo_regenerates_only_shots_with_that_person(flux2, tmp_path):
    sb = _sb_two_people(flux2.ref, None)
    sb["shots"][1]["characters"] = ["ermias"]
    before = {s["id"]: keyframes.cache_key(sb, s) for s in sb["shots"]}
    other = tmp_path / "new.png"
    other.write_bytes(_png(300, 300, (200, 10, 10)))
    sb["characters"][0]["reference_image"] = str(other)
    after = {s["id"]: keyframes.cache_key(sb, s) for s in sb["shots"]}
    assert [k for k in before if before[k] != after[k]] == ["s02"]


def test_image_size_is_in_the_flux2_cache_key(flux2, monkeypatch):
    sb = _sb_two_people(flux2.ref, None)
    shot = sb["shots"][1]
    before = keyframes.cache_key(sb, shot)
    monkeypatch.setattr(config, "CF_IMAGE_WIDTH", 768)
    assert keyframes.cache_key(sb, shot) != before
