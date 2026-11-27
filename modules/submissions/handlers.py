"""Outbox handlers for submissions (registered through common.events.registry)."""

from common.events.registry import handler
from modules.forms import behaviour
from modules.notifications import service as notifications

from . import repository, service


def notify_on_response(db, event) -> None:
    """Tells the people a form names (T2.2.3) about each finished response,
    on the channels it names. The relay retries it if it fails, and runs it
    once per event."""
    submission = repository.get_submission(db, int(event.payload["submission_id"]))
    if submission is None or submission.form is None:
        return
    form = submission.form
    notify = behaviour.settings_of(form).notify
    if notify is None or not notify.employee_ids:
        return
    anonymous = service.is_anonymous_row(submission)
    params = {"form": form.name}
    if not anonymous:
        params["respondent"] = service.submitter_name(submission) or "-"
    # in the form's own organisation only: recipients() drops anyone else
    notifications.notify(
        db,
        organisation_id=form.organisation_id,
        recipient_ids=notify.employee_ids,
        template="submission.received_anonymous" if anonymous else "submission.received",
        params=params,
        link=f"/submissions/{submission.id}",
        channels=notify.channels,
    )


handler("submission.submitted", "submissions.notify_on_response")(notify_on_response)
handler("submission.late", "submissions.notify_on_response")(notify_on_response)
