import asyncio
import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.providers.base import ProviderError

WIDTH, HEIGHT, FPS = 1080, 1920, 30
# Clips à cadence basse (Wan 2.2 14B : 16 fps) : images intermédiaires calculées par compensation de mouvement plutôt
# que dupliquées (mouvement saccadé). Mesuré : ~3 s de calcul par seconde de clip en 720x1248, sans artefact visible.
# Les sources à 24 fps et plus gardent la simple conversion de cadence.
MIN_SMOOTH_FPS = 24
MINTERPOLATE = f"minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
MUSIC_VOLUME = 0.15
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"  # son final normalisé (cible plateformes), voix + musique
PAD_S = 0.3
# Voix et clip de durées différentes : ils convergent vers le milieu. Voix plus longue : voix accélérée (hauteur
# conservée, `atempo`) et clip ralenti (`setpts`) ; voix plus courte : voix ralentie et clip accéléré. Chacun dans la
# limite où il reste naturel ; si ça ne suffit pas, la voix passe en priorité (clip coupé, ou dernière image tenue). Les
# fichiers d'origine ne sont jamais modifiés : seul le segment monté est transformé.
MAX_TEMPO = 1.4  # voix accélérée de ×1,4 au plus
MIN_TEMPO = 0.85  # voix ralentie de ×0,85 au plus (en dessous, elle traîne)
MAX_STRETCH = 1.25  # clip ralenti ou accéléré de ×1,25 au plus
# Clip plus court que la voix accélérée au maximum : la dernière image est tenue jusqu'à la fin de la scène, jamais de
# reprise du début (un clip bouclé donne l'impression que l'action recommence). 5 s de marge, la durée de la scène coupe
# le surplus.
HOLD_LAST_FRAME = "tpad=stop_mode=clone:stop_duration=5"
# Sous-titres ASS en pixels réels (PlayRes = taille de la vidéo) : un SRT serait mis à l'échelle depuis 384x288 par
# libass (texte énorme et trop haut). Bas centré (Alignment 2), 420 px au-dessus du bas : tiers inférieur, au-dessus des
# boutons/légendes des plateformes. Couleurs &HAABBGGRR : texte blanc, contour noir.
SUB_MARGIN_V, SUB_MARGIN_H = 420, 80
# Styles de sous-titres au choix (paramètre `subtitle_style` de l'étape montage) : police, taille, couleur du texte,
# BorderStyle (1 contour, 3 boîte opaque), épaisseur du contour (ou de la boîte), couleur du contour / de la boîte.
SUBTITLE_STYLES = {
    "classic": {"size": 64, "primary": "&H00FFFFFF", "border": 1, "outline": 4, "outline_colour": "&H00000000"},
    "box": {"size": 60, "primary": "&H00FFFFFF", "border": 3, "outline": 16, "outline_colour": "&HA0000000"},
    "bold": {"size": 84, "primary": "&H0000E6FF", "border": 1, "outline": 8, "outline_colour": "&H00000000"},
}
DEFAULT_SUBTITLE_STYLE = "classic"


def ass_header(style: str) -> str:
    st = SUBTITLE_STYLES.get(style) or SUBTITLE_STYLES[DEFAULT_SUBTITLE_STYLE]
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, \
StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{st["size"]},{st["primary"]},{st["primary"]},{st["outline_colour"]},&H80000000,-1,0,0,0,100,100,0,0,\
{st["border"]},{st["outline"]},1,2,{SUB_MARGIN_H},{SUB_MARGIN_H},{SUB_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


@dataclass
class SceneInput:
    clip: Path
    voice: Path
    text: str


async def _run(*cmd: str, cwd: Path | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise ProviderError(f"ffmpeg: {err.decode()[-300:]}")
    return out.decode()


async def last_frame(video: bytes) -> bytes:
    """Dernière image d'un clip (PNG) : sert d'image de départ à la scène suivante d'un enchaînement."""
    with tempfile.TemporaryDirectory() as workdir:
        src, out = Path(workdir) / "clip.mp4", Path(workdir) / "last.png"
        src.write_bytes(video)
        await _run("ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.2", "-i", str(src), "-update", "1",
                   "-frames:v", "1", str(out))
        if not out.exists():
            raise ProviderError("ffmpeg: aucune image extraite du clip")
        return out.read_bytes()


async def probe_duration(path: Path) -> float:
    out = await _run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path))
    return float(out.strip())


