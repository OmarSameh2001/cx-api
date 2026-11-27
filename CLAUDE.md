# cx-api
- Every endpoint lives in modules/<name>/, split into route, controller, service, model, dto and repository. Routes only wire things together, services hold the rules, and repositories hold the queries.
- Scope every query to the caller's organisation_id from the token. Another organisation's record is a 404, not a 403. Every new router gets an isolation test.
- Permissions: use `@require_permission("resource:action")` with names from modules/roles/permissions.py. That file is the whole catalogue; there's no API to add one. Platform-wide features use `Depends(platform_admin)`.
- Errors: `raise AppError(status, "module.code")`, with the message in common/i18n/messages/en and ar.
- Changes people make go to the audit log with `audit.record`. Events use `events.emit` inside the same transaction as the data.
- Tests use the FakeSession in tests/conftest.py and stub repository functions. They never touch a real database.
