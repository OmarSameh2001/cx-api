"""Team chat providers."""

import uuid

from loguru import logger

from .base import ConfigError, Message, MessagingError, Provider, SendResult
from .http import post
from .registry import provider


@provider("slack", "webhook")
class SlackWebhook(Provider):
    """A Slack incoming webhook: SLACK_WEBHOOK_URL, or the message's `to`
    when it is a webhook URL (one per organisation or channel)."""

    def send(self, message: Message) -> SendResult:
        url = message.to if message.to.startswith("https://hooks.slack.com/") else self.config.get("WEBHOOK_URL")
        if not url:
            raise ConfigError("SLACK_WEBHOOK_URL must be set", provider=self.name)
        text = f"*{message.subject}*\n{message.text}" if message.subject else message.text
        post(self.name, url, json={"text": text})
        return SendResult(self.name, None)


@provider("slack", "bot")
class SlackBot(Provider):
    """A Slack app's bot token: SLACK_BOT_TOKEN; `to` is a channel id or
    name, else SLACK_DEFAULT_CHANNEL."""

    def send(self, message: Message) -> SendResult:
        (token,) = self.config.require("BOT_TOKEN")
        channel = message.to or self.config.get("DEFAULT_CHANNEL")
        if not channel:
            raise ConfigError("no Slack channel: pass one or set SLACK_DEFAULT_CHANNEL", provider=self.name)
        text = f"*{message.subject}*\n{message.text}" if message.subject else message.text
        res = post(self.name, "https://slack.com/api/chat.postMessage", json={"channel": channel, "text": text},
                   headers={"Authorization": f"Bearer {token}"})
        body = res.json() if res.content else {}
        if not body.get("ok"):
            error = body.get("error", "unknown error")
            raise MessagingError(f"slack: {error}", permanent=error not in ("ratelimited", "internal_error"),
                                 provider=self.name)
        return SendResult(self.name, body.get("ts"))


@provider("slack", "log")
class LogSlack(Provider):
    def send(self, message: Message) -> SendResult:
        logger.info("slack (not sent) to {}: {}", message.to or "default", message.text)
        return SendResult(self.name, f"log-{uuid.uuid4()}")
