"""Sending messages on any channel through interchangeable providers.

    from common.services import messaging
    messaging.send(messaging.Message(channel="email", to="a@b.co", subject="Hi", text="Hello"))

Providers per channel (pick and order them with <CHANNEL>_PROVIDERS):
  email:    smtp, ses, resend, sendgrid, mailgun, postmark, brevo, log
  sms:      twilio, vonage, unifonic, log
  whatsapp: twilio, meta, log
  slack:    webhook, bot, log
See registry.py for how fallback works and how to add one.
"""

from .base import CHANNELS, ConfigError, Message, MessagingError, Provider, ProviderConfig, SendResult
from .registry import available, configured, get, is_enabled, provider, reset_for_tests, send

__all__ = [
    "CHANNELS", "ConfigError", "Message", "MessagingError", "Provider", "ProviderConfig", "SendResult",
    "available", "configured", "get", "is_enabled", "provider", "reset_for_tests", "send",
]
