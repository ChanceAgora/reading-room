# Keep acquisition adapters separate from authorized intake

Bookshare obtains authorized downloads and can supply useful catalog claims,
file ordering, original-member mappings, and inspection evidence. Those are
inputs to a shared library intake process, not reasons to require every book
to have a Bookshare identifier or pass a historical Bookshare-only audit.
Local EPUB and Word acquisitions use the same registration and indexing path.

New acquisition records preserve their provider, source claims, file identity,
and evidence in private library state. Historical manifests remain readable
through compatibility handling. The original book bytes are never changed.
Uncertain duplicates, formats, and editions are not silently merged or replaced.
Acquisition provenance, proposed changes, applied corrections, and verification
remain distinct records rather than one mutable catalog assertion.

Explicit intake records the selected source scope and its resolved processing
permissions. Paid metadata review requires a saved automatic-review preference
or an explicit per-intake choice; local-only intake does not authorize it.
Ordinary sync discovers and indexes source files but does not authorize paid reviews;
reading a status page does not create a job. A single service worker processes
the private queue, with stable request identities, claims, results, and receipts
that survive restarts. This adds persistent workflow state in exchange for
avoiding repeated provider charges and making long books honestly resumable.

Healthy exact text becomes available before the review finishes. Semantic
indexing, source structure, review coverage, and automatic changes have separate
statuses. Unrequested review is not reported as completed review. When authorized,
intake checks book details first and records an outcome for every
indexed heading, including small headings and incomplete sections. The outcome
does not imply the complete text was inspected. Publication investigations stay
at book scope and are not repeated for each section.

All paid intake work uses the shared monthly allowance and conservative reservations.
Budget pauses wait for an explicit resume, including after a calendar reset.
Interrupted or uncertain requests retain their cost reservations and are not
silently replayed. Saved results can continue to application without another
model request. Changed source content pauses affected work for reconsideration.

Completed provider stages also have durable checkpoints. A clean pause can
continue only the unstarted stages, reserving their remaining allowance and
retaining the original review's request and active-execution limits. An
in-flight stage with an unknown outcome is never silently replayed. Semantic
indexing checks for pause before each provider request and reuses completed
vectors; intake always uses the monthly allowance, even before an initial
semantic build has completed. A budget or provider pause blocks further paid
intake work across the queue until explicitly resumed, while exact text work
and safe application of saved results can continue.

Authorization binds the selected source files, including known parts of a
split work. A newly arrived adjacent file cannot silently enlarge that scope.
Intake pauses before indexing or reviewing the enlarged selection and asks for
the intended book files to be restored or selected explicitly.

This workflow applies to newly requested intake and explicitly selected existing
books. Changing a future-import default does not authorize old jobs; later review
is requested explicitly on the existing intake identity. It does not launch a
backfill merely because a worker or browser starts.
The compact intake view explains readiness, coverage, provisional automatic
changes, and questions requiring a decision. The guided review remains the place
to inspect and resolve those questions.
