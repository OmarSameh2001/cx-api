import os

from dotenv import load_dotenv

load_dotenv()

# How often the relay runs. With JOBS_RUNNER=inline the cron tick is the
# floor (about a minute); with Celery, Beat can run it every few seconds.
EVENTS_RELAY_SECONDS = int(os.getenv("EVENTS_RELAY_SECONDS", "60"))
# events handled per relay run, and a time budget so an inline tick (which
# runs inside a Vercel request) always finishes; the rest wait for the next run
EVENTS_RELAY_BATCH_SIZE = int(os.getenv("EVENTS_RELAY_BATCH_SIZE", "100"))
EVENTS_RELAY_MAX_SECONDS = float(os.getenv("EVENTS_RELAY_MAX_SECONDS", "20"))
# a handler that keeps failing is retried with backoff (1 min, 2, 4...) up to
# this many times, then logged to failed_jobs and given up on
EVENTS_MAX_ATTEMPTS = int(os.getenv("EVENTS_MAX_ATTEMPTS", "5"))
EVENTS_RETRY_BACKOFF_MAX_SECONDS = int(os.getenv("EVENTS_RETRY_BACKOFF_MAX_SECONDS", "3600"))
# handled events (and their processed_events rows) are deleted after this
EVENTS_RETENTION_DAYS = int(os.getenv("EVENTS_RETENTION_DAYS", "30"))
EVENTS_PURGE_SECONDS = int(os.getenv("EVENTS_PURGE_SECONDS", "86400"))
