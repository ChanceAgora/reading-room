# Contributing to The Reading Room

Thanks for helping make source-grounded research easier to use. This is a personal project with best-effort maintenance; small, focused contributions are easiest to review.

## Report a bug

Use a [GitHub issue](https://github.com/sethwilsonUS/reading-room/issues) for ordinary bugs. Include the version/commit, operating system, expected result, actual result, and a short reproduction. For an accessibility problem, include the browser, assistive technology, and task that was blocked.

Use a synthetic EPUB/DOCX or describe the structural pattern whenever possible. Do not upload copyrighted books, private passages, acquisition records, research history, API keys, or unredacted logs. Diagnostics can contain local paths; review them before sharing. See [security reporting](SECURITY.md) for sensitive vulnerabilities.

## Make a change

1. Read [development](docs/development.md), [AGENTS.md](AGENTS.md), and the relevant [glossary](GLOSSARY.md) terms.
2. Discuss a substantial new feature or architectural change in an issue before building it. Straightforward fixes and documentation improvements can go directly to a pull request.
3. Make the change on a branch and add meaningful synthetic tests for affected behavior.
4. Run the relevant checks, including generated API types for interface changes. Keep source packages and Git publication boundaries intact.
5. Describe the concrete problem, the resulting behavior, and what you verified in the pull request. State untested areas rather than presenting them as passed.

Preserve the distinction between source evidence, provisional corrections, personal verification, and research use. Do not infer authorship from proximity or credit an entire anthology to its editor. Read the [contributor guide](skills/library-search/references/contributors.md) before changing attribution parsers.

UI changes need meaningful keyboard behavior and accessible labels/focus. Keep instructions readable without screenshots. Paid features must remain explicit, metered, resumable, and testable without real credentials; navigation and retries must not replay charges.

By contributing original material, you agree to make it available under the project's MIT license. Preserve third-party licenses and identify the provenance of any code, assets, or fixtures you add. The project license does not cover books supplied by users.
