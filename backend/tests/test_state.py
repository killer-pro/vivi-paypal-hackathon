import pytest

from app.state import InvalidTransition, can_start, dependents, downstream, transition, upstream

ALL_PENDING = {n: "pending" for n in ["idea", "story", "script", "reference", "clips", "voice", "music", "montage", "final"]}


def test_valid_transitions():
    assert transition("pending", "running") == "running"
    assert transition("running", "awaiting_validation") == "awaiting_validation"
    assert transition("awaiting_validation", "approved") == "approved"
    assert transition("running", "failed") == "failed"
    assert transition("failed", "running") == "running"
    assert transition("stale", "running") == "running"
    assert transition("approved", "running") == "running"  # régénération


def test_invalid_transitions():
    with pytest.raises(InvalidTransition):
        transition("pending", "approved")
    with pytest.raises(InvalidTransition):
        transition("running", "running")


def test_downstream():
    assert downstream("clips") == ["voice", "music", "montage", "final"]
    assert downstream("final") == []


def test_can_start_requires_previous_required_steps_approved():
    s = dict(ALL_PENDING, idea="approved", story="approved", script="approved")
    assert can_start(s, "clips")  # reference optionnelle, ignorée
    assert not can_start(dict(s, script="awaiting_validation"), "clips")
    assert can_start(ALL_PENDING, "idea")
    assert not can_start(ALL_PENDING, "script")
    assert not can_start(dict(ALL_PENDING, idea="approved"), "script")  # la story doit être validée


def test_reference_starts_while_script_awaits_validation():
    s = dict(ALL_PENDING, idea="approved", story="approved", script="awaiting_validation")
    assert can_start(s, "reference") is True


def test_clips_still_need_script_approved():
    s = dict(ALL_PENDING, idea="approved", story="approved", script="awaiting_validation")
    assert can_start(s, "clips") is False


def test_reference_blocked_while_story_unapproved():
    s = dict(ALL_PENDING, idea="approved", story="awaiting_validation", script="awaiting_validation")
    assert can_start(s, "reference") is False


def test_voice_and_music_depend_on_script_only():
    assert upstream("voice") == ["idea", "story", "script"] and upstream("music") == ["idea", "story", "script"]
    assert upstream("montage") == ["idea", "story", "script", "reference", "clips", "voice", "music"]
    assert dependents("clips") == ["montage", "final"] and dependents("voice") == ["montage", "final"]
    assert dependents("story") == ["script", "reference", "clips", "voice", "music", "montage", "final"]
    assert dependents("script") == ["reference", "clips", "voice", "music", "montage", "final"]


def test_voice_can_start_while_clips_are_not_validated():
    s = dict(ALL_PENDING, idea="approved", story="approved", script="approved", clips="running")
    assert can_start(s, "voice") and can_start(s, "music")
    assert not can_start(s, "montage")
