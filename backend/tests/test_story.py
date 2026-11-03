import json

import pytest

from app.providers.base import ProviderError
from app.services.story import (
    INVENTORY_SCHEMA,
    MAX_BIBLE_CHARS,
    STORY_SCHEMA,
    assign_voices,
    build_bible,
    compact_prompt,
    descriptor_head,
    elements_in,
    extra_references,
    main_reference,
    parse_story,
    references_from,
    story_problems,
    story_result_errors,
)

CHLOE = {"id": "chloe", "kind": "character", "name": "Chloe", "descriptor": "Chloe, 22, long blonde ponytail, emerald dress",
         "prompt": "Chloe full body on a plain background"}
SARAH = {"id": "sarah", "kind": "character", "name": "Sarah", "descriptor": "Sarah, 22, short auburn bob, navy blazer",
         "prompt": "Sarah full body on a plain background"}
BAG = {"id": "sac", "kind": "prop", "name": "Sac", "descriptor": "a beige leather handbag with a gold chain",
       "prompt": "A beige leather handbag with a gold chain on a plain background"}
BUTTON = {"id": "bouton", "kind": "prop", "name": "Bouton", "descriptor": "a pearl button on the dress strap", "prompt": "A pearl button"}
BAR = {"id": "bar", "kind": "place", "name": "Bar", "descriptor": "a cozy cocktail bar", "prompt": ""}


def beat(*elements, summary="s", voice="v", duration=4):
    return {"summary": summary, "voice_text": voice, "duration_s": duration,
            "elements": [{"id": i, "state": state} for i, state in elements]}


def story(beats, elements=(CHLOE, SARAH, BAG, BUTTON)):
    return {"elements": list(elements), "beats": beats}


def test_parse_story_merges_the_story_pass_and_the_inventory_pass():
    beats = json.dumps({"beats": [
        {"summary": "Elle coupe le bouton", "voice_text": "Regarde ses mains.", "duration_s": 4},
        {"summary": "Le sac est mouillé", "voice_text": "Oups.", "duration_s": "5 s"}]})
    inventory = json.dumps({"bible": "Anime, cel shading, cocktail bar.",
                            "elements": [{"id": "Sac", "kind": "prop", "name": "Sac", "descriptor": "d", "prompt": "p"}],
                            "beats": [{"elements": [{"id": "Sac", "state": "dry"}]},
                                      {"elements": [{"id": "sac", "state": "wet"}]}]})
    parsed = parse_story(beats, inventory, 9)
    assert [b["duration_s"] for b in parsed["beats"]] == [4, 5]
    assert parsed["beats"][1] == {"summary": "Le sac est mouillé", "voice_text": "Oups.", "duration_s": 5,
                                  "continuity": "cut", "speaker": "", "elements": [{"id": "sac", "state": "wet"}]}
    assert parsed["elements"][0]["id"] == "sac" and parsed["bible"] == "Anime, cel shading, cocktail bar."


def test_parse_story_shares_the_remaining_duration_between_beats_without_one():
    beats = json.dumps({"beats": [{"summary": "a", "voice_text": "v", "duration_s": 4},
                                  {"summary": "b", "voice_text": "v"}, {"summary": "c", "voice_text": "v"}]})
    parsed = parse_story(beats, json.dumps({"elements": [], "beats": []}), 12)
    assert [b["duration_s"] for b in parsed["beats"]] == [4, 4, 4]


def _durations(values, target):
    beats = json.dumps({"beats": [{"summary": "a", "voice_text": "v", "duration_s": d} for d in values]})
    parsed = parse_story(beats, json.dumps({"elements": [], "beats": []}), target)
    return [b["duration_s"] for b in parsed["beats"]]


def test_parse_story_stretches_beats_that_fall_more_than_10_percent_short_of_the_target():
    # Mesuré : 3+4+4+5+5+5 = 26 s pour 30 s demandées ; le surplus va aux beats sous le maximum d'un clip (5 s).
    got = _durations([3, 4, 4, 5, 5, 5], 30)
    assert sum(got) == pytest.approx(30, abs=0.5) and max(got) <= 5 and all(g >= d for g, d in zip(got, [3, 4, 4, 5, 5, 5], strict=False))


def test_parse_story_shrinks_beats_that_overshoot_the_target_by_more_than_10_percent():
    got = _durations([5, 5, 5, 5, 5, 5], 24)
    assert sum(got) == pytest.approx(24, abs=0.5) and min(got) >= 2


