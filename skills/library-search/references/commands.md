# Commands and curation

Executable: resolve `../scripts/library` relative to this reference's location,
or `scripts/library` relative to the host-provided library-search SKILL.md path.
Use `--help` for current options rather than inventing flags. Examples below
use `library` as shorthand for that absolute path. JSON output is bounded for
agentic use; keep source excerpts out of unnecessary conversational dumps.

```sh
library status --json
library sync --json
library search 'water and belonging' --mode balanced --json
library search 'group dynamics' --mode exploratory --json
library search 'exact words from a passage' --filter form=poem --json
library read PASSAGE_ID --context 3 --json
library cite PASSAGE_ID --json
library cite PASSAGE_ID --segment BLOCK_ID --json
library search 'beatitudes' --filter text_type=commentary --json
library search 'water and belonging' --exact --json
library focus list --json
library focus show FOCUS_ID --json
library usage --json
library serve
```

Search combines keyword/phrase matching with an explicitly enabled OpenAI
large semantic index, when configured, and diversity across works. Otherwise
it uses local text search. `--exact` keeps retrieval
wholly local. Inspect actual semantic coverage and pending updates rather than
assuming engine selection guarantees complete coverage. Review each result's
reason and limitations. Explicit filters narrow eligibility; they can exclude books with
unknown metadata, so omit them when merely expressing a preference.

## Passage citations

Run `library cite PASSAGE_ID --json` after reading and verifying its context.
The same citation is available from the browser's passage view. Use the full
note for a first footnote/endnote, the shortened note for subsequent references,
and the bibliography entry for the source list. Keep the returned style/version
and readiness warnings visible in research notes until resolved. The command
is local and does not call an AI provider.

A citation cites the edition actually inspected. Verify publisher, publication
year, edition/volume, and distinct author/editor/translator roles in its title
and copyright pages. A copyright date, acquisition date, and edition year may
differ. Generated catalog display titles and filename separators may not be the
publisher's title. Use evidence-backed bibliography corrections, preserving user
edits; `annotate --help` and the metadata editor expose supported fields.

For essay, chapter, poem, note, or artwork credits, follow the shared
[contributor evidence workflow](contributors.md). It covers source boundaries,
distinct roles, unresolved names, and section- or passage-level bibliography
annotations. A study-note contributor does not author neighboring Scripture;
an indexed section can contain both.

Use source-supplied printed pages only when their meaning is verified. Otherwise
use the actual chapter/section locator. Do not turn extraction block numbers,
Word parts, reader offsets, or reflowed pagination into print pages. A local
reading link aids resumption, while a catalog link identifies an edition; neither
proves a claim without the inspected passage. Respect task-specific output and
instructor style requirements; the library's Chicago default does not change
existing lesson gates or class-sharing conventions.

## Evidence-backed metadata

Use the target work, section, or passage ID returned by the library. Submit an annotation
with the field, JSON value, evidence, origin, and status. For example:

```sh
library annotate WORK_ID --field profile --value '{"subjects":["ecology"],"forms":["poem"],"themes":["water"]}' --evidence 'Contents and the inspected water poems; precise section IDs recorded in research notes.' --origin codex --status provisional
```

When `annotate` reports `index_refresh_required`, run `library sync --json` to
publish those edits into search. Replace that evidence with actual inspected
locations. A broad book profile is
an aid to discovery, not a claim that every section has every label. Add
section-level labels when the inspected text supports them. Record competing
interpretations and uncertain attribution explicitly. Reserve `origin=user`
for the user's edits or an explicit correction they give; do not present an agent
inference as their confirmed classification. Regeneration preserves user edits.

Passage IDs accept `bibliography`, `attribution`, `notes`, `text_type`, and
`segments`. Use passage bibliography when the entire verified passage has a
narrower credit than its containing section. Use evidence-backed segments when
different portions need distinct credits; see [text types and mixed passages](text-types.md).
These annotations do not automatically classify the rest of the library.
Unchanged bibliography fields inherit the section, while passage corrections
override matching fields. `cite` reads the latest corrections immediately;
search and reading need the reported synchronization. A source change can make
a passage correction inactive: review `orphaned_passage_curation_count` in
`status`, inspect the new source span, and deliberately reapply only supported
corrections. See [the contributor guide](contributors.md) for the scoped example.

