# Keep correction proposals separate from applied information

Pending manual edits and AI proposals live in durable local reviews, separate
from the curation history that supplies effective metadata. Existing
provisional annotations already affect library information, so using that
status for an unsaved proposal would silently apply it. An explicit scoped
save applies selected fields; verification is a separate per-field decision,
preserving the difference between a plausible correction and source-confirmed
citation metadata.

Reviews retain the source and metadata revision they were based on. Changed
evidence or intervening edits require a renewed review rather than an automatic
overwrite. Related display and citation edits are offered together but remain
individually selectable, and a single save cannot expand its correction scope.

Review decisions are durable but separate from pending field changes. Accept
queues a correction; Reject and Keep current information record workflow
decisions without changing or verifying metadata. Later keeps a question
outstanding. Discarding unsaved changes does not forget previously handled
findings or undo saved corrections. Each decision retains enough context for
history and safe restoration.

Decisions survive a repeated review with equivalent findings. An item returns
for reconsideration when relevant values, source content, scope, or evidence
change, rather than when an explanation is reworded or an unrelated field is
edited. This trades a small amount of persistent review state for avoiding
repeated decisions and preserving uncertainty honestly. Older reviews remain
readable without a write on page load.

The action list precedes the full record. Related fields can share an explanation
and investigation links, but each field retains its own decision and verification.
Investigation expands existing evidence and useful leads without initiating paid
work. Source associations must be validated; a consulted record is not necessarily
evidence for a particular finding. Verification sits beside the evidence, while
the final save remains compact. Undo and Restore affect review state and must
never overwrite subsequent manual edits or reverse already saved metadata.

The default experience is now one plain-language recommendation at a time, with
identification and citation questions before optional research categories. A
recommendation can say that no change is needed. Related changes within one
target are staged together by default, with a preview and individual selection
in Details. This reduces the cataloguing knowledge needed to use the review
while preserving field-level control, evidence, and independent verification.
The entire chosen bundle is validated and staged atomically. Navigation does
not accept, reject, defer, verify, or apply information.

Book metadata has one home: the book review. An ISBN relationship discovered
while reviewing a section is retained as a book-level assessment, separate from
the section's changes and from the book's manual drafts. Section reviews link
to that assessment rather than turning an ISBN question into an Introduction
correction. Related-format evidence may help identify a book; it cannot silently
establish a section's author or transfer page locators between formats.

AI requests distinguish complete target text from supporting publication
evidence, and content classifications use definitions and purpose-based rules.
AI support labels describe the evidence and uncertainty, not personal
verification. Different ISBNs can identify related formats rather than revised
contents; comparisons retain sources and unknowns instead of treating numeric
inequality as an edition conflict. Recognized e-book providers can corroborate
format relationships, with the actual copy and publisher preferred when
records disagree. Original books remain untouched and paid work still requires
an explicit request.

Authorized intake can now apply eligible recommendations without a person's
individual Accept and Save actions. This is a separate assistant application
path: it records provisional Codex-origin changes, not a human decision or
personal verification. An AI confidence label alone is insufficient. Automatic
application binds factual values to their source assertions and uses explicit
rules for supported editorial judgments, complete scope, contributor roles,
conflicts, revisions, and existing user work. Ineligible findings remain in the
guided review. User edits, confirmed values, manual drafts, and prior human
decisions are not silently replaced.

Automatic applications retain their target, previous provenance, evidence,
model/run and eligibility information, and a durable idempotent receipt.
Undoing an automatic correction appends a reversal of that particular event,
rather than writing an old value as a new assertion. This preserves the
distinctions between absent, inherited, unknown, and explicitly empty values.
Later edits remain intact, and an undone finding is not immediately reapplied.
This automatic-change Undo is distinct from restoring an unsaved review choice.
