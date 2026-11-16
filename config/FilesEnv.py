import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


# "s3" (any S3-compatible store: Supabase Storage, Cloudflare R2, AWS) or
# "cloudinary". New uploads go to this provider; each file remembers its own,
# so switching keeps old files readable as long as both are configured.
STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER", "s3").strip().lower()

# --- S3 / Supabase Storage ---------------------------------------------------
# Supabase: Storage > Settings > S3 connection. Endpoint looks like
# https://<project>.supabase.co/storage/v1/s3, and the bucket must be private.
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "").strip() or None
S3_REGION = os.getenv("S3_REGION", "eu-west-1").strip()
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "").strip()
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "").strip()
S3_BUCKET = os.getenv("S3_BUCKET", "cx-files").strip()

# --- Cloudinary ----------------------------------------------------------------
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()

# --- limits ----------------------------------------------------------------------
# Nothing is ever accepted above this, whatever the limits table says.
FILES_HARD_MAX_MB = _int("FILES_HARD_MAX_MB", "50")
# images larger than this many pixels are refused by the image service
# (a small file can still decode to a huge bitmap)
IMAGE_MAX_PIXELS = _int("IMAGE_MAX_PIXELS", "40000000")

# --- links -----------------------------------------------------------------------
FILES_UPLOAD_URL_TTL_SECONDS = _int("FILES_UPLOAD_URL_TTL_SECONDS", "900")
FILES_LINK_TTL_SECONDS = _int("FILES_LINK_TTL_SECONDS", "300")

# --- cleanup -------------------------------------------------------------------
# uploads never completed, and completed files never attached to anything,
# are deleted after these
FILES_PENDING_TTL_MINUTES = _int("FILES_PENDING_TTL_MINUTES", "60")
FILES_UNATTACHED_TTL_HOURS = _int("FILES_UNATTACHED_TTL_HOURS", "24")
FILES_CLEANUP_SECONDS = _int("FILES_CLEANUP_SECONDS", "3600")
FILES_CLEANUP_BATCH_SIZE = _int("FILES_CLEANUP_BATCH_SIZE", "200")

# --- public forms ------------------------------------------------------------------
PUBLIC_UPLOADS_PER_MINUTE_PER_IP = _int("PUBLIC_UPLOADS_PER_MINUTE_PER_IP", "20")
PUBLIC_UPLOADS_PER_HOUR_PER_FORM_IP = _int("PUBLIC_UPLOADS_PER_HOUR_PER_FORM_IP", "60")
