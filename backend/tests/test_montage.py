import re
import subprocess
from pathlib import Path

import pytest

from app.services.montage import (
    HEIGHT,
    HOLD_LAST_FRAME,
    WIDTH,
    SceneInput,
    build_ass,
    clip_filter,
    music_level,
    probe_duration,
    probe_fps,
    render,
)


def mk(path: Path, *args: str):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, str(path)], check=True)


def test_build_ass_uses_real_pixels_and_sanitizes():
    ass = build_ass([("Salut\n\n\"toi\" {\\b1}🚀", 2.0), ("Fin", 1.5)])
    assert f"PlayResX: {WIDTH}\nPlayResY: {HEIGHT}\n" in ass  # tailles et marges en pixels 1080x1920
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,Salut \"toi\" (/b1)🚀\n" in ass
    assert "Dialogue: 0,0:00:02.00,0:00:03.50,Default,,0,0,0,,Fin\n" in ass


def test_build_ass_replaces_dashes_missing_from_the_font():
    # tirets insécables écrits par le LLM (« micro‑objectif ») : absents de la police, affichés en carré vide
    ass = build_ass([("un micro\u2011objectif, mi\u2010temps", 1.0)])
    assert ",,un micro-objectif, mi-temps\n" in ass


def test_build_ass_subtitle_styles():
    classic, box, bold = (build_ass([("Salut", 1.0)], s) for s in ("classic", "box", "bold"))
    assert ",64,&H00FFFFFF," in classic and ",1,4,1,2," in classic  # contour
    assert ",3,16,1,2," in box  # boîte opaque (BorderStyle 3)
    assert ",84,&H0000E6FF," in bold  # gros texte jaune
    assert build_ass([("Salut", 1.0)], "inconnu") == classic  # style inconnu : retombe sur le classique


async def test_render_9_16_with_short_clip_held_and_music(tmp_path):
    clip = tmp_path / "c.mp4"
    mk(clip, "-f", "lavfi", "-i", "color=c=red:s=320x568:d=1:r=30", "-pix_fmt", "yuv420p")  # 1 s
    voice = tmp_path / "v.mp3"
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=3")  # 3 s > clip
    music = tmp_path / "m.mp3"
    mk(music, "-f", "lavfi", "-i", "sine=frequency=100:duration=2")
    out = tmp_path / "out.mp4"
    total = await render([SceneInput(clip, voice, "Texte \"cité\"")], music, out, tmp_path / "w")
    assert 2.3 <= total <= 2.7  # voix de 3 s accélérée au plus (1,4) : 2,14 s + marge
    assert abs(await probe_duration(out) - total) < 0.3
    size = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert size == "1080,1920,30/1"


async def test_render_without_music(tmp_path):
    clip = tmp_path / "c.mp4"
    mk(clip, "-f", "lavfi", "-i", "color=c=red:s=320x568:d=2:r=30", "-pix_fmt", "yuv420p")
    voice = tmp_path / "v.mp3"
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=1")
    out = tmp_path / "o.mp4"
    await render([SceneInput(clip, voice, "x")], None, out, tmp_path / "w")
    assert out.stat().st_size > 0


async def test_render_trims_clip_longer_than_scene(tmp_path):
    clip = tmp_path / "c.mp4"
    mk(clip, "-f", "lavfi", "-i", "color=c=red:s=320x568:d=5:r=30", "-pix_fmt", "yuv420p")  # clip Kling de 5 s
    voice = tmp_path / "v.mp3"
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=2")  # scène de ~2 s
    out = tmp_path / "o.mp4"
    total = await render([SceneInput(clip, voice, "x")], None, out, tmp_path / "w")
    assert total < 3 and abs(await probe_duration(out) - total) < 0.3


async def test_render_accepts_16fps_portrait_clip(tmp_path):
    clip = tmp_path / "c.mp4"  # sortie Wan 2.2 14B : 49 images à 16 fps, 480x832
    mk(clip, "-f", "lavfi", "-i", "testsrc=s=480x832:r=16", "-frames:v", "49", "-pix_fmt", "yuv420p")
    voice = tmp_path / "v.mp3"
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=4")  # voix plus longue que le clip : dernière image tenue
    out = tmp_path / "o.mp4"
    total = await render([SceneInput(clip, voice, "x")], None, out, tmp_path / "w")
    assert abs(await probe_duration(out) - total) < 0.3
    stream = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert stream == "1080,1920,30/1"


