"""SMS and WhatsApp providers. Numbers are E.164 (+966501234567)."""

import uuid

from loguru import logger

from .base import ConfigError, Message, MessagingError, Provider, SendResult
from .http import json_or_empty, post
from .registry import provider


def _twilio(p: Provider, message: Message, sender: str, to: str) -> SendResult:
    sid, token = p.config.require("ACCOUNT_SID", "AUTH_TOKEN")
    data = {"To": to, "Body": message.text}
    service = p.config.get("MESSAGING_SERVICE_SID")
    if service:
        data["MessagingServiceSid"] = service
    else:
        data["From"] = sender
    res = post(p.name, f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data, auth=(sid, token))
    return SendResult(p.name, json_or_empty(res).get("sid"))


@provider("sms", "twilio")
class TwilioSms(Provider):
    """Twilio: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM (a
    number or sender ID) or TWILIO_MESSAGING_SERVICE_SID."""

    def send(self, message: Message) -> SendResult:
        sender = self.config.get("FROM")
        if not sender and not self.config.get("MESSAGING_SERVICE_SID"):
            raise ConfigError("TWILIO_FROM or TWILIO_MESSAGING_SERVICE_SID must be set", provider=self.name)
        return _twilio(self, message, sender or "", message.to)


@provider("whatsapp", "twilio")
class TwilioWhatsapp(Provider):
    """Twilio WhatsApp: the TWILIO_* settings, and TWILIO_WHATSAPP_FROM (an
    approved WhatsApp sender number)."""

    def send(self, message: Message) -> SendResult:
        (sender,) = self.config.require("WHATSAPP_FROM")
        return _twilio(self, message, f"whatsapp:{sender}", f"whatsapp:{message.to}")


@provider("sms", "vonage")
class VonageSms(Provider):
    """Vonage (Nexmo): VONAGE_API_KEY, VONAGE_API_SECRET, VONAGE_FROM."""

    def send(self, message: Message) -> SendResult:
        key, secret, sender = self.config.require("API_KEY", "API_SECRET", "FROM")
        res = post(self.name, "https://rest.nexmo.com/sms/json", data={
            "api_key": key, "api_secret": secret, "from": sender, "to": message.to.lstrip("+"),
            "text": message.text, "type": "unicode",
            **({"client-ref": message.reference} if message.reference else {}),
        })
        # Vonage answers 200 with a per-message status: "0" is sent
        first = (json_or_empty(res).get("messages") or [{}])[0]
        if str(first.get("status")) != "0":
            # 1 throttled, 5 internal error: worth retrying; the rest are the request's fault
            permanent = str(first.get("status")) not in ("1", "5")
            raise MessagingError(f"vonage: {first.get('error-text', 'not sent')}", permanent=permanent,
                                 provider=self.name)
        return SendResult(self.name, first.get("message-id"))


@provider("sms", "unifonic")
class UnifonicSms(Provider):
    """Unifonic (Saudi Arabia and the Gulf): UNIFONIC_APP_SID,
    UNIFONIC_SENDER_ID."""

    def send(self, message: Message) -> SendResult:
        app_sid, sender = self.config.require("APP_SID", "SENDER_ID")
        res = post(self.name, "https://el.cloud.unifonic.com/rest/SMS/messages", data={
            "AppSid": app_sid, "SenderID": sender, "Recipient": message.to.lstrip("+"), "Body": message.text,
        })
        body = json_or_empty(res)
        if body.get("success") in (False, "false"):
            raise MessagingError(f"unifonic: {body.get('message') or body.get('errorCode')}", permanent=True,
                                 provider=self.name)
        return SendResult(self.name, str((body.get("data") or {}).get("MessageID") or "") or None)


@provider("whatsapp", "meta")
class MetaWhatsapp(Provider):
    """WhatsApp Cloud API: META_WHATSAPP_TOKEN, META_WHATSAPP_PHONE_NUMBER_ID,
    META_WHATSAPP_API_VERSION (v21.0). Free text only reaches people who
    wrote to you in the last 24 hours; otherwise pass an approved template
    in Message.extra: {"whatsapp_template": "name", "whatsapp_params": [...]}.
    """

    def send(self, message: Message) -> SendResult:
        token, number_id = self.config.require("TOKEN", "PHONE_NUMBER_ID")
        version = self.config.get("API_VERSION") or "v21.0"
        payload: dict = {"messaging_product": "whatsapp", "to": message.to.lstrip("+")}
        template = message.extra.get("whatsapp_template")
        if template:
            params = [{"type": "text", "text": str(v)} for v in message.extra.get("whatsapp_params") or []]
            payload.update(type="template", template={
                "name": template, "language": {"code": message.locale},
                **({"components": [{"type": "body", "parameters": params}]} if params else {}),
            })
        else:
            payload.update(type="text", text={"body": message.text})
        res = post(self.name, f"https://graph.facebook.com/{version}/{number_id}/messages", json=payload,
                   headers={"Authorization": f"Bearer {token}"})
        first = (json_or_empty(res).get("messages") or [{}])[0]
        return SendResult(self.name, first.get("id"))


@provider("sms", "log")
class LogSms(Provider):
    def send(self, message: Message) -> SendResult:
        logger.info("sms (not sent) to {}: {}", message.to, message.text)
        return SendResult(self.name, f"log-{uuid.uuid4()}")


@provider("whatsapp", "log")
class LogWhatsapp(Provider):
    def send(self, message: Message) -> SendResult:
        logger.info("whatsapp (not sent) to {}: {}", message.to, message.text)
        return SendResult(self.name, f"log-{uuid.uuid4()}")
