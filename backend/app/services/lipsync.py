"""Avatar parlant (`Project.lipsync`) : quelles scènes sont générées en lip-sync, et avec quelle voix.

Une scène parle quand le mode est actif, qu'un personnage dit sa voix off (`Scene.speaker`) et qu'il est visible dans la
scène (sujet principal ou élément visible), sauf si elle en est sortie (`Scene.lipsync`). Les autres scènes restent des
clips ordinaires sur la voix off."""
from app.models import Asset, Project, Scene


def on_screen(scene: Scene) -> bool:
    """Le personnage qui dit la voix off de la scène y est-il visible ?"""
    return bool(scene.speaker) and (
        scene.speaker == scene.reference or any(e.get("id") == scene.speaker for e in scene.elements or []))


def talks(project: Project, scene: Scene) -> bool:
    """Scène générée en lip-sync : mode actif, personnage qui parle visible, et la scène n'en est pas sortie
    (`Scene.lipsync`, case « Parle face caméra »)."""
    return project.lipsync and scene.lipsync is not False and on_screen(scene)


def voice_matches(asset: Asset | None, text: str, voice_id: str) -> bool:
    """La voix déjà produite pour la scène dit-elle ce texte avec cette voix ? Alors le lip-sync la réutilise au lieu
    d'en payer une nouvelle (les voix d'avant ce mode n'ont pas ces métadonnées : elles sont refaites)."""
    meta = asset.meta if asset else {}
    return bool(meta) and meta.get("text") == text and meta.get("voice_id") == voice_id
