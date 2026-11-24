"""Email providers. Each reads `<PREFIX>_*` settings (see ENVIRONMENT.md).
The sender is EMAIL_FROM ("CX <no-reply@example.com>") unless a provider's
own `<PREFIX>_FROM` is set; replies go to EMAIL_REPLY_TO when set."""

import os
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Optional

from loguru import logger

from .base import ConfigError, Message, MessagingError, Provider, SendResult
from .http import json_or_empty, post
from .registry import provider


def _sender(p: Provider) -> str:
    sender = p.config.get("FROM") or os.getenv("EMAIL_FROM", "").strip()
    if not sender:
        raise ConfigError("EMAIL_FROM must be set", provider=p.name)
    return sender


def _reply_to() -> Optional[str]:
    return os.getenv("EMAIL_REPLY_TO", "").strip() or None


def _split(address: str) -> tuple[str, str]:
    name, email = parseaddr(address)
    return name, email


@provider("email", "smtp")
class SmtpEmail(Provider):
    """Any SMTP server: SMTP_HOST, SMTP_PORT (587), SMTP_USERNAME,
    SMTP_PASSWORD, SMTP_SECURITY = starttls (default) | ssl | none."""

    def send(self, message: Message) -> SendResult:
        (host,) = self.config.require("HOST")
        security = (self.config.get("SECURITY") or "starttls").lower()
        port = self.config.int("PORT", 465 if security == "ssl" else 587)
        email = EmailMessage()
        email["From"] = _sender(self)
        email["To"] = message.to
        email["Subject"] = message.subject or ""
        if _reply_to():
            email["Reply-To"] = _reply_to()
        message_id = make_msgid(domain=_split(_sender(self))[1].partition("@")[2] or None)
        email["Message-ID"] = message_id
        email.set_content(message.text)
        if message.html:
            email.add_alternative(message.html, subtype="html")
        try:
            context = ssl.create_default_context()
            if security == "ssl":
                server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
            else:
                server = smtplib.SMTP(host, port, timeout=20)
            with server:
                if security == "starttls":
                    server.starttls(context=context)
                username = self.config.get("USERNAME")
                if username:
                    server.login(username, self.config.get("PASSWORD") or "")
                server.send_message(email)
        except smtplib.SMTPRecipientsRefused as exc:
            raise MessagingError(f"smtp: recipient refused: {exc}", permanent=True, provider=self.name) from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise ConfigError(f"smtp: authentication failed: {exc}", provider=self.name) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise MessagingError(f"smtp: {exc}", provider=self.name) from exc
        return SendResult(self.name, message_id)


@provider("email", "ses")
class SesEmail(Provider):
    """Amazon SES (API v2): SES_REGION, and SES_ACCESS_KEY_ID /
    SES_SECRET_ACCESS_KEY (or the usual AWS credentials chain)."""

    def send(self, message: Message) -> SendResult:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError

        client = boto3.client(
            "sesv2",
            region_name=self.config.get("REGION") or os.getenv("AWS_REGION") or "eu-west-1",
            aws_access_key_id=self.config.get("ACCESS_KEY_ID"),
            aws_secret_access_key=self.config.get("SECRET_ACCESS_KEY"),
        )
        body = {"Text": {"Data": message.text, "Charset": "UTF-8"}}
        if message.html:
            body["Html"] = {"Data": message.html, "Charset": "UTF-8"}
        request = {
            "FromEmailAddress": _sender(self),
            "Destination": {"ToAddresses": [message.to]},
            "Content": {"Simple": {"Subject": {"Data": message.subject or "", "Charset": "UTF-8"}, "Body": body}},
        }
        if _reply_to():
            request["ReplyToAddresses"] = [_reply_to()]
        if self.config.get("CONFIGURATION_SET"):
            request["ConfigurationSetName"] = self.config.get("CONFIGURATION_SET")
        try:
            res = client.send_email(**request)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            permanent = code in ("MessageRejected", "MailFromDomainNotVerifiedException", "AccountSuspendedException",
                                 "BadRequestException", "NotFoundException")
            raise MessagingError(f"ses: {code}: {exc}", permanent=permanent, provider=self.name) from exc
        except BotoCoreError as exc:
            raise MessagingError(f"ses: {exc}", provider=self.name) from exc
        return SendResult(self.name, res.get("MessageId"))