def test_parse_story_keeps_durations_within_10_percent_of_the_target():
    assert _durations([3, 4, 4, 5, 5, 6], 30) == [3, 4, 4, 5, 5, 6]


@pytest.mark.parametrize("raw", ["", "pas du json", json.dumps({"beats": []}), json.dumps({"beats": [{"summary": "a"}]})])
def test_parse_story_rejects_a_story_without_usable_beats_and_says_so(raw):
    with pytest.raises(ProviderError, match="story"):
        parse_story(raw, json.dumps({"elements": [], "beats": []}), 30)


def test_parse_story_tolerates_an_inventory_with_fewer_beats_than_the_story():
    beats = json.dumps({"beats": [{"summary": "a", "voice_text": "v", "duration_s": 4},
                                  {"summary": "b", "voice_text": "v", "duration_s": 4}]})
    inventory = json.dumps({"elements": [], "beats": [{"elements": [{"id": "x", "state": "ok"}]}]})
    parsed = parse_story(beats, inventory, 8)
    assert parsed["beats"][0]["elements"] == [{"id": "x", "state": "ok"}] and parsed["beats"][1]["elements"] == []


def test_a_prop_seen_in_one_early_beat_only_is_reported():
    problems = story_problems(story([beat(("chloe", ""), ("bouton", "cut")), beat(("sarah", "")), beat(("chloe", "")),
                                     beat(("sarah", "")), beat(("sac", "dry"))]))
    assert any("bouton" in p and "beat 1" in p for p in problems)


def test_a_prop_in_one_of_the_last_two_beats_is_resolved_there():
    s = story([beat(("chloe", "")), beat(("sarah", "")), beat(("chloe", "")), beat(("sac", "ruined"), ("bouton", "gone")),
               beat(("sarah", ""))])
    assert not any("accessoire" in p for p in story_problems(s))


def test_an_id_absent_from_the_elements_is_reported():
    problems = story_problems(story([beat(("chloe", ""), ("sac_x", "dry")), beat(("sarah", "")), beat(("sac", ""))]))
    assert any("sac_x" in p and "beat 1" in p for p in problems)


def test_an_element_that_no_beat_cites_is_reported():
    problems = story_problems(story([beat(("chloe", "")), beat(("sarah", ""))], elements=(CHLOE, SARAH, BAG)))
    assert any("sac" in p and "aucun beat" in p for p in problems)


def test_a_state_that_goes_back_without_a_beat_between_is_reported():
    s = story([beat(("sac", "dry")), beat(("sac", "wet")), beat(("sac", "dry")), beat(("sac", "dry")), beat(("sac", "dry"))],
              elements=(BAG,))
    assert any("sac" in p and "dry" in p and "beat 3" in p for p in story_problems(s))


def test_a_clean_story_has_no_problem():
    s = story([beat(("chloe", ""), ("bouton", "attached")), beat(("sarah", "")), beat(("bouton", "cut"), ("sac", "dry")),
               beat(("sac", "wet")), beat(("chloe", ""))])
    assert story_problems(s) == []


def test_elements_in_returns_the_full_elements_with_their_state_and_skips_unknown_ids():
    present = elements_in(beat(("sac", "wet"), ("fantome", "x")), [BAG, CHLOE])
    assert present == [{"id": "sac", "kind": "prop", "name": "Sac", "descriptor": BAG["descriptor"], "state": "wet"}]


def test_descriptor_head_joins_descriptors_with_their_state():
    head = descriptor_head([{**BAG, "state": "wet"}, {**CHLOE, "state": ""}])
    assert head == "a beige leather handbag with a gold chain (wet). Chloe, 22, long blonde ponytail, emerald dress"


def test_descriptor_head_names_a_character_whose_descriptor_does_not_name_it():
    marie = {"id": "marie", "kind": "character", "name": "Marie", "descriptor": "young woman, dark blue ponytail", "state": ""}
    assert descriptor_head([marie]) == "Marie, young woman, dark blue ponytail"
    assert descriptor_head([{**marie, "kind": "prop"}]) == "young woman, dark blue ponytail"


def test_references_come_from_characters_and_props_only_and_are_capped():
    many = [{**BAG, "id": f"p{i}"} for i in range(8)]
    assert [r["id"] for r in references_from([BAR, CHLOE, *many])] == ["chloe", "p0", "p1", "p2", "p3", "p4"]
    assert references_from([CHLOE]) == [{"id": "chloe", "prompt": CHLOE["prompt"], "descriptor": CHLOE["descriptor"]}]


