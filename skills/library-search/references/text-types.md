# Text types and mixed passages

Text type describes the material being read, separately from a book's subjects
or the extractor's paragraph/heading structure. Supported values are `scripture`,
`commentary`, `poetry`, `quotation`, `caption`, `translation_note`, `editorial`,
`index`, `reference`, `prose`, `mixed`, and `unknown`. Record it on a passage or
uniform section, not a whole book. A study Bible or anthology usually mixes types.

Use `annotate ID --field text_type --value '"commentary"'` with actual evidence,
origin and status. A classification does not establish its author's identity.
Unknown remains searchable; `search ... --filter text_type=commentary` narrows
to classified passages, including mixed passages containing commentary. Inspect
the matched portion: the filter does not prove every word is commentary.

For Scripture alone, use passage bibliography with `type: "scripture"`,
`bible_translation` (full source-supported name), optional
`bible_translation_short`, `scripture_scope: "text_only"`, and a verified
`locator` of type `verse` containing biblical book, chapter, and verse range.
Verify this edition's translation statement; do not infer NRSV versus NRSVue
from a familiar title or similar wording. Citation output uses the biblical
reference and translation. Its empty bibliography is intentional under the
default Chicago convention, not missing scholarship metadata. Commentary and
translation notes require their own credits and citations.

## A passage containing more than one contribution

Use a `segments` annotation only after inspecting the complete passage. Its
value is a list of objects with `first_block_id`, `last_block_id`, `text_type`,
`attribution`, `bibliography`, and optional `notes`. Get real block IDs from
bounded reading, continuing through the passage as necessary. The ordered,
nonoverlapping spans must use nonblank endpoint blocks and cover every nonblank
source block (blank-only gaps are allowed); they do not alter
the original text or passage identity. Each segment's bibliography describes
only that portion, while the containing work supplies publication metadata.
Do not inherit another segment's contributor or assign a footnote to the author
it quotes. Check source reference relationships when note ownership is unclear.

An unsigned index, headnote, or translation note can be labeled as such after
checking the relevant credits. Record `authors: []` only to assert that no
individual is named in that inspected source, with evidence and a limitation;
this is not proof of historical anonymity. Use `authors: null` when authorship
has not been established. Preserve known container editors as editors.

`library cite PASSAGE_ID --json` returns `component_citations` for segmented
material and asks for a component instead of producing one misleading citation.
Select the relevant `segment_id` with `library cite PASSAGE_ID --segment BLOCK_ID
--json`, or follow **Cite this portion** in the reader. The browser chooser shows
an excerpt so repeated Scripture/commentary portions can be distinguished.
Verify citation warnings independently of text type and attribution.

If one source block itself mixes authorship that cannot be represented safely,
record the limitation and leave it unresolved; do not classify the entire block
as Scripture merely to clear a warning. Changed source identities require fresh
boundary checks before reapplying orphaned curation. Preserve user corrections.

Normal sync publishes these changes and refreshes the semantic index through
the existing budget ledger. Unchanged text can reuse cached embeddings. Intake
needs a representative pattern check, not an exhaustive manual classification
of every book before it becomes searchable.
