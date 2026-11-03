"""Styles visuels proposés à la création d'une vidéo. Les directives sont en anglais : elles finissent dans les
prompts visuels."""
from typing import NamedTuple


class Style(NamedTuple):
    label: str
    directive: str


STYLES: dict[str, Style] = {
    "realistic": Style("Réaliste", "photorealistic cinematic footage, natural lighting, real-world textures"),
    "anime": Style("Anime", "Japanese anime style, cel shading, vivid colors, expressive characters"),
    "illustration": Style("Illustration", "hand-drawn digital illustration, flat colors, soft shapes, storybook look"),
}


def directive(style_id: str) -> str:
    """Directive du style, chaîne vide si le style est vide ou inconnu."""
    style = STYLES.get(style_id)
    return style.directive if style else ""
