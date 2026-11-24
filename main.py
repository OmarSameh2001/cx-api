from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import models  # noqa: F401  -- register all SQLAlchemy mappers
from common.errors import CodedHTTPException, coded_http_exception_handler
from common.middleware import AuthenticationMiddleware, BodySizeLimitMiddleware, RequestContextMiddleware
from db import engine
from modules.assignments.route import router as assignments_router
from modules.audit.route import router as audit_router
from modules.auth.route import router as auth_router
from modules.employees.route import router as employees_router
from modules.files.route import router as files_router
from modules.forms.route import router as forms_router
from modules.jobs.route import router as jobs_router
from modules.notifications.route import router as notifications_router
from modules.organisations.route import router as organisations_router
from modules.public_api.route import router as public_router
from modules.results.route import router as results_router
from modules.roles.route import router as roles_router
from modules.shared.lookup.route import router as lookups_router
from modules.submissions.route import router as submissions_router
from modules.units.route import router as units_router
from modules.ai.route import router as ai_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield


app = FastAPI(title="cx-api", lifespan=lifespan)
app.add_exception_handler(CodedHTTPException, coded_http_exception_handler)

app.add_middleware(AuthenticationMiddleware, public_prefixes=["/public/", "/internal/"])
# answers are small; cap what respondents can send (inside CORS so a 413 still
# carries CORS headers the browser can read)
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=256 * 1024,
    path_prefixes=["/public/", "/submissions"],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://cx-front-azure.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
# outermost: every request, refused ones included, gets a correlation ID
app.add_middleware(RequestContextMiddleware)

app.include_router(auth_router)
app.include_router(employees_router)
app.include_router(forms_router)
app.include_router(submissions_router)
app.include_router(results_router)
app.include_router(assignments_router)
app.include_router(roles_router)
app.include_router(organisations_router)
app.include_router(units_router)
app.include_router(lookups_router)
app.include_router(public_router)
app.include_router(ai_router)
app.include_router(jobs_router)
app.include_router(files_router)
app.include_router(audit_router)
app.include_router(notifications_router)

# Parked (Mentions was dropped; E0.3): the tenants, keywords, mentions,
# platform-config and mention notification routers stay unmounted. Their
# modules and tables are kept.


@app.get("/")
def health():
    return {"status": "ok"}