def test_schemas_ask_for_the_fields_the_parser_reads():
    assert set(STORY_SCHEMA["properties"]["beats"]["items"]["properties"]) == {
        "summary", "voice_text", "duration_s", "continuity"}
    assert {"bible", "elements", "beats"} <= set(INVENTORY_SCHEMA["properties"])


def test_build_bible_adds_the_element_descriptors_to_the_style_and_is_capped():
    text = build_bible("Anime, cel shading.", [CHLOE, BAR, BAG])
    assert text.startswith("Anime, cel shading.\n")
    assert f"Chloe: {CHLOE['descriptor']}" in text and f"Sac: {BAG['descriptor']}" in text
    assert len(build_bible("x" * 5000, [CHLOE])) == MAX_BIBLE_CHARS


def test_main_reference_prefers_a_character_then_a_prop_that_has_an_image():
    elements = [BAR, BAG, CHLOE]
    assert main_reference(elements_in(beat(("sac", ""), ("chloe", "")), elements), elements) == "chloe"
    assert main_reference(elements_in(beat(("sac", ""), ("bar", "")), elements), elements) == "sac"
    assert main_reference(elements_in(beat(("bar", "")), elements), elements) == ""


def test_an_empty_inventory_is_reported():
    assert any("inventaire" in p for p in story_problems(story([beat(), beat()], elements=())))


def test_a_beat_without_any_visible_element_is_reported():
    problems = story_problems(story([beat(("chloe", "")), beat(), beat(("sac", "x"))], elements=(CHLOE, BAG)))
    assert any("beat 2" in p and "aucun élément" in p for p in problems)


def good_result():
    return {"bible": "b", "elements": [dict(CHLOE)], "beats": [
        {"summary": "s", "voice_text": "v", "duration_s": 4, "elements": [{"id": "chloe", "state": ""}]}]}


def test_a_well_formed_story_result_has_no_error():
    assert story_result_errors(good_result()) == []


@pytest.mark.parametrize("change,message", [
    (lambda r: r.update(beats=[]), "au moins un beat"),
    (lambda r: r["beats"][0].update(summary=" "), "beat 1"),
    (lambda r: r["beats"][0].update(voice_text=""), "beat 1"),
    (lambda r: r["beats"][0].update(duration_s="4 s"), "durée"),
    (lambda r: r["beats"][0].update(duration_s=0), "durée"),
    (lambda r: r["beats"][0].pop("elements"), "beat 1"),
    (lambda r: r["beats"][0]["elements"].append({"id": "fantome", "state": ""}), "fantome"),
    (lambda r: r.update(elements="x"), "éléments"),
])
def test_a_malformed_story_result_is_refused_with_a_readable_message(change, message):
    result = good_result()
    change(result)
    assert any(message in e for e in story_result_errors(result))


def test_parse_story_reads_the_continuity_of_each_beat_and_never_chains_the_first_beat():
    beats = json.dumps({"beats": [
        {"summary": "a", "voice_text": "v", "duration_s": 4, "continuity": "continue"},
        {"summary": "b", "voice_text": "v", "duration_s": 4, "continuity": " Continue "},
        {"summary": "c", "voice_text": "v", "duration_s": 4, "continuity": "cut"},
        {"summary": "d", "voice_text": "v", "duration_s": 4, "continuity": "n'importe quoi"},
        {"summary": "e", "voice_text": "v", "duration_s": 4}]})
    parsed = parse_story(beats, "", 20)
    assert [b["continuity"] for b in parsed["beats"]] == ["cut", "continue", "cut", "cut", "cut"]


def test_a_story_result_with_an_unknown_continuity_is_refused_and_a_missing_one_is_fine():
    result = good_result()
    assert story_result_errors(result) == []
    result["beats"][0]["continuity"] = "continue"
    assert story_result_errors(result) == []
    result["beats"][0]["continuity"] = "peut-être"
    assert any("continuité" in e and "beat 1" in e for e in story_result_errors(result))


def test_extra_references_put_characters_first_skip_the_main_one_and_unavailable_images_and_are_capped():
    kinds = {"chloe": "character", "sac": "prop", "verre": "prop", "sarah": "character", "bar": "place"}
    ids = ["sac", "bar", "chloe", "verre", "sarah"]
    assert extra_references(ids, kinds, {"sac", "chloe", "verre", "sarah"}, exclude={"chloe"}, limit=2) == ["sarah", "sac"]
    assert extra_references(ids, kinds, {"sac"}, exclude=set(), limit=2) == ["sac"]
    assert extra_references(ids, kinds, {"sac", "chloe"}, exclude=set(), limit=0) == []
    assert extra_references(["sac", "sac"], kinds, {"sac"}, exclude=set(), limit=3) == ["sac"]


