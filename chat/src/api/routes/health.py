"""api/routes/health.py: GET /health."""

from fastapi import APIRouter

from chat.src.api.middleware import limiter

router = APIRouter()


@router.get("/health")
@limiter.exempt
async def health():
    return {"status": "ok"}
