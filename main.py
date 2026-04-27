from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

import models  # noqa: F401  -- register all SQLAlchemy mappers
from db import engine
from modules.auth.route import router as auth_router
from modules.forms.route import router as forms_router
from modules.submissions.route import router as submissions_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield


app = FastAPI(title="cx-api", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(forms_router)
app.include_router(submissions_router)


@app.get("/")
def health():
    return {"status": "ok"}
