"""Single-file HTML playground — browser chat surface so the product is usable
without pairing WhatsApp/Telegram first. Mounted at GET /."""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_HTML_PATH = _STATIC_DIR / "playground.html"


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def playground() -> HTMLResponse:
    if not _HTML_PATH.exists():
        return HTMLResponse(
            "<h1>Synapse</h1><p>Playground HTML missing. Reinstall or rebuild.</p>",
            status_code=503,
        )
    return HTMLResponse(_HTML_PATH.read_text(encoding="utf-8"))
