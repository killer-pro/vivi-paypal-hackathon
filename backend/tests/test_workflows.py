import pytest

from app.providers.profiles import PROFILES, get_profile
from app.providers.workflows import i2v_workflow, keyframe_workflow, kontext_workflow, t2v_workflow


def nodes(workflow: dict, class_type: str) -> list[dict]:
    return [n for n in workflow.values() if n["class_type"] == class_type]


def test_t2v_substitutes_size_frames_seed_prompt():
    wf = t2v_workflow(get_profile("fast"), 'un "chat"', 42, 49)
    (latent,) = nodes(wf, "EmptyHunyuanLatentVideo")
    assert (latent["inputs"]["width"], latent["inputs"]["height"], latent["inputs"]["length"]) == (320, 576, 49)
    assert nodes(wf, "KSamplerAdvanced")[0]["inputs"]["noise_seed"] == 42
    assert nodes(wf, "CLIPTextEncode")[0]["inputs"]["text"] == 'un "chat"'


def test_esrgan_only_for_max():
    for profile in PROFILES:
        if profile.keyframe:
            continue
        wf = t2v_workflow(profile, "p", 1, 49)
        assert bool(nodes(wf, "ImageUpscaleWithModel")) == (profile.id == "max")
        assert bool(nodes(wf, "UpscaleModelLoader")) == (profile.id == "max")


def test_esrgan_is_blended_with_the_plain_upscale():
    wf = t2v_workflow(get_profile("max"), "p", 1, 49)
    (blend,) = nodes(wf, "ImageBlend")
    assert blend["inputs"]["blend_factor"] == 0.5
    esrgan, plain = (wf[blend["inputs"][k][0]] for k in ("image1", "image2"))
    assert wf[esrgan["inputs"]["image"][0]]["class_type"] == "ImageUpscaleWithModel"
    assert wf[plain["inputs"]["image"][0]]["class_type"] == "VAEDecode"
    assert (plain["inputs"]["width"], plain["inputs"]["height"]) == (720, 1248)
    (combine,) = nodes(wf, "VHS_VideoCombine")
    assert wf[combine["inputs"]["images"][0]] is blend
    assert not nodes(t2v_workflow(get_profile("fast"), "p", 1, 49), "ImageBlend")


def test_prompt_with_placeholder_stays_literal():
    wf = t2v_workflow(get_profile("fast"), "{{SEED}}", 7, 49)
    assert nodes(wf, "CLIPTextEncode")[0]["inputs"]["text"] == "{{SEED}}"
    assert nodes(wf, "KSamplerAdvanced")[0]["inputs"]["noise_seed"] == 7


def test_i2v_reads_the_uploaded_image():
    wf = i2v_workflow(get_profile("precision"), "p", 3, 49, "keyframe_abc.png")
    (load,) = nodes(wf, "LoadImage")
    assert load["inputs"]["image"] == "keyframe_abc.png"
    (i2v,) = nodes(wf, "WanImageToVideo")
    assert (i2v["inputs"]["width"], i2v["inputs"]["height"], i2v["inputs"]["length"]) == (384, 672, 49)


def test_keyframe_size_is_576x1008():
    wf = keyframe_workflow("un chat", 5)
    (latent,) = nodes(wf, "EmptySD3LatentImage")
    assert (latent["inputs"]["width"], latent["inputs"]["height"]) == (576, 1008)
    assert nodes(wf, "KSampler")[0]["inputs"]["seed"] == 5
    assert nodes(wf, "SaveImage")[0]["inputs"]["filename_prefix"] == "video_virale/keyframe"


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_every_workflow_ends_at_720x1248(profile):
    wf = (
        i2v_workflow(profile, "p", 1, 49, "k.png") if profile.keyframe else t2v_workflow(profile, "p", 1, 49)
    )
    scales = nodes(wf, "ImageScale")
    assert len(scales) == (2 if profile.esrgan else 1)  # Maximum : version ESRGAN et version simple, mêlées
    assert all((n["inputs"]["width"], n["inputs"]["height"]) == (720, 1248) for n in scales)
    (combine,) = nodes(wf, "VHS_VideoCombine")
    final = wf[combine["inputs"]["images"][0]]
    assert final["class_type"] == ("ImageBlend" if profile.esrgan else "ImageScale")


def test_kontext_with_one_image_keeps_a_single_reference_latent():
    wf = kontext_workflow("p", 7, ["a.png"])
    assert len(nodes(wf, "ReferenceLatent")) == 1 and [n["inputs"]["image"] for n in nodes(wf, "LoadImage")] == ["a.png"]


def test_kontext_with_several_images_chains_one_reference_latent_per_image_before_the_guidance():
    wf = kontext_workflow("p", 7, ["a.png", "b.png", "c.png"])
    assert [n["inputs"]["image"] for n in nodes(wf, "LoadImage")] == ["a.png", "b.png", "c.png"]
    latents = {key: n for key, n in wf.items() if n["class_type"] == "ReferenceLatent"}
    assert len(latents) == 3 and len(nodes(wf, "VAEEncode")) == 3
    (guidance,) = nodes(wf, "FluxGuidance")
    # chaîne : texte → image 1 → image 2 → image 3 → guidance
    chain, key = [], guidance["inputs"]["conditioning"][0]
    while key in latents:
        chain.append(key)
        key = latents[key]["inputs"]["conditioning"][0]
    assert len(chain) == 3 and wf[key]["class_type"] == "CLIPTextEncode"
    first = latents[chain[-1]]["inputs"]["latent"][0]
    assert wf[wf[first]["inputs"]["pixels"][0]]["inputs"]["image"][0] and wf[
        wf[wf[first]["inputs"]["pixels"][0]]["inputs"]["image"][0]]["inputs"]["image"] == "a.png"  # la première image en tête
    assert all(n["inputs"]["width"] == 576 and n["inputs"]["height"] == 1008 for n in nodes(wf, "ImageScale"))
    assert nodes(wf, "KSampler")[0]["inputs"]["seed"] == 7
