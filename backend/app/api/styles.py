from fastapi import APIRouter

from app.services.styles import STYLES

router = APIRouter(prefix="/styles", tags=["styles"])


@router.get("")
async def list_styles() -> list[dict]:
    """Styles visuels proposés à la création d'une vidéo."""
    return [{"id": style_id, "label": style.label} for style_id, style in STYLES.items()]
