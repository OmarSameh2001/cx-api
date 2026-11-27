import os
from typing import Literal, cast

from dotenv import load_dotenv

load_dotenv()

SameSite = Literal["lax", "strict", "none"]


JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-change-me")
JWT_REFRESH_SECRET = os.getenv("JWT_REFRESH_SECRET", JWT_SECRET + ":refresh")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ISSUER = os.getenv("JWT_ISSUER", "cx-api")

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
MAX_REFRESH_TOKENS_PER_USER = int(os.getenv("MAX_REFRESH_TOKENS_PER_USER", "5"))

REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "refresh_token")
REFRESH_COOKIE_PATH = os.getenv("REFRESH_COOKIE_PATH", "/auth")
ACCESS_COOKIE_NAME = os.getenv("ACCESS_COOKIE_NAME", "access_token")
ACCESS_COOKIE_PATH = os.getenv("ACCESS_COOKIE_PATH", "/")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
_samesite = os.getenv("COOKIE_SAMESITE", "lax").lower()
if _samesite not in ("lax", "strict", "none"):
    _samesite = "lax"
COOKIE_SAMESITE = cast(SameSite, _samesite)
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None

# How many proxies in front of the API add an X-Forwarded-For entry (Vercel:
# 1). The caller's IP is the entry that many places from the right; entries
# further left were sent by the client and can be anything. 0 ignores the
# header (the API is reached directly), so nobody can pick their own IP to
# get round the per-IP limits.
TRUSTED_PROXY_COUNT = max(0, int(os.getenv("TRUSTED_PROXY_COUNT", "1")))
