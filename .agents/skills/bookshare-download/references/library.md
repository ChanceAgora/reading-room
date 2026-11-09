# Library storage and acquisition provenance

Use the sibling [library-search launcher](../../library-search/scripts/library)
with `doctor --json` to discover the selected library root. Do not assume a
personal filesystem path. Application code lives in the checkout; books live
outside it, with private records and indexes in the book root's `.library`.

## Place and preserve the acquisition

- Keep one author/editor-and-title folder per distinct work, edition, or volume.
  Match actual publisher content; preserve conflicting catalog claims separately.
- Check title, contributor roles, ISBN, edition, and actual coverage as well as
  Bookshare ID. Different IDs can describe the same edition.
- Stage outside the library so partial downloads do not enter source discovery.
- Retain original packages at stable paths, normally `~/Downloads/Bookshare/`,
  with collision-safe names. Ephemeral browser downloads are not durable source
  provenance. Inspect and hash the retained source before placement.
- Reject archive traversal, absolute member paths, symlink entries, duplicate
  members, and destinations escaping the selected book folder. Do not overwrite
  an existing file. Preserve every source part and its inspected reading order.
- Preserve original bytes while copying or renaming. Keep extracted text,
  metadata, inspection notes, and caches outside individual book folders.
- Separate acquisition claims from verified source evidence, generated metadata,
  and the user's corrections. A successful ZIP check is not a completeness check.

## Complete shared intake

Follow [source-neutral intake](../../library-search/references/intake.md). Supply
one context per book with provider identity, observed metadata, ordered files,
hashes, retained archive or direct-source provenance, bounded inspection
findings, and discrepancies. Registration validates supplied provenance and
source bytes; it does not silently verify bibliographic claims.

For an outer ZIP, use `provenance.archive_path` and optionally `archive_sha256`.
Map every actual EPUB/DOCX member exactly once with `original_zip_member` and its
placed `path`. For a direct EPUB or DOCX, use `provenance.source_file` and optional
`source_sha256`/`source_bytes`. Do not supply both archive and direct provenance.
Several unrelated books in one archive require deliberate source mappings;
do not assign the entire archive independently to each book.

Run `library intake --path BOOK_FOLDER --context CONTEXT_JSON --json` after
verified placement. `library` means the absolute skill launcher above. Intake
registers and publishes text, then performs only the paid stages authorized by
library settings or explicit intake overrides. New libraries have AI off.
`--local-only` skips both paid stages for that intake; it does not exclude the
book from a later explicitly requested library-wide semantic build.

Do not directly annotate generated profiles as a parallel intake path.
Authorized automatic changes remain provisional assistant work with evidence
and Undo. Uncertain facts remain questions in guided review; user decisions and
personal verification remain distinct and protected. No original book is rewritten.

Report acquired files, text readiness, semantic coverage, metadata-review
progress or “not requested,” and remaining questions separately. Resume failed
stages through the stable intake ID rather than reacquiring files. Retained
archive checks support acquisition integrity; missing historical archives do
not prevent indexing an existing usable local copy.

## Historical compatibility

Some existing libraries have `.catalog` manifests. Preserve those records;
source-neutral intake reads supported historical context and writes new
acquisitions in `.library/acquisitions`. Do not create a competing catalog writer
or run historical whole-library audit scripts for new intake. Those personal
scripts are not distributed or required by The Reading Room.