async def probe_fps(path: Path) -> float:
    out = await _run("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                     "-of", "csv=p=0", str(path))
    num, _, den = out.strip().partition("/")
    return float(num) / float(den or 1)


def clip_filter(fps: float, stretch: float = 1.0) -> str:
    """Filtre vidéo d'un clip : durée multipliée par `stretch` (> 1 ralenti, < 1 accéléré), cadence lissée si elle est
    basse, puis 9:16 rempli (lanczos), cadence du rendu et dernière image tenue si la scène dure plus longtemps que le
    clip."""
    slow = f"setpts={stretch:.4f}*PTS," if stretch != 1 else ""
    smooth = f"{MINTERPOLATE}," if fps < MIN_SMOOTH_FPS else ""
    return (f"{slow}{smooth}scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={WIDTH}:{HEIGHT},fps={FPS},setsar=1,{HOLD_LAST_FRAME}")


def _ts(seconds: float) -> str:
    cs = round(seconds * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def _ass_text(text: str) -> str:
    """Une ligne de texte brut : accolades (balises ASS) et antislashs (\\N, \\h…) neutralisés."""
    clean = re.sub(r"\s+", " ", text).strip()
    return clean.replace("\\", "/").replace("{", "(").replace("}", ")")


def build_ass(items: list[tuple[str, float]], style: str = DEFAULT_SUBTITLE_STYLE) -> str:
    lines, t = [], 0.0
    for text, dur in items:
        lines.append(f"Dialogue: 0,{_ts(t)},{_ts(t + dur)},Default,,0,0,0,,{_ass_text(text)}\n")
        t += dur
    return ass_header(style) + "".join(lines)


@dataclass
class Segment:
    """Une scène montée : clip recadré en 9:16 à la durée de la scène, et voix calée sur cette même durée."""
    video: Path
    audio: Path
    duration: float
    text: str


def _segment_version() -> str:
    """Empreinte des réglages d'encodage d'un segment : un changement (taille, cadence, filtres, marge) invalide les
    segments déjà en cache."""
    recipe = "|".join([f"{WIDTH}x{HEIGHT}@{FPS}", MINTERPOLATE, str(MIN_SMOOTH_FPS), str(PAD_S), str(MAX_TEMPO), str(MIN_TEMPO), str(MAX_STRETCH), "fill-pad", clip_filter(0), clip_filter(60)])
    return hashlib.sha1(recipe.encode()).hexdigest()[:8]


SEGMENT_VERSION = _segment_version()


def segment_key(project_id: int, clip_id: int, voice_id: int) -> str:
    """Clé (sans extension) du segment d'une scène dans le stockage : il ne dépend que de son clip et de sa voix, qui
    ne changent jamais (une régénération crée un nouvel asset). Seule la scène modifiée est donc ré-encodée au montage."""
    return f"projects/{project_id}/segments/{SEGMENT_VERSION}-{clip_id}-{voice_id}"


def converge(voice_s: float, clip_s: float) -> tuple[float, float, float]:
    """(durée de la scène sans marge, vitesse de la voix, durée du clip après transformation ÷ sa durée d'origine ; le clip
    remplit la scène marge comprise, sans image figée à la fin tant que `MAX_STRETCH` le permet).
    La scène dure à peu près la moyenne de la voix et du clip, dans les plafonds de `MAX_TEMPO`, `MIN_TEMPO` et
    `MAX_STRETCH`. Si les deux ne peuvent pas se rejoindre, la voix décide (`MAX_TEMPO` / `MIN_TEMPO` au plus) et le
    clip, au plafond, est coupé (plus long que la scène) ou finit sur sa dernière image tenue (plus court)."""
    middle = (voice_s + clip_s) / 2
    lowest = max(voice_s / MAX_TEMPO, clip_s / MAX_STRETCH)
    highest = min(voice_s / MIN_TEMPO, clip_s * MAX_STRETCH)
    if lowest <= highest:
        duration = min(max(middle, lowest), highest)
    else:
        duration = min(max(middle, voice_s / MAX_TEMPO), voice_s / MIN_TEMPO)
    return duration, voice_s / duration, min(max((duration + PAD_S) / clip_s, 1 / MAX_STRETCH), MAX_STRETCH)


async def render_segment(scene: SceneInput, workdir: Path, name: str) -> Segment:
    """Encode une scène : voix et clip convergent vers la même durée (voir `converge`), plus une marge ; le clip est coupé à
    la durée de la scène ou, s'il reste plus court, sa dernière image est tenue. Recadré 9:16 ; voix calée sur la même
    durée."""
    workdir.mkdir(parents=True, exist_ok=True)
    voice_s, clip_s = await probe_duration(scene.voice), await probe_duration(scene.clip)
    duration, tempo, stretch = converge(voice_s, clip_s)
    d = duration + PAD_S
    v, a = workdir / f"{name}.mp4", workdir / f"{name}.wav"
    await _run("ffmpeg", "-y", "-loglevel", "error", "-i", str(scene.clip), "-t", f"{d:.3f}",
               "-vf", clip_filter(await probe_fps(scene.clip), stretch),
               "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(v))
    await _run("ffmpeg", "-y", "-loglevel", "error", "-i", str(scene.voice), "-af", f"{f'atempo={tempo:.4f},' if tempo != 1 else ''}apad=whole_dur={d:.3f}",
               "-ar", "44100", "-ac", "2", str(a))
    return Segment(v, a, d, scene.text)


async def assemble(segments: list[Segment], music: Path | None, out: Path, workdir: Path,
                   subtitle_style: str = DEFAULT_SUBTITLE_STYLE) -> float:
    """Assemble les segments : sous-titres, voix, musique éventuelle, normalisation du son. Renvoie la durée totale."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "v.txt").write_text("".join(f"file '{s.video.resolve()}'\n" for s in segments), encoding="utf-8")
    (workdir / "a.txt").write_text("".join(f"file '{s.audio.resolve()}'\n" for s in segments), encoding="utf-8")
    (workdir / "subs.ass").write_text(build_ass([(s.text, s.duration) for s in segments], subtitle_style), encoding="utf-8")
    await _run("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "v.txt", "-c", "copy",
               "video.mp4", cwd=workdir)
    await _run("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "a.txt", "-c", "copy",
               "voice.wav", cwd=workdir)
    total = sum(s.duration for s in segments)
    inputs = ["-i", "video.mp4", "-i", "voice.wav"]
    fc = "[0:v]subtitles=subs.ass[v];"
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        fc += f"[2:a]volume={MUSIC_VOLUME}[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix];[mix]{LOUDNORM}[a]"
    else:
        fc += f"[1:a]{LOUDNORM}[a]"
    await _run("ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
               "-t", f"{total:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out.resolve()), cwd=workdir)
    return total


async def render(scenes: list[SceneInput], music: Path | None, out: Path, workdir: Path) -> float:
    """Montage complet, sans cache : encode chaque scène puis assemble."""
    segments = [await render_segment(s, workdir, f"s{i}") for i, s in enumerate(scenes)]
    return await assemble(segments, music, out, workdir)
