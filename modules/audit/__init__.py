"""Audit log. Other modules record through the service:

    from modules.audit import service as audit
    audit.record(db, "form.published", entity=form, data={"version": 3})
"""