# --- Voix par personnage : locuteur de chaque beat, voix de chaque personnage ----------------------------------------

def spoken(speaker, *elements):
    return {**beat(*elements), "speaker": speaker}


def test_parse_story_reads_the_speaker_of_each_beat_from_the_inventory_pass():
    beats = json.dumps({"beats": [{"summary": "a", "voice_text": "v", "duration_s": 4},
                                  {"summary": "b", "voice_text": "v", "duration_s": 4}]})
    inventory = json.dumps({"elements": [], "beats": [{"elements": [], "speaker": ""}, {"elements": [], "speaker": " Chloe "}]})
    parsed = parse_story(beats, inventory, 8)
    assert [b["speaker"] for b in parsed["beats"]] == ["", "chloe"]
    assert parse_story(beats, json.dumps({"elements": [], "beats": []}), 8)["beats"][0]["speaker"] == ""


def test_parse_story_keeps_a_valid_voice_id_on_characters_and_drops_an_invalid_one():
    inventory = json.dumps({"elements": [
        {"id": "chloe", "kind": "character", "name": "Chloe", "descriptor": "d", "prompt": "p", "voice_id": "v-1"},
        {"id": "sarah", "kind": "character", "name": "Sarah", "descriptor": "d", "prompt": "p", "voice_id": "../x"}], "beats": []})
    parsed = parse_story(json.dumps({"beats": [{"summary": "a", "voice_text": "v", "duration_s": 4}]}), inventory, 4)
    assert [e["voice_id"] for e in parsed["elements"]] == ["v-1", ""]


def test_a_speaker_that_is_not_a_character_is_reported():
    s = story([spoken("chloe", ("chloe", "")), spoken("sac", ("sac", "x")), spoken("", ("chloe", ""))], elements=(CHLOE, BAG))
    problems = story_problems(s)
    assert any("beat 2" in p and "locuteur" in p and "sac" in p for p in problems)
    assert not any("beat 1" in p and "locuteur" in p for p in problems)


def test_assign_voices_gives_each_speaking_character_a_distinct_catalog_voice_except_the_narrator_voice():
    s = story([spoken("chloe", ("chloe", "")), spoken("", ("sac", "")), spoken("sarah", ("sarah", "")),
               spoken("chloe", ("chloe", ""))], elements=(dict(CHLOE), dict(SARAH), dict(BAG)))
    catalog = [{"id": "narr", "name": "Narrateur"}, {"id": "v1", "name": "A"}, {"id": "v2", "name": "B"}]
    assign_voices(s, catalog, narrator="narr")
    assert [e.get("voice_id") for e in s["elements"]] == ["v1", "v2", None]  # l'accessoire ne parle pas


def test_assign_voices_keeps_chosen_voices_and_leaves_the_rest_empty_when_the_catalog_runs_out():
    s = story([spoken("chloe", ("chloe", "")), spoken("sarah", ("sarah", ""))], elements=({**CHLOE, "voice_id": "mine"}, dict(SARAH)))
    assign_voices(s, [{"id": "mine", "name": "M"}], narrator="")
    assert [e["voice_id"] for e in s["elements"]] == ["mine", ""]  # « mine » est déjà prise : pas de doublon


def test_a_story_result_with_a_bad_voice_id_or_an_unknown_speaker_is_refused():
    result = good_result()
    result["elements"][0]["voice_id"] = "../x"
    assert any("voix" in e for e in story_result_errors(result))
    result = good_result()
    result["beats"][0]["speaker"] = "fantome"
    assert any("beat 1" in e and "locuteur" in e for e in story_result_errors(result))
    result["beats"][0]["speaker"] = "chloe"
    assert story_result_errors(result) == []


def test_compact_prompt_replaces_a_sent_descriptor_by_its_name():
    chloe = {"name": "Chloé", "descriptor": "a young woman with red hair and a green coat"}
    prompt = "A young woman with red hair and a green coat (soaked). Chloé runs. Rain falls."
    assert compact_prompt(prompt, [chloe]) == "Chloé. Chloé runs. Rain falls."
    assert compact_prompt("Chloé runs.", [chloe]) == "Chloé runs."
    assert compact_prompt(prompt, []) == prompt