@provider("email", "resend")
class ResendEmail(Provider):
    """Resend: RESEND_API_KEY."""

    def send(self, message: Message) -> SendResult:
        (key,) = self.config.require("API_KEY")
        payload = {"from": _sender(self), "to": [message.to], "subject": message.subject or "", "text": message.text}
        if message.html:
            payload["html"] = message.html
        if _reply_to():
            payload["reply_to"] = _reply_to()
        headers = {"Authorization": f"Bearer {key}"}
        if message.reference:  # the same delivery is never sent twice by Resend
            headers["Idempotency-Key"] = message.reference
        res = post(self.name, "https://api.resend.com/emails", json=payload, headers=headers)
        return SendResult(self.name, json_or_empty(res).get("id"))


@provider("email", "sendgrid")
class SendgridEmail(Provider):
    """SendGrid: SENDGRID_API_KEY."""

    def send(self, message: Message) -> SendResult:
        (key,) = self.config.require("API_KEY")
        name, email = _split(_sender(self))
        content = [{"type": "text/plain", "value": message.text}]
        if message.html:
            content.append({"type": "text/html", "value": message.html})
        payload = {
            "personalizations": [{"to": [{"email": message.to}]}],
            "from": {"email": email, **({"name": name} if name else {})},
            "subject": message.subject or "",
            "content": content,
        }
        if _reply_to():
            payload["reply_to"] = {"email": _split(_reply_to())[1]}
        if message.reference:
            payload["custom_args"] = {"reference": message.reference}
        res = post(self.name, "https://api.sendgrid.com/v3/mail/send", json=payload,
                   headers={"Authorization": f"Bearer {key}"})
        return SendResult(self.name, res.headers.get("X-Message-Id"))


@provider("email", "mailgun")
class MailgunEmail(Provider):
    """Mailgun: MAILGUN_API_KEY, MAILGUN_DOMAIN, MAILGUN_REGION = us | eu."""

    def send(self, message: Message) -> SendResult:
        key, domain = self.config.require("API_KEY", "DOMAIN")
        base = "https://api.eu.mailgun.net" if (self.config.get("REGION") or "us").lower() == "eu" else "https://api.mailgun.net"
        data = {"from": _sender(self), "to": message.to, "subject": message.subject or "", "text": message.text}
        if message.html:
            data["html"] = message.html
        if _reply_to():
            data["h:Reply-To"] = _reply_to()
        if message.reference:
            data["v:reference"] = message.reference
        res = post(self.name, f"{base}/v3/{domain}/messages", data=data, auth=("api", key))
        return SendResult(self.name, json_or_empty(res).get("id"))


@provider("email", "postmark")
class PostmarkEmail(Provider):
    """Postmark: POSTMARK_SERVER_TOKEN, POSTMARK_MESSAGE_STREAM (outbound)."""

    def send(self, message: Message) -> SendResult:
        (token,) = self.config.require("SERVER_TOKEN")
        payload = {
            "From": _sender(self), "To": message.to, "Subject": message.subject or "",
            "TextBody": message.text, "MessageStream": self.config.get("MESSAGE_STREAM") or "outbound",
        }
        if message.html:
            payload["HtmlBody"] = message.html
        if _reply_to():
            payload["ReplyTo"] = _reply_to()
        if message.reference:
            payload["Metadata"] = {"reference": message.reference}
        res = post(self.name, "https://api.postmarkapp.com/email", json=payload,
                   headers={"X-Postmark-Server-Token": token, "Accept": "application/json"})
        return SendResult(self.name, json_or_empty(res).get("MessageID"))


@provider("email", "brevo")
class BrevoEmail(Provider):
    """Brevo (Sendinblue): BREVO_API_KEY."""

    def send(self, message: Message) -> SendResult:
        (key,) = self.config.require("API_KEY")
        name, email = _split(_sender(self))
        payload = {
            "sender": {"email": email, **({"name": name} if name else {})},
            "to": [{"email": message.to}],
            "subject": message.subject or "",
            "textContent": message.text,
        }
        if message.html:
            payload["htmlContent"] = message.html
        if _reply_to():
            payload["replyTo"] = {"email": _split(_reply_to())[1]}
        res = post(self.name, "https://api.brevo.com/v3/smtp/email", json=payload,
                   headers={"api-key": key, "Accept": "application/json"})
        return SendResult(self.name, json_or_empty(res).get("messageId"))


@provider("email", "log")
class LogEmail(Provider):
    """Writes the email to the log instead of sending it: for local work and
    tests. Never configure it in production."""

    def send(self, message: Message) -> SendResult:
        logger.info("email (not sent) to {}: {}\n{}", message.to, message.subject, message.text)
        return SendResult(self.name, f"log-{uuid.uuid4()}")
