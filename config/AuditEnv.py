import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


# --- what one entry may hold ---------------------------------------------------
# text values in the change log are cut to this many characters, lists to
# this many items; a value that is still too large is replaced by its size
AUDIT_MAX_TEXT_CHARS = _int("AUDIT_MAX_TEXT_CHARS", "200")
AUDIT_MAX_LIST_ITEMS = _int("AUDIT_MAX_LIST_ITEMS", "50")
AUDIT_MAX_VALUE_BYTES = _int("AUDIT_MAX_VALUE_BYTES", "2000")

# --- failed sign-ins -------------------------------------------------------------
# this many failures from one IP within the window raise the next one to "error"
AUDIT_FAILED_LOGIN_ALERT = _int("AUDIT_FAILED_LOGIN_ALERT", "5")
AUDIT_FAILED_LOGIN_WINDOW_MINUTES = _int("AUDIT_FAILED_LOGIN_WINDOW_MINUTES", "15")

# --- retention, in days, per severity (0 keeps entries for ever) ----------------
# the purge job deletes older entries; it is the only thing that may
AUDIT_RETENTION_DAYS = {
    "debug": _int("AUDIT_RETENTION_DAYS_DEBUG", "30"),
    "info": _int("AUDIT_RETENTION_DAYS_INFO", "365"),
    "notice": _int("AUDIT_RETENTION_DAYS_NOTICE", "730"),
    "warning": _int("AUDIT_RETENTION_DAYS_WARNING", "1095"),
    "error": _int("AUDIT_RETENTION_DAYS_ERROR", "1095"),
    "critical": _int("AUDIT_RETENTION_DAYS_CRITICAL", "0"),
}
AUDIT_PURGE_SECONDS = _int("AUDIT_PURGE_SECONDS", "86400")
# rows deleted per statement, so one purge never holds a long lock
AUDIT_PURGE_BATCH_SIZE = _int("AUDIT_PURGE_BATCH_SIZE", "5000")