Research focuses contain a name, description, preferred subjects, forms and
books, and breadth (`focused`, `balanced`, or `exploratory`). Inspect the current
record and use `focus set --help` or the local interface to edit it. Shared
focuses should express reusable preferences, not hardcoded current inventories.

## Vocabulary and faceted browsing

Use the Reading Room’s **Subjects & connections** page to browse overlapping
classifications, including labels on individual sections. Counts are distinct
available books, not repeated labels. The vocabulary editor keeps aliases and
broader, narrower, or related terms together; these are discovery relationships,
not evidence of historical influence.

```sh
library taxonomy list --query poetry --json
library taxonomy set haiku --value '{"label":"Haiku","aliases":["hokku"],"broader":["poetry"],"related":["ecology"],"origin":"codex","status":"provisional","evidence":"An explicit discovery vocabulary proposal; verify against inspected source usage."}' --json
```

Create a missing relationship target before linking to it. Vocabulary updates do
not relabel source books or require re-extraction; annotate the actual work or
section separately when its text supports a classification. Preserve user
corrections and use provisional Codex origin for agent-generated proposals.

## Complete units and exact selections

```sh
library contents WORK_ID --json
library read-unit UNIT_ID --json
library read-unit UNIT_ID --cursor NEXT_CURSOR --json
library cite-unit UNIT_ID --json
library create-selection UNIT_ID --file /absolute/path/to/source-ranges.json --json
library cite-selection SELECTION_ID --json
```

The ranges file is a JSON list such as
`[{"block_id":"BLOCK_ID","start":4,"end":27}]`. Offsets count Unicode code
points in original block text; end is exclusive. Include every intervening
source block for a contiguous multi-paragraph selection. Use returned source
coordinates, not quotation searching. Confirm `quotation` before citing or
recording. Source changes invalidate a saved selection instead of moving it.
Mixed credits return component citations or warnings; exact anchoring does
not verify a printed page. Whole-unit citations resolve their own scope.

```sh
library usage record --event '{"kind":"used","target_scope":"selection","target_id":"SELECTION_ID","project":"research-project","evidence":"/absolute/path/to/research-note.md"}' --json
library usage record --event '{"kind":"inspected","target_scope":"unit","target_id":"UNIT_ID","project":"research-project","evidence":"/absolute/path/to/research-note.md"}' --json
```

## Usage history

```sh
library usage record --event '{"kind":"inspected","work_id":"WORK_ID","passage_id":"PASSAGE_ID","project":"research-project","evidence":"/absolute/path/to/research-note.md"}' --json
```

Only record events that actually occurred. Prefer stable source IDs and exact
evidence links. Historical imports use `library usage import PATH --json` with
the supported lesson or supplement source, preserving ambiguous matches and
deduplicating repeated imports. Do not import entire personal-writing text
as searchable book material. Keep research usage separate from the API budget
ledger, which accounts for reservations, retries, and actual paid usage.

## Acquisition handoff

`bookshare-download` owns authorization, format choice, source inspection, and
meaningful filenames. After verified placement, follow [source-neutral intake](intake.md):
`library intake --path /absolute/book/folder --context /absolute/context.json --json`.
The job snapshots the user's semantic and metadata-review permissions. New
libraries use local processing unless paid capabilities have been authorized.
Use `--local-only` when explicitly requested; do not directly annotate generated
profiles as a parallel intake path. Inspect the outline and perform the bounded
[structure check](structure.md); successful extraction alone does not establish
chapter boundaries. Verify a distinctive passage and citation before calling it
ready for research. Resume incomplete stages without downloading again.

Normal sync uses the application's metered semantic pipeline only when approved. Download
success, exact-search readiness, structural quality, bibliography readiness,
and semantic readiness are separate states. Preserve stage outcomes and resume only incomplete work.
A citation draft with missing publication details is not a completed bibliography.
The application enforces spending limits; a skill invocation does not override
them, and paid-processing failures do not disable local text research.
