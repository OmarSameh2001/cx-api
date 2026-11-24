import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


# the name in messages and email footers, and the frontend address that
# notification links are relative to
APP_NAME = os.getenv("APP_NAME", "CX").strip()
APP_URL = os.getenv("APP_URL", "http://localhost:3000").strip().rstrip("/")
# language of messages sent to people who haven't chosen one: en or ar
NOTIFICATIONS_DEFAULT_LOCALE = os.getenv("NOTIFICATIONS_DEFAULT_LOCALE", "en").strip().lower()

# Which providers each channel uses, in order, is <CHANNEL>_PROVIDERS
# (EMAIL_PROVIDERS, SMS_PROVIDERS, WHATSAPP_PROVIDERS, SLACK_PROVIDERS);
# see common/services/messaging. A channel with none is off.

# --- delivery (the worker) ---------------------------------------------------------
NOTIFICATIONS_DELIVER_SECONDS = _int("NOTIFICATIONS_DELIVER_SECONDS", "60")
NOTIFICATIONS_DELIVER_BATCH_SIZE = _int("NOTIFICATIONS_DELIVER_BATCH_SIZE", "50")
# a send that fails is tried again after 1, 2, 4... minutes, up to this many
# attempts, then marked failed
NOTIFICATIONS_MAX_ATTEMPTS = _int("NOTIFICATIONS_MAX_ATTEMPTS", "5")
NOTIFICATIONS_RETRY_BACKOFF_MAX_SECONDS = _int("NOTIFICATIONS_RETRY_BACKOFF_MAX_SECONDS", "3600")
# a delivery stuck "sending" this long (the worker died mid-send) is tried again
NOTIFICATIONS_SENDING_TIMEOUT_SECONDS = _int("NOTIFICATIONS_SENDING_TIMEOUT_SECONDS", "600")

# --- keeping storage small -------------------------------------------------------
# read in-app notifications, and finished deliveries, are deleted after these
NOTIFICATIONS_READ_RETENTION_DAYS = _int("NOTIFICATIONS_READ_RETENTION_DAYS", "90")
NOTIFICATIONS_UNREAD_RETENTION_DAYS = _int("NOTIFICATIONS_UNREAD_RETENTION_DAYS", "365")
NOTIFICATIONS_DELIVERY_RETENTION_DAYS = _int("NOTIFICATIONS_DELIVERY_RETENTION_DAYS", "30")
NOTIFICATIONS_PURGE_SECONDS = _int("NOTIFICATIONS_PURGE_SECONDS", "86400")
