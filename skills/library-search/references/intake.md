# Source-neutral library intake

Use this workflow when the user asks to add EPUB or Word material, whether obtained
through Bookshare or supplied as local files. Intake uses independently approved
semantic settings and the saved automatic-review default for future imports.
New libraries have both off. A request to acquire a book does not itself grant
permission to enable paid features or accept spending limits. Merely
searching, opening a book, or synchronizing does not authorize intake. Never
backfill existing holdings unless the user explicitly selects them.

## Prepare one book

Check existing holdings before copying. Reuse a usable byte-identical copy;
inspect possible title/edition/ISBN matches rather than silently merging,
replacing, or discarding a different format or edition. Keep original files
unchanged. Place the selected book in a descriptive folder under the configured library root,
preserving every source part and its actual reading order. Stage outside the
library. Source-specific skills own acquisition, access, and package inspection;
the library owns registration and subsequent review.

The current formats are EPUB and DOCX. Do not call PDF, scans, or other formats
indexed or reviewed. Keep distinct books in separate folders. Several EPUBs,
mixed formats, or source parts in multiple folders require an explicit list of
the ordered files belonging to one book; unselected adjacent books are rejected
to prevent accidental merging.

## Supply context without claiming verification

Write a bounded JSON context outside individual book folders. Use this shape,
replacing illustrative paths and values with observed ones:

```json
{
  "provider": "publisher",
  "provider_id": "optional-record-id",
  "source_label": "Publisher download",
  "metadata": {
    "title": "Observed book title",
    "publisher": "Observed publisher",
    "publication_year": "2026",
    "source_url": "https://example.org/actual-record"
  },
  "files": [
    {"path": "/absolute/library/book/Book.epub", "sequence": 0}
  ],
  "provenance": {
    "source_file": "/absolute/original-download/Book.epub"
  },
  "inspection_evidence": [],
  "discrepancies": []
}
```

Use `provider: "local"` when the origin is unknown; a provider ID is optional.
Bookshare uses `provider: "bookshare"` and its actual record ID. Supplied metadata
is imported candidate information. Preserve distinct authors/editors/translators
when the source establishes their roles; a combined catalog credit is only a
display candidate. Different print and digital ISBNs need comparison, not an
assumed edition conflict.

Files may also provide `sha256`, `bytes`, `scope`, `source_path`, and
`original_zip_member`. Hashes and sizes are checked against the actual files.
For an outer archive, provide `provenance.archive_path` and optional
`archive_sha256`; map every book member exactly once through the file entries.
Do not supply both archive and direct-source provenance. Originals, member
coverage, and placed bytes are validated without rewriting them.

Inspection evidence entries may contain `path`, `sha256`, `locator`, `quote`,
`field`, and `value`. Keep quotations short (at most 2,000 characters each).
Use actual source member/location information; do not invent extraction IDs.
Only hints that match an indexed source hash, location, and quotation become
model-facing investigation leads. An assistant's assertion of verification is
not itself evidence. Do not include credentials or private research notes.

## Enqueue, inspect, and resume

Resolve `library` to the absolute [skill-relative launcher](../scripts/library).
Check `library doctor --json` for the root, capability settings, and accepted limits.

```sh
library intake --path /absolute/book/folder --context /absolute/context.json --json
library intake status INTAKE_ID --json
library intake pause INTAKE_ID --json
library intake resume INTAKE_ID --json
library intake --path /absolute/book/folder --local-only --json
library intake --path /absolute/book/folder --review-metadata --json
library intake --path /absolute/book/folder --no-review-metadata --json
library intake review INTAKE_ID --json
```

`--context` is optional for an existing local book. The path must select one
book file or folder inside the library, not the entire library root. Repeating
the request reuses its stable intake. JSON includes work identities as they
become available, independent readiness, counts, and progress/review URLs.
Summarize those fields; do not dump thousands of target records into the chat.
The original acquisition context is retained. A repeat with different supplied
metadata or evidence is rejected explicitly; use the existing guided review to
correct information rather than silently replacing that provenance record.

Overrides apply to this intake only; the saved default applies to later imports.
Changing a default never upgrades previously local-only jobs. Use `intake review`
to explicitly request later metadata review without creating another job; paid
work still needs accepted spending limits. Existing jobs can be paused separately.

The running local service processes authorized jobs sequentially. Healthy exact
text becomes available before review completes; semantic indexing uses the
approved OpenAI large pipeline separately. Book details are reviewed first,
then every indexed heading receives an outcome. Heading-only, incomplete,
ambiguous, and failed cases stay explicitly labeled. A bounded review is not
proof that every word was inspected. Source changes require resumption against
the refreshed source; source-bound corrections are not silently transferred.

When requested, review uses `gpt-6-luna`, low reasoning, the existing key loader,
and the user's accepted shared monthly ledger. Section reviews are local-evidence-only; publication web
research belongs to the book. Budget and provider pauses preserve results and
require explicit Resume. A new month does not resume paused work. Never issue
unmetered calls, silently retry uncertain paid attempts, or redownload a book
to fix indexing/review.

Eligible facts and helpful labels are saved as provisional assistant changes.
User edits, confirmed values, manual drafts, and prior human decisions are
protected. Automatic changes retain evidence and Undo; personal verification
remains separate. Uncertain questions link to the guided review. Use its book
scope for ISBN/edition/publication information and the relevant section scope
for contribution information.

```sh
library intake undo INTAKE_ID --json
library intake undo INTAKE_ID --event EVENT_ID --json
```

Undo preserves subsequent edits and restores the previous information and its
provenance. It does not edit original books. Direct `annotate` is not a second
automatic intake path.

Report acquired files, exact-search readiness, semantic readiness, review
progress, changes saved, and questions remaining separately. Include the
progress link. If the worker is still running, say so; the download conversation
does not need to stay open. Verify a distinctive passage and citation when text
is ready, retaining honest contributor and locator warnings.
