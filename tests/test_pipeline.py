"""Fast checks of the contract and the caching rules. Run: make test"""
import copy
import json
from pathlib import Path

import pytest

from pipeline import keyframes, narration, shots
from pipeline.validate import check

FIXTURE = Path(__file__).parent / "fixtures" / "storyboard.valid.json"


@pytest.fixture
def sb():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_is_valid(sb):
    errors, _, _ = check(sb)
    assert errors == []


def test_schema_rejects_missing_reason(sb):
    del sb["shots"][0]["reason"]
    errors, _, _ = check(sb)
    assert any("reason" in e for e in errors)


def test_schema_rejects_too_few_shots(sb):
    sb["shots"] = sb["shots"][:5]
    errors, _, _ = check(sb)
    assert errors


def test_consent_gate(sb):
    _, _, consent = check(sb)
    assert consent, "a real person without recorded consent must be flagged"
    sb["characters"][0]["consent"]["recorded"] = True
    _, _, consent = check(sb)
    assert consent == []


def test_unknown_character(sb):
    sb["shots"][0]["characters"] = ["nobody"]
    errors, _, _ = check(sb)
    assert any("unknown character" in e for e in errors)


def test_changing_one_prompt_changes_only_that_keyframe(sb):
    before = {s["id"]: keyframes.cache_key(sb, s) for s in sb["shots"]}
    changed = copy.deepcopy(sb)
    changed["shots"][2]["image_prompt"] += " at dusk"
    after = {s["id"]: keyframes.cache_key(changed, s) for s in changed["shots"]}
    assert [k for k in before if before[k] != after[k]] == ["s03"]


def test_style_block_change_invalidates_every_keyframe(sb):
    changed = copy.deepcopy(sb)
    changed["style"]["style_block"] += ", film grain"
    assert all(keyframes.cache_key(sb, s) != keyframes.cache_key(changed, c)
               for s, c in zip(sb["shots"], changed["shots"]))


def test_changing_one_line_changes_only_that_narration(sb):
    changed = copy.deepcopy(sb)
    changed["shots"][4]["narration"]["text"] = "a different line"
    diff = [s["id"] for s, c in zip(sb["shots"], changed["shots"])
            if narration.cache_key(sb, s) != narration.cache_key(changed, c)]
    assert diff == ["s05"]


def test_wan_frame_counts_are_4n_plus_1_and_capped():
    for d in (2, 3.3, 5, 7.5, 12):
        f = shots.frame_num(d)
        assert (f - 1) % 4 == 0 and f <= 121
