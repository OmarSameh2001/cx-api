from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from db import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield


app = FastAPI(title="cx-api", lifespan=lifespan)


@app.get("/")
def health():
    return {"status": "ok"}
