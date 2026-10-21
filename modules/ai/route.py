from fastapi import APIRouter

from .chatbot.form.route import router as form_router


# Every AI feature mounts here, under /ai. A new feature adds one line.
router = APIRouter(prefix="/ai", tags=["ai"])
router.include_router(form_router)
