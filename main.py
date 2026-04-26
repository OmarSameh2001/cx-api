from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

import models  # noqa: F401  -- register all SQLAlchemy mappers
from db import engine
from modules.auth.route import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield


app = FastAPI(title="cx-api", lifespan=lifespan)

app.include_router(auth_router)


@app.get("/")
def health():
    return {"status": "ok"}
