import pytest

from app.providers.profiles import DEFAULT_PROFILE, PROFILES, ModelFile, get_profile, required_files


def test_catalog_matches_the_spec():
    assert [(p.id, p.speed, p.quality, p.minutes_per_clip, p.width, p.height, p.esrgan, p.keyframe) for p in PROFILES] == [
        ("fast", 4, 3.5, 5, 320, 576, False, False),
        ("balanced", 3, 4, 7.5, 384, 672, False, False),
        ("precision", 2, 5, 11, 384, 672, False, True),
        ("max", 1, 5, 18, 480, 832, True, False),
    ]
    assert DEFAULT_PROFILE == "fast"


def test_legacy_workflow_name_maps_to_max():
    assert get_profile("workflow").id == "max"


def test_unknown_profile_raises_key_error():
    with pytest.raises(KeyError):
        get_profile("inconnu")


def _names(profile_id: str) -> set[str]:
    return {f.filename for f in required_files(get_profile(profile_id))}


def test_every_profile_declares_its_required_files():
    fast = _names("fast")
    assert ModelFile("UnetLoaderGGUF", "unet_name", "Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf") in required_files(get_profile("fast"))
    assert {
        "Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf",
        "Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf",
        "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
        "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
        "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "wan_2.1_vae.safetensors",
    } == fast
    assert _names("balanced") == fast
    assert "ESRGAN/4x-UltraSharp.pth" not in fast
    assert _names("max") == fast | {"ESRGAN/4x-UltraSharp.pth"}

    precision = _names("precision")
    assert {
        "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf",
        "Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf",
        "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
        "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
        "flux1-dev-Q4_K_S.gguf",
        "clip_l.safetensors",
        "t5xxl_fp8_e4m3fn.safetensors",
        "ae.safetensors",
    } <= precision
    assert not any("T2V" in n or "t2v" in n for n in precision)
    assert "ESRGAN/4x-UltraSharp.pth" not in precision
    assert ModelFile("DualCLIPLoader", "clip_name1", "clip_l.safetensors") in required_files(get_profile("precision"))