def test_clip_filter_interpolates_only_low_frame_rates():
    assert clip_filter(16).startswith("minterpolate=fps=30:mi_mode=mci")  # Wan 2.2 14B : mouvement lissé vers 30 fps
    for fps in (24, 25, 30, 60):  # providers cloud : cadence d'origine, simplement convertie
        assert "minterpolate" not in clip_filter(fps)
    assert all(f"fps=30,setsar=1,{HOLD_LAST_FRAME}" in clip_filter(fps) for fps in (16, 30))
    assert "flags=lanczos" in clip_filter(30)


async def test_probe_fps_reads_frame_rate(tmp_path):
    clip = tmp_path / "c.mp4"
    mk(clip, "-f", "lavfi", "-i", "testsrc=s=64x64:r=16", "-frames:v", "8", "-pix_fmt", "yuv420p")
    assert await probe_fps(clip) == 16


def mean_volume(path: Path) -> float:
    err = subprocess.run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True, check=True).stderr
    return float(err.split("mean_volume:")[1].split("dB")[0])


async def test_music_does_not_lower_voice_level(tmp_path):
    clip = tmp_path / "c.mp4"
    mk(clip, "-f", "lavfi", "-i", "color=c=red:s=320x568:d=2:r=30", "-pix_fmt", "yuv420p")
    voice = tmp_path / "v.wav"
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=2")
    silence = tmp_path / "m.wav"
    mk(silence, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "2")
    without, with_music = tmp_path / "a.mp4", tmp_path / "b.mp4"
    await render([SceneInput(clip, voice, "x")], None, without, tmp_path / "w1")
    await render([SceneInput(clip, voice, "x")], silence, with_music, tmp_path / "w2")
    assert abs(mean_volume(with_music) - mean_volume(without)) < 1  # amix normalize=0 : voix non divisée par 2


