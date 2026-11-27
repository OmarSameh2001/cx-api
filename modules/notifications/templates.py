"""Message templates, in English and Arabic (T1.9.4).

A notification stores only its template key and parameters; the words are
rendered when it is read (in the reader's language) or sent. So a fixed
translation shows up on old notifications too, and nothing is stored twice.

Each template has, per language:
  title    the bell's headline, the email subject and the SMS/WhatsApp text
  body     the longer text (in-app list, email body)
Placeholders are {name}; a missing parameter renders as nothing, and a
{channel} parameter (in_app, email...) shows as that channel's name in the
reader's language. To add a template, add an entry here with both languages.
"""

import html
import string
from dataclasses import dataclass
from typing import Any, Mapping

LOCALES = ("en", "ar")
RTL = {"ar"}


@dataclass(frozen=True)
class Text:
    title: str
    body: str


TEMPLATES: dict[str, dict[str, Text]] = {
    # sent from the notification settings to check a channel works
    "system.test": {
        "en": Text("Test notification", "This is a test from {app}. If you can read it, {channel} notifications work."),
        "ar": Text("إشعار تجريبي", "هذه رسالة تجريبية من {app}. إذا وصلتك، فإشعارات {channel} تعمل."),
    },
    # free text written by a person or a workflow step
    "system.message": {
        "en": Text("{title}", "{body}"),
        "ar": Text("{title}", "{body}"),
    },
    "submission.received": {
        "en": Text("New response to {form}", "{respondent} answered {form}."),
        "ar": Text("رد جديد على {form}", "قام {respondent} بالإجابة على {form}."),
    },
    # an anonymous form's response: nobody to name
    "submission.received_anonymous": {
        "en": Text("New response to {form}", "Someone answered {form}. The form is anonymous."),
        "ar": Text("رد جديد على {form}", "أجاب أحدهم على {form}. هذا النموذج بدون أسماء."),
    },
    "form.assigned": {
        "en": Text("New form to answer: {form}", "{form} was assigned to you. Please answer it by {due}."),
        "ar": Text("نموذج جديد للإجابة: {form}", "تم إسناد {form} إليك. يرجى الإجابة عليه قبل {due}."),
    },
    "task.assigned": {
        "en": Text("New task: {task}", "{task} was assigned to you. It is due {due}."),
        "ar": Text("مهمة جديدة: {task}", "تم إسناد المهمة {task} إليك. موعد التسليم {due}."),
    },
    # a way into someone's account was added or removed (E1.11)
    "security.identity_linked": {
        "en": Text(
            "{provider} sign-in added",
            "A {provider} account ({email}) can now be used to sign in to your account. "
            "If this wasn't you, remove it from your profile and change your password.",
        ),
        "ar": Text(
            "تمت إضافة تسجيل الدخول عبر {provider}",
            "أصبح بإمكان حساب {provider} ({email}) تسجيل الدخول إلى حسابك. "
            "إذا لم تكن أنت من قام بذلك، فأزله من ملفك الشخصي وغيّر كلمة المرور.",
        ),
    },
    "security.identity_unlinked": {
        "en": Text(
            "{provider} sign-in removed",
            "Your {provider} account can no longer be used to sign in. If this wasn't you, change your password.",
        ),
        "ar": Text(
            "تمت إزالة تسجيل الدخول عبر {provider}",
            "لم يعد بإمكان حساب {provider} تسجيل الدخول إلى حسابك. إذا لم تكن أنت من قام بذلك، فغيّر كلمة المرور.",
        ),
    },
    "task.overdue": {
        "en": Text("Overdue: {task}", "{task} was due {due} and is not done yet."),
        "ar": Text("متأخرة: {task}", "كان موعد المهمة {task} في {due} ولم تُنجز بعد."),
    },
}

CHANNEL_NAMES = {
    "en": {"in_app": "in-app", "email": "email", "sms": "SMS", "whatsapp": "WhatsApp", "slack": "Slack"},
    "ar": {"in_app": "داخل التطبيق", "email": "البريد الإلكتروني", "sms": "الرسائل النصية",
           "whatsapp": "واتساب", "slack": "سلاك"},
}


def _fill(text: str, params: Mapping[str, Any]) -> str:
    # only {name} placeholders; attribute and index lookups ({a.b}, {a[0]})
    # are not allowed, so parameters can't reach into objects
    out = []
    for literal, field, _spec, _conversion in string.Formatter().parse(text):
        out.append(literal)
        if field is not None:
            if not field.isidentifier():
                raise ValueError(f"bad placeholder {{{field}}}")
            out.append(str(params.get(field, "")))
    return "".join(out)


def exists(key: str) -> bool:
    return key in TEMPLATES


def locale_or_default(locale: str | None, default: str) -> str:
    if locale:
        short = locale.split("-")[0].split("_")[0].lower()
        if short in LOCALES:
            return short
    return default


def render(key: str, params: Mapping[str, Any] | None, locale: str) -> Text:
    """The template's words in `locale` (English when it has none), filled in."""
    texts = TEMPLATES.get(key)
    if texts is None:
        return Text(key, "")
    text = texts.get(locale) or texts["en"]
    values = {k: v for k, v in (params or {}).items() if v is not None}
    if "channel" in values:
        names = CHANNEL_NAMES.get(locale) or CHANNEL_NAMES["en"]
        values["channel"] = names.get(str(values["channel"]), values["channel"])
    return Text(_fill(text.title, values).strip(), _fill(text.body, values).strip())


def email_html(text: Text, *, locale: str, link: str | None, app_name: str) -> str:
    """A plain, inline-styled email (mail clients ignore stylesheets),
    right-to-left for Arabic."""
    direction = "rtl" if locale in RTL else "ltr"
    align = "right" if direction == "rtl" else "left"
    button = ""
    if link:
        label = "فتح" if locale == "ar" else "Open"
        button = (
            f'<p style="margin:24px 0 0"><a href="{html.escape(link, quote=True)}" '
            f'style="background:#2563eb;color:#ffffff;padding:10px 18px;border-radius:6px;'
            f'text-decoration:none;display:inline-block">{label}</a></p>'
        )
    body = "<br>".join(html.escape(line) for line in text.body.splitlines())
    return (
        f'<!doctype html><html lang="{locale}" dir="{direction}"><body style="margin:0;padding:24px;'
        f'background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a">'
        f'<div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;'
        f'border-radius:8px;padding:24px;text-align:{align}">'
        f'<h1 style="font-size:18px;margin:0 0 12px">{html.escape(text.title)}</h1>'
        f'<p style="font-size:14px;line-height:1.6;margin:0">{body}</p>{button}'
        f'<p style="font-size:12px;color:#64748b;margin:24px 0 0">{html.escape(app_name)}</p>'
        f"</div></body></html>"
    )


def plain_text(text: Text, *, link: str | None) -> str:
    return "\n\n".join(p for p in (text.title, text.body, link) if p)


def short_text(text: Text, *, link: str | None) -> str:
    """For SMS and WhatsApp: the headline, the body and the link, kept short."""
    parts = [text.title]
    if text.body and text.body != text.title:
        parts.append(text.body)
    if link:
        parts.append(link)
    return "\n".join(parts)[:900]
