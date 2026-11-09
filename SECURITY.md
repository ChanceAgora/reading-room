# Security reporting

The Reading Room is a localhost-only, single-user technical preview. It is not designed to be exposed publicly, tunneled to other users, or deployed as an authenticated hosted service.

For a sensitive vulnerability, use [GitHub private vulnerability reporting](https://github.com/sethwilsonUS/reading-room/security/advisories/new) when available. If that route is unavailable, open an issue asking for a private reporting channel without including exploit details or sensitive material. Reports are handled on a best-effort basis; no response-time commitment is offered.

Include the affected version, expected boundary, observed behavior, and a minimal synthetic reproduction. Useful areas include source HTML/XML handling, archive paths, local Host/Origin checks, credentials, unintended paid requests, and publication leaks. Do not attach real books, private excerpts, library state, keys, cookies, or unredacted logs.

Books and extracted content are untrusted input. They must not execute scripts, fetch hidden network resources, or escape the selected library. API keys stay server-side, and the application's cost ledger is not an account-wide billing security boundary.

For normal functional and accessibility bugs, use the public issue tracker with sanitized details. See [Contributing](CONTRIBUTING.md).
