# Optional AI, privacy, and costs

You can read, browse, perform exact-text searches, edit metadata, and create citation drafts without an API key. A fresh library has semantic search and automatic metadata review off. Merely finding a key in the environment does not authorize either feature.

## Two independent choices

| Feature | Purpose | What goes to OpenAI |
| --- | --- | --- |
| Semantic search | Retrieve passages related to a query, alongside exact matches. | Extracted passage text for embeddings and query text for query embeddings. A full build processes the library's indexable text in bounded requests. |
| Metadata review | Suggest evidence-backed corrections to book/section information. | Bounded source evidence and bibliographic information; unresolved publication questions may use limited web research. |

Original EPUB/DOCX packages remain local. That does **not** mean all book content stays local when AI is enabled: extracted text is transmitted as described above. Bibliographic web queries use identifiers and publication facts rather than private filesystem paths or research notes. Local corrections and research-use history are separate from the source corpus.

Codex is another tool with its own data handling. If you ask an agent to read local passages, those passages enter that agent's context. The library's exact-search mode does not control what an external agent does with its results.

The application is a local service, not a cloud library account. Review the provider's current [API data controls](https://platform.openai.com/docs/guides/your-data) and the rights that apply to your own materials before enabling external processing.

## Configure credentials

Use your own OpenAI API key. Reading Room checks `OPENAI_API_KEY`, then the file named by `LIBRARY_OPENAI_ENV`, then `openai_env_file` in the library's private configuration. See the [configuration reference](configuration.md#credentials) for safe file setup and precedence.

The server needs access to that credential source. A macOS login service does not inherit your interactive shell exports; use the private credential-file reference for automatic startup. Never paste a key into an issue, screenshot, committed configuration, or browser UI.

## Accept spending limits

The suggested limits are **$10 for the initial full-library embedding build** and **$10 per calendar month for shared updates, searches, and reviews**. They are separate allowances. Intake embeddings use the monthly allowance even when a full initial build has not finished.

These are application accounting limits for one library. They are not account-wide OpenAI limits or a provider-enforced billing cap. Actual provider charges, pricing changes, other applications, and uncertain requests can differ from this ledger.

Accept the suggestions or choose explicit amounts and a timezone:

```sh
./bin/library budget configure --accept-budget --timezone America/Chicago
# Or choose your own limits:
./bin/library budget configure --initial-usd 5 --monthly-usd 15 --timezone Europe/London
./bin/library budget status --json
```

Use your own IANA timezone rather than copying an example unintentionally. The monthly boundary follows the saved timezone. Later feature opt-ins reuse accepted limits rather than resetting them; existing libraries retain their previous amounts and accounting history.

Before each paid request, the library reserves a conservative amount. Completed usage reconciles the reservation; an uncertain timeout keeps it. Cached embeddings and saved review stages avoid paying again for completed work. An exhausted allowance leaves local reading, exact search, and manual editing available. Increasing a limit is a deliberate configuration change, not an automatic retry.

## Enable semantic search

First build the local text index, then inspect a local estimate:

```sh
./bin/library sync --exact
./bin/library semantic estimate --json
./bin/library semantic enable --accept-budget --timezone America/Chicago
```

The estimate makes no provider request and grants no permission. Enabling records permission but does not itself build the semantic index. After reviewing the estimate and limits, explicitly start the build:

```sh
./bin/library sync --json
./bin/library semantic status --json
```

The supported semantic model is `text-embedding-3-large`. Fresh indexes use the included `tiktoken` tokenizer, without downloading a local embedding model. First use may fetch public tokenizer data; the local estimate sends no book text and makes no paid provider request. Existing indexes retain their recorded windowing configuration and cached vectors; [older E5-windowed indexes](operations.md#continue-an-older-semantic-index) need an optional tokenizer only when extending or rebuilding them. Ordinary search combines exact and semantic retrieval; query embeddings may incur a small charge. For a wholly local query:

```sh
./bin/library search 'a distinctive phrase' --exact --json
```

To prevent subsequent semantic provider requests while retaining cached work:

```sh
./bin/library semantic disable
```

An in-flight request may finish and settle normally. Re-enabling does not reset the initial-build allowance or discard completed embeddings. Status reports actual coverage; an incomplete index is never equivalent to a fully indexed collection.

## Enable metadata review

To remember automatic review for future imports:

```sh
./bin/library review enable --accept-budget --timezone America/Chicago
./bin/library review status --json
```

This sets the future-import default. It does not review existing books automatically. Each new intake records its resolved permission; use `--no-review-metadata` to skip review for one import or `--local-only` to skip both paid stages. See [intake choices](intake.md#choose-processing-for-an-import).

To turn off the future-import default:

```sh
./bin/library review disable
```

**This does not cancel already-authorized jobs.** Pause them explicitly on the Intake page or with `intake pause INTAKE_ID`. You can still explicitly request a one-off review when the automatic default is off. The browser's manual AI-review action is also a separate request and requires accepted spending limits.

Automatic review examines bounded evidence and can apply eligible corrections as provisional assistant work. It preserves user edits and verification; uncertain findings remain for your review. Accepting a suggestion, saving a correction, and verifying it against source evidence are different actions.

Review currently uses `gpt-6-luna` with bounded requests. A complete review reserves up to $0.75 conservatively; this is not its expected price. The implementation limits model requests and web-tool use, keeps uncertain costs, and does not silently switch to another model when access fails. See the [release verification record](release.md) for the model-contract and pricing verification status.

The price table was checked against [official OpenAI pricing](https://developers.openai.com/api/docs/pricing) on 2026-11-09: large embeddings cost $0.13 per million tokens; standard review-model input/output rates are $0.10/$0.50 per million tokens, with separately accounted cached input, cache writes, and web-search use. Pricing can change; the ledger uses the application's recorded rates and conservative reservations rather than a live provider bill.

## What the spending controls do not cover

Reading Room's ledger covers its own API calls. It does not account for Codex use, Bookshare subscriptions, other applications sharing the key, or provider charges unrelated to this library. The local service and key are under your account's control; do not expose the server on a network or place credentials in frontend environment variables.
