"""CAPTCHA checks for public forms (T2.2.6), through interchangeable providers.

    from common.services import captcha
    captcha.widget()                    # {"provider", "site_key"} for the browser, or None
    captcha.verify(token, remote_ip)    # True, False, or raises CaptchaUnavailable

Pick one with CAPTCHA_PROVIDER and its keys (CAPTCHA_SITE_KEY,
CAPTCHA_SECRET_KEY). Every provider here takes the same server check: POST
secret, response and remoteip to its verify address and read `success`.
To add one, add its verify address to PROVIDERS and its widget to the
frontend's captcha component.
"""

from typing import Optional

import requests
from loguru import logger

from config import FormsEnv as Env

PROVIDERS: dict[str, str] = {
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    "hcaptcha": "https://api.hcaptcha.com/siteverify",
    "recaptcha": "https://www.google.com/recaptcha/api/siteverify",
}

MAX_TOKEN_LENGTH = 4096


class CaptchaUnavailable(Exception):
    """The provider couldn't be reached: the answer is neither yes nor no."""


def provider() -> Optional[str]:
    name = Env.CAPTCHA_PROVIDER
    if not name:
        return None
    if name not in PROVIDERS:
        logger.warning("CAPTCHA_PROVIDER {!r} is not one of {}; CAPTCHA is off", name, sorted(PROVIDERS))
        return None
    if not (Env.CAPTCHA_SITE_KEY and Env.CAPTCHA_SECRET_KEY):
        logger.warning("CAPTCHA_PROVIDER is set without CAPTCHA_SITE_KEY and CAPTCHA_SECRET_KEY; CAPTCHA is off")
        return None
    return name


def is_enabled() -> bool:
    return provider() is not None


def widget() -> Optional[dict[str, str]]:
    name = provider()
    return {"provider": name, "site_key": Env.CAPTCHA_SITE_KEY} if name else None


def verify(token: Optional[str], remote_ip: Optional[str] = None) -> bool:
    name = provider()
    if name is None:
        return True
    if not token or not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
        return False
    data = {"secret": Env.CAPTCHA_SECRET_KEY, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        res = requests.post(PROVIDERS[name], data=data, timeout=Env.CAPTCHA_TIMEOUT_SECONDS)
        res.raise_for_status()
        body = res.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("captcha check with {} failed: {!r}", name, exc)
        raise CaptchaUnavailable(name) from exc
    return bool(isinstance(body, dict) and body.get("success") is True)