def integrated_loudness(path: Path) -> float:
    err = subprocess.run(["ffmpeg", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True, check=True).stderr
    return float(err.split('"input_i" : "')[1].split('"')[0])


@pytest.mark.parametrize("with_music", [False, True])
async def test_final_audio_is_loudness_normalized(tmp_path, with_music):
    clip = tmp_path / "c.mp4"
    mk(clip, "-f", "lavfi", "-i", "color=c=red:s=320x568:d=6:r=30", "-pix_fmt", "yuv420p")
    voice = tmp_path / "v.wav"
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=6", "-af", "volume=0.05")  # voix très faible
    music = tmp_path / "m.wav"
    mk(music, "-f", "lavfi", "-i", "sine=frequency=500:duration=6", "-ar", "44100")
    out = tmp_path / "o.mp4"
    await render([SceneInput(clip, voice, "x")], music if with_music else None, out, tmp_path / "w")
    assert abs(integrated_loudness(out) - (-16)) < 2


def test_segment_key_depends_only_on_clip_voice_and_encoding_recipe():
    from app.services import montage

    key = montage.segment_key(7, 12, 34)
    assert key == f"projects/7/segments/{montage.SEGMENT_VERSION}-12-34"
    assert montage.segment_key(7, 12, 35) != key and montage.segment_key(7, 13, 34) != key  # autre clip ou autre voix
    assert len(montage.SEGMENT_VERSION) == 8


async def test_render_segment_then_assemble_equals_render(tmp_path):
    from app.services.montage import assemble, render_segment

    clip, voice = tmp_path / "c.mp4", tmp_path / "v.mp3"
    mk(clip, "-f", "lavfi", "-i", "color=c=red:s=320x568:d=2:r=30", "-pix_fmt", "yuv420p")
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=2")
    scene = SceneInput(clip, voice, "x")
    segments = [await render_segment(scene, tmp_path / "seg", f"s{i}") for i in range(2)]
    assert all(abs(s.duration - 2.3) < 0.05 for s in segments)  # voix + marge
    total = await assemble(segments, None, tmp_path / "o.mp4", tmp_path / "w")
    assert abs(total - 4.6) < 0.1 and abs(await probe_duration(tmp_path / "o.mp4") - total) < 0.3


@pytest.mark.parametrize("style", ["classic", "box", "bold", "none"])
async def test_assemble_burns_each_subtitle_style(tmp_path, style):
    from app.services.montage import assemble, render_segment

    clip, voice = tmp_path / "c.mp4", tmp_path / "v.mp3"
    mk(clip, "-f", "lavfi", "-i", "color=c=blue:s=320x568:d=1:r=30", "-pix_fmt", "yuv420p")
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=1")
    segment = await render_segment(SceneInput(clip, voice, "Un texte assez long pour passer sur deux lignes"), tmp_path / "seg", "s")
    out = tmp_path / f"{style}.mp4"
    await assemble([segment], None, out, tmp_path / "w", style)
    assert out.stat().st_size > 0


@pytest.mark.parametrize(("percent", "level"), [(None, 0.15), (40, 0.4), ("25", 0.25), (0, 0.0), (250, 1.0), (-5, 0.0),
                                               ("fort", 0.15), (float("nan"), 0.15)])
def test_music_level_reads_the_volume_percent_of_the_music_step(percent, level):
    assert music_level(percent) == level


async def test_music_volume_sets_the_music_level_under_the_voice(tmp_path):
    """Voix à 300 Hz, musique à 4 kHz : le pic au-dessus de 2 kHz ne mesure que la musique."""
    from app.services.montage import assemble, render_segment

    clip, voice, music = tmp_path / "c.mp4", tmp_path / "v.wav", tmp_path / "m.wav"
    mk(clip, "-f", "lavfi", "-i", "color=c=red:s=320x568:d=1:r=30", "-pix_fmt", "yuv420p")
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=1")
    mk(music, "-f", "lavfi", "-i", "sine=frequency=4000:duration=3")
    segment = await render_segment(SceneInput(clip, voice, "x"), tmp_path / "seg", "s")

    async def music_peak(volume: float) -> float:
        out = tmp_path / f"{volume}.mp4"
        await assemble([segment], music, out, tmp_path / f"w{volume}", music_volume=volume)
        log = subprocess.run(["ffmpeg", "-i", str(out), "-af", "highpass=f=2000:poles=2,highpass=f=2000:poles=2,volumedetect",
                              "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
        return float(re.search(r"max_volume: (\S+) dB", log).group(1))

    low, high = await music_peak(0.05), await music_peak(0.6)
    assert high - low > 15  # ×12 en amplitude ≈ +21,6 dB (la voix, identique, fixe la normalisation)


async def test_no_subtitles_style_burns_no_text(tmp_path):
    """Style « none » : la zone des sous-titres garde la couleur du clip (aucun pixel blanc du texte)."""
    from app.services.montage import assemble, render_segment

    clip, voice = tmp_path / "c.mp4", tmp_path / "v.mp3"
    mk(clip, "-f", "lavfi", "-i", "color=c=blue:s=320x568:d=1:r=30", "-pix_fmt", "yuv420p")
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=1")
    segment = await render_segment(SceneInput(clip, voice, "TEXTE BIEN VISIBLE"), tmp_path / "seg", "s")

    async def brightest(style: str) -> int:
        out = tmp_path / f"{style}.mp4"
        await assemble([segment], None, out, tmp_path / f"w{style}", style)
        gray = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(out), "-frames:v", "1", "-vf",
                               f"crop={WIDTH}:300:0:{HEIGHT - 700},format=gray", "-f", "rawvideo", "-"],
                              capture_output=True, check=True).stdout
        return max(gray)

    assert await brightest("classic") > 200 and await brightest("none") < 100


async def test_render_holds_the_last_frame_of_a_clip_shorter_than_the_voice(tmp_path):
    """La fin d'un clip est la fin : pas de reprise du début (testsrc change à chaque image, une boucle se verrait)."""
    clip = tmp_path / "c.mp4"
    mk(clip, "-f", "lavfi", "-i", "testsrc=s=320x568:r=30", "-frames:v", "30", "-pix_fmt", "yuv420p")  # 1 s
    voice = tmp_path / "v.mp3"
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=3")
    out = tmp_path / "o.mp4"
    await render([SceneInput(clip, voice, "x")], None, out, tmp_path / "w")

    def similarity(a: str, b: str) -> float:
        """SSIM entre l'image à `a` s. et celle à `b` s. (1 = identiques ; l'encodage x264 les rend presque identiques)."""
        log = subprocess.run(
            ["ffmpeg", "-loglevel", "info", "-ss", a, "-i", str(out), "-ss", b, "-i", str(out), "-frames:v", "1",
             "-lavfi", "ssim", "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
        return float(re.search(r"All:([\d.]+)", log).group(1))

    assert similarity("1.3", "2.2") > 0.99 > similarity("0.2", "0.9")


def test_converge_meets_in_the_middle_within_the_natural_limits():
    from app.services.montage import MAX_STRETCH, MAX_TEMPO, MIN_TEMPO, PAD_S, converge

    duration, tempo, stretch = converge(4.4, 3.4)  # voix 1 s plus longue : voix accélérée, clip ralenti, au milieu
    assert duration == pytest.approx(3.9) and tempo == pytest.approx(4.4 / 3.9)
    assert stretch == pytest.approx((3.9 + PAD_S) / 3.4)  # le clip remplit aussi la marge : pas d'image figée
    duration, tempo, stretch = converge(3.0, 3.3)  # voix plus courte : voix ralentie, clip accéléré, au milieu
    assert duration == pytest.approx(3.15) and tempo == pytest.approx(3.0 / 3.15)
    assert stretch == pytest.approx((3.15 + PAD_S) / 3.3)
    assert converge(3.3, 3.3) == (3.3, 1.0, pytest.approx((3.3 + PAD_S) / 3.3))
    duration, tempo, stretch = converge(9.0, 3.3)  # beaucoup trop longue : voix au maximum, clip ralenti au maximum
    assert (duration, tempo, stretch) == pytest.approx((9.0 / MAX_TEMPO, MAX_TEMPO, MAX_STRETCH))
    duration, tempo, stretch = converge(1.5, 3.3)  # beaucoup trop courte : voix ralentie au maximum, clip accéléré au maximum
    assert (duration, tempo, stretch) == pytest.approx((1.5 / MIN_TEMPO, MIN_TEMPO, 1 / MAX_STRETCH))


async def test_render_speeds_up_a_voice_longer_than_the_clip(tmp_path):
    clip = tmp_path / "c.mp4"
    mk(clip, "-f", "lavfi", "-i", "testsrc=s=320x568:r=30", "-frames:v", "90", "-pix_fmt", "yuv420p")  # 3 s
    voice = tmp_path / "v.mp3"
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=3.5")
    out = tmp_path / "o.mp4"
    total = await render([SceneInput(clip, voice, "x")], None, out, tmp_path / "w")
    assert total == pytest.approx(3.25 + 0.3, abs=0.15)  # voix 3,5 s et clip 3 s convergent vers 3,25 s, + marge


async def test_render_stretches_a_voice_shorter_than_the_clip_and_speeds_the_clip_up(tmp_path):
    clip = tmp_path / "c.mp4"
    mk(clip, "-f", "lavfi", "-i", "testsrc=s=320x568:r=30", "-frames:v", "99", "-pix_fmt", "yuv420p")  # 3,3 s
    voice = tmp_path / "v.mp3"
    mk(voice, "-f", "lavfi", "-i", "sine=frequency=300:duration=3")
    out = tmp_path / "o.mp4"
    total = await render([SceneInput(clip, voice, "x")], None, out, tmp_path / "w")
    assert total == pytest.approx(3.15 + 0.3, abs=0.15)  # voix 3 s et clip 3,3 s convergent vers 3,15 s, + marge


async def test_last_frame_returns_the_final_image_of_a_clip_as_png(tmp_path):
    """Un clip dont la couleur change à chaque seconde : la dernière image n'a pas la couleur de la première."""
    from app.services.montage import last_frame

    clip = tmp_path / "c.mp4"
    mk(clip, "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1:r=10", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1:r=10",
       "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p")
    png = await last_frame(clip.read_bytes())
    assert png.startswith(b"\x89PNG")
    out = tmp_path / "f.png"
    out.write_bytes(png)
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(out), "-vf", "scale=1:1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    assert raw[2] > 200 and raw[0] < 60  # bleu, pas rouge


async def test_last_frame_of_something_that_is_not_a_video_fails_readably():
    from app.providers.base import ProviderError
    from app.services.montage import last_frame

    with pytest.raises(ProviderError, match="ffmpeg"):
        await last_frame(b"pas une video")
