"""Form settings that live on the server, not on each form (E2.2)."""

import os

from dotenv import load_dotenv

from config import AuthEnv

load_dotenv()


def _int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


# Signs prefilled links, resume links, edit links and shuffle seeds. Changing
# it ends every link already handed out.
FORM_LINK_SECRET = os.getenv("FORM_LINK_SECRET", AuthEnv.JWT_SECRET + ":forms")

# A public respondent's saved draft (save and continue later) expires this
# many days after it was last saved.
PUBLIC_DRAFT_TTL_DAYS = _int("PUBLIC_DRAFT_TTL_DAYS", "30")

# CAPTCHA on public forms: turnstile, hcaptcha or recaptcha (v2). Unset, no
# form asks for one. The site key goes to the browser; the secret never does.
CAPTCHA_PROVIDER = os.getenv("CAPTCHA_PROVIDER", "").strip().lower()
CAPTCHA_SITE_KEY = os.getenv("CAPTCHA_SITE_KEY", "").strip()
CAPTCHA_SECRET_KEY = os.getenv("CAPTCHA_SECRET_KEY", "").strip()
CAPTCHA_TIMEOUT_SECONDS = _int("CAPTCHA_TIMEOUT_SECONDS", "5")
