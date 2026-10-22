# Security

## Reporting a vulnerability

Report it privately through GitHub: **Security, Report a vulnerability** on this repository. Please do not open a public issue. You can expect an acknowledgement within a week.

## Supported versions

Only the latest commit on the default branch receives fixes.

## Notes

Set a stable `JWT_SECRET_KEY` and leave `ENABLE_DEMO_ACCOUNT` unset on any reachable server. `/metrics` and the key endpoints require authentication.
