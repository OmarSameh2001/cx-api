from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import models  # noqa: F401  -- register all SQLAlchemy mappers
from common.middleware import AuthenticationMiddleware
from db import engine
from modules.assignments.route import router as assignments_router
from modules.auth.route import router as auth_router
from modules.employees.route import router as employees_router
from modules.forms.route import router as forms_router
from modules.public.route import router as public_router
from modules.roles.route import router as roles_router
from modules.shared.lookup.route import router as lookups_router
from modules.submissions.route import router as submissions_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield


app = FastAPI(title="cx-api", lifespan=lifespan)

app.add_middleware(AuthenticationMiddleware, public_prefixes=["/public/"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(employees_router)
app.include_router(forms_router)
app.include_router(submissions_router)
app.include_router(assignments_router)
app.include_router(roles_router)
app.include_router(lookups_router)
app.include_router(public_router)


@app.get("/")
def health():
    return {"status": "ok"}
