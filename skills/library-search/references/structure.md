# Check a book's indexed structure

Use this check during new-book intake, after a parser change affecting section
boundaries, or when an indexed book looks incomplete. Keep it bounded to the
affected book and relevant source passages; a healthy research session does
not require re-auditing the shelf.

## Recognize suspicious structure

Start with `library status --json` and `library contents WORK_ID --json`.
Status summarizes supported and needs-review books; contents returns the
work’s analyzer version, structural outcome, evidence, issues, and normalized
outline. Follow `next_offset` with `--offset`; large groups retain ancestor
context. A short first page is not proof of a short book. Legacy `library book`
section counts describe retrieval sections, not complete reading units.

Normal sync analyzes new or changed sources before contributor detection and
retrieval chunking. Analyzer version changes also trigger analysis; unchanged
results are cached. Use these outcomes during intake. A `supported` outcome
records source evidence and representative boundary checks, not exhaustive
scholarly verification.

A substantial book with only “Front matter,” one section containing most of
its passages, or fewer boundaries than the source's contents suggests warrants
inspection. These are clues, not automatic failures: some works legitimately
have little internal structure. Healthy status, many readable passages, and
complete embeddings do not establish that chapters or contributions were
recognized.

## Distinguish missing text from missing boundaries

Compare the indexed contents with the actual edition's printed contents and
sample the beginning, a middle transition, and the end. Use indexed passages
first, then bounded format-aware inspection of the original when the index
cannot expose the relevant boundaries. Confirm whether later text is absent
or merely collected under an earlier heading. Verify reading order and
continuity across EPUB spine members or split Word files. Missing or unreadable
parts interrupt structural continuity.

Outline ancestry and reading-unit membership are distinct. A group can have
children plus a separate reading link for introductory or Scripture text.
Complete units have explicit source membership, including verified notes;
unassigned notes stay separate. For main Feasting commentary volumes, inspect
occasion → Scripture reading → perspective; companions can differ. Repeated
running labels do not automatically start new essays. Native heading depth,
chapter-number/title pairs, and repeated titles require source context.

An EPUB's navigation contents may list only the whole book even when its
printed contents lists many chapters. The only HTML heading tags may belong
to a Bookshare wrapper while real headings survive as ordinary paragraphs.
Likewise, Word exports can lose heading styles. Check both navigation and
visible source structure; capitalization, short lines, or familiar names alone
do not establish headings or bylines.

## Repair from evidence and verify the result

For confirmed missing boundaries, retain the heading text, exact source
member/anchor, and supporting contents or neighboring context. Prefer a
source-supported parser pattern with boundary and ambiguity tests. If OCR or
lost formatting makes a general rule unreliable, a reviewed correction scoped
to an exact source fingerprint, member, anchor, and expected text is safer.
Such a correction should decline to apply when its source or anchors differ.
Do not silently extend a repair to other editions or similarly titled books.

Keep originals, text, reading order, and source locators intact. A damaged
page label is a separate issue; restoring a heading does not verify or repair
pagination. Section boundaries also do not verify authorship: retain unresolved
contributors and follow the [contributor guide](contributors.md) before
assigning narrower credits. Preserve durable user corrections and usage history.

After a repair, refresh through the application's normal metered sync path
and verify the affected book's contents and representative transitions again.
Check that the body remains searchable, text coverage has not shrunk, and
curation has not become orphaned. Repaired boundaries may change retrieval IDs;
legacy links must retain their exact original source extent when unchanged,
or remain explicitly unresolved. Never transfer corrections to nearby text. Report structural quality separately from
text, citation, and semantic readiness. If boundaries remain uncertain, record
that limitation rather than treating the whole-book “Front matter” label as
meaningful or blocking otherwise usable text research.
