# Release procedure and verification record

The public preview is a source release of `sethwilsonUS/reading-room`. A release is ready when the documented clean installation works, private material is absent from the actual published tree and archives, and known limitations are stated accurately.

## Before tagging

1. Run the Python, frontend, browser, documentation, and public-content checks described in [development](development.md).
2. Install from a clean source archive in a path containing spaces, using a separate synthetic library. Follow the quickstart without borrowing a developer's existing configuration or keys.
3. Exercise a no-key setup and a dummy-key-without-consent setup. Neither may contact a paid provider or reserve costs.
4. Test each paid-feature permission combination with fake providers, accepted budgets, interrupted stages, and restored legacy state. Verify that completed work is not replayed and disabling a feature preserves caches/history.
5. Check cross-project skill invocation without an activated environment. Test installer conflicts, idempotent install/uninstall, and missing/moved checkouts.
6. Exercise the primary workflow with the keyboard and record any screen-reader verification separately. VoiceOver listening is an explicitly accepted follow-up for this technical preview; do not infer a listening result from an accessibility tree or automated audit.
7. Verify the supported provider models, request/usage contracts, and current price table against official documentation. Account-access failures must preserve local features and must not cause model substitution.
8. Review all staged files and built archive members. Exclude original books, extracted text, private screenshots/reports, state, credentials, personal paths, and local curation tooling. Review dependency/asset licenses and notices.
9. Publish the reviewed commit and tag `v0.1.0`, with source-only release notes linking to this record and the [known limitations](limitations.md).

The release tag and source archives must identify the same reviewed commit. Generated UI assets are built during source setup; no prebuilt installer or hosted service is promised.

## Verification record

Verification date: **2026-11-09**. The local reference environment is **macOS 27.0.1 (build 26A434), Apple Silicon/arm64, Python 3.12.14, Node.js 24.15.0, and Safari 27.0.1**. These are tested versions, not a claim that every macOS/browser combination has been checked. A pending entry is not a successful check.

| Area | Evidence / status |
| --- | --- |
| Backend and permission/recovery tests | Final full run: **1,026 tests and 4 subtests passed**. Includes independent feature permissions, later authorization, disabled/exhausted states, recovery, legacy cache reuse, source-scope isolation, and concurrent source-change rejection with fake providers. |
| Frontend type, lint, unit, and build checks | Final integrated rerun passed on Node 24.15.0: type generation/checking, lint, build, and 53 unit tests. |
| Browser and automated accessibility checks | Final integrated rerun passed: 11 browser tests against synthetic sources, including automated accessibility checks. |
| Clean source installation and demo | Installation from the actual source archive passed in a path containing spaces on Node 24.15.0/npm 10.9.2, with a fresh Python 3.12 environment and a separate synthetic library. Local intake/search/read/cite and real OpenAI tokenization, indexing, accounting, query caching, and disabling passed using a fake SDK. Heavy experimental dependencies were absent; no live paid calls or Node engine warnings. |
| Skills | Automated preflight, idempotency, safe uninstall, legacy-name conflict, and symlinked cross-project launcher coverage is present. Final regression results are included with the backend suite; desktop skill-picker discovery and a live Bookshare download are not independently verified in this release record. |
| Manual keyboard | Safari: entered copper birds and submitted with Return; followed the result into contextual reading and used Cite whole reading unit. On the intake page, the skip link and Refresh focus workflow worked. This was a targeted pass, not an exhaustive audit. |
| VoiceOver listening | Not verified. Accepted as pending for this technical preview; no screen-reader conformance claim is made. Mouse-based exact quotation selection remains a separate disclosed limitation. |
| Provider pricing | Official model/request/usage contracts and pricing checked 2026-11-09; mocked embedding/review contracts and safe account-access failure behavior passed. No live paid request or account-specific model-access test was made. |
| Publication and package-content audit | Staged blobs/modes, explicit public file list, source archive, and built-wheel contents passed privacy/credential-pattern checks. Dependency versions matched their generated notices. Local Markdown/skill links passed. The public release contains source only. |

The [demo search illustration](images/demo-search.png) uses only the invented demonstration book. Written [quickstart instructions](quickstart.md) describe the same result without requiring the image. The macOS [Verify workflow](https://github.com/sethwilsonUS/reading-room/actions/workflows/verify.yml) repeats installation and automated checks on GitHub. Tagging requires a successful run for the release commit. Preserve the explicit VoiceOver follow-up.

## Updating the release

Keep compatibility with existing books, curation, source identities, authorizations, cost ledgers, and completed request receipts. A data migration needs tests using a representative synthetic legacy state and a documented backup/recovery path. Never repair compatibility by resetting an initial allowance or reenqueuing completed paid work.

Public reports should summarize verification without including a person's library, excerpts, paths, or credentials. Historical private reports are not publication evidence until their relevant findings have been reproduced using publishable fixtures.
