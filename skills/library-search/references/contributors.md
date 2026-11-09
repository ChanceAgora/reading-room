# Finding and preserving contributors

Use this guide during intake of an edited or mixed-author book, when a passage
has an unverified contributor, or when attribution conflicts with the source.
Make a bounded best effort at intake, then verify the particular contribution
used in later research. Unresolved names do not prevent text-search readiness;
report the gap separately. Do not review every byline in every book on each
search, and do not assume indexing detects every contributor automatically.

For shared intake, follow [source-neutral intake](intake.md): pass observed
credits, source locations, and scope limitations as context. Let its protected
application path save eligible findings as provisional assistant corrections.
Do not run a separate annotation pass or mark automatic intake findings
confirmed. The manual annotation workflow below applies to explicitly requested
research or curation outside intake.

## Establish the source's attribution pattern

Start with the actual edition's title/publication pages and contents. For a
representative chapter, essay, poem, or entry, inspect both its beginning and
end: a signed closing line may identify its author even when the opening only
names a topic. Check contributor lists, abbreviation keys, acknowledgments,
translation statements, illustration lists, captions, and credits as relevant.
Use indexed context first; inspect the original DOCX/EPUB when layout, missing
text, or links make the evidence ambiguous.

Look for an explicit relationship between a name and a contribution: a byline,
signed ending, contents entry with author, a credit tied to a named work, or a
key explaining initials. Preserve role phrases such as “introduction and
annotations by”: they define which material the person wrote. A roster can corroborate spelling and identity, but
presence in the roster alone does not identify the author of an essay. Running
headers, an all-caps line, a familiar name, or a catalog's combined author/editor
field are clues, not sufficient evidence of scope.

Cross-check credits within the same edition when it resolves uncertainty. A
contents credit, roster entry, and closing byline can reinforce one another;
there is no fixed number of sources to collect once the person, role, and scope
are established. A later edition may change contributors or revise their work.

At intake, record the pattern observed, representative evidence locations, and
exceptions needing review alongside the provisional profile. Apply verified
credits where the existing structure supports them. When a book has no reliable
automatic pattern, retain that limitation and investigate relevant passages as
they are used. A recurring pattern in one volume is not proof that another
volume or export uses it identically.

## Match the credit to its scope

Read the contribution's opening, ending, and neighboring headings before
attaching a name. Follow the book's logical reading order across Word parts or
EPUB spine members: a physical file boundary need not end an essay, and a
heading can start a new perspective within a longer chapter. A closing byline
usually belongs to the preceding contribution only when the source establishes
that pattern; do not let it bleed into the next essay, poem, notes, or credits.
Missing, unreadable, or empty source parts interrupt that inference. Do not
carry a contributor across the gap without evidence establishing continuity.

Keep these roles distinct:

- Book author and volume editor; an anthology editor is not every poem's author.
- Chapter/essay/entry author and a person quoted or discussed within it.
- Original author, translator, adapter, and author of an introduction or notes.
- Commentary contributor and the biblical author, narrator, or speaker.
- Artist, photographer, translator of a caption, and author of the surrounding
  art-historical discussion. A reproduction credit may name a rights holder or
  collection rather than the artist.

A heading or indexed section is a retrieval boundary, not proof of uniform
authorship. Read the actual blocks covered by the proposed annotation and the
transition on either side. A study Bible can interleave scholarly commentary,
Scripture, translation notes, and quoted sources under one lingering heading;
an anthology or reference entry can similarly contain nested contributions.

Credit the passage actually used, preserving its relationship to the enclosing
chapter and editor. A credit for a biblical book's “introduction and annotations”
does not make that scholar the author or translator of the biblical text. Nor
does an essay author's credit establish authorship of every poem, quotation,
caption, or primary-source extract embedded in it. Choose the smallest supported
annotation target whose full text fits the evidence. If an indexed passage
mixes material that needs different credits, use the supported block-span
segments described in [text types and mixed passages](text-types.md), with a
separate credit and citation for each portion. If the actual source blocks
cannot safely express the boundary, record the limitation and retain the warning.

Notes require their own boundary check. The author cited inside a footnote is
not thereby the author of that note or the essay. Shared endnotes may follow
the final contribution while belonging to earlier ones. Use explicit labels or
unambiguous source reference/backlink relationships to establish ownership;
nearness, repeated note numbers, or anchor-name suffixes alone are insufficient.
Leave ambiguous shared notes unowned instead of inheriting the nearest byline.

## Record evidence and uncertainty

Preserve the source's spelling, initials, diacritics, and order. Expand initials
only with a source-supported identity match. Use structured given/family names
only when their roles are established; preserve a literal name rather than
guessing surname boundaries or culturally specific name order. Identifying the
right person and preparing their bibliographic name are separate checks.
Publication year, edition identity, and locator verification are separate too:
finding the contributor does not confirm all remaining citation fields. When
needed, corroborate an ambiguous edition year with an authoritative publisher
or institutional record matching the edition and identifier.

Distinguish these outcomes:

- **Unknown:** no supported attribution yet. Leave it unset and retain the
  warning. Unknown does not mean anonymous or an explicitly unsigned work.
- **Provisional:** a plausible candidate with a recorded rationale or incomplete
  scope. Do not present it as verified in research or a finished citation.
- **Confirmed:** the inspected source supports this person, role, and scope.
  Confirmation applies only to the fields checked, not all metadata in a record.
- **Disputed:** conflicting credits or editions need resolution; retain both
  evidence locations and do not silently choose the convenient one.

The command's annotation statuses are `provisional`, `confirmed`, and
`disputed`; unknown is absence of a verified value, not a `--status` option.
Use `--origin codex` for agent work, including source-verified corrections.
Reserve `--origin user` for the user's own edits or explicit corrections. Preserve
existing user corrections through sync and rebuilding.

Outside shared intake, use `library annotate` on the actual work, section, or passage ID returned by the index.
Record source file/member, section or passage ID, the relevant byline/credit
location, and the scope it establishes in `--evidence`. Keep evidence excerpts
short. For citation-ready chapter, poem, or entry authors, use the supported
`bibliography` field; a display-only `attribution` does not verify bibliographic
name structure. Use a section ID only when the entire section fits that credit.
For a verified contribution wholly contained in one passage of a mixed section,
use its passage ID, as in this example after replacing every example value:

```sh
library annotate PASSAGE_ID --field bibliography --value '{"type":"chapter","title":"Actual chapter title","authors":[{"given":"Jane","family":"Doe"}]}' --evidence 'Actual file/member and passage IDs: source credit identifies Jane Doe as the chapter contributor; the complete target passage contains only that contribution. Neighboring source text has separate authorship.' --origin codex --status confirmed --json
```

Keep container editors and publication details on the work, and contribution
authors/title on the section or passage that matches their scope. Passage targets
support `bibliography`, `attribution`, `notes`, `text_type`, and `segments`; their bibliography fields
override the corresponding section fields while unchanged fields inherit.
An explicit passage `attribution` controls its display credit, but does not
replace structured citation metadata. The browser's **Edit attribution for this
passage only** link provides the same narrow scope. Use supported notes for credits or
scope that the citation schema cannot yet express; do not force an artist or
photographer into an essay-author field. `authors: null` means unknown;
`authors: []` asserts no named author and needs explicit evidence. Consult
`annotate --help` and the metadata editor for current fields rather than
inventing a schema.

Citations use current curation immediately; synchronize when the annotation
reports an index refresh is required to update search and reading. Reread the
affected passage and its neighbors, then run `library cite PASSAGE_ID --json`.
Check that the author, container editor, contribution title, and locator reflect
the evidence and that neighboring text did not inherit the narrow credit.
Passage corrections are bound to the identified source content. If changed bytes
or boundaries invalidate that passage ID, the correction remains in history and
appears in `status` as orphaned passage curation. Inspect the replacement before
reapplying; do not transfer by title, ordinal, or nearby text alone.
Preserve unresolved warnings. If local text cannot settle a consequential
credit, use the matching edition in Logos or another reliable source, recording
which source resolved it; don't assume a different edition has identical credits.

For study Bibles, cite scholarly introductions, annotations, and sidebars under
their supported contributor as material in the edited volume. Cite Scripture
itself by biblical book, chapter/verse, and translation under the task's required
style. An unknown note contributor is not automatically the volume editor or
an anonymous author. Keep unresolved drafts marked for review. For unpaginated
exports, use a verified contribution title and section locator; a Word screen
page or extraction ordinal is not a substitute for a printed page.

## When improving automatic detection

Prefer a narrow parser for an observed source pattern over a universal rule
that treats person-like text as bylines. Retain evidence locators and confidence,
respect durable corrections, and leave unsupported matches unverified. Check
representative boundaries, split files, changed formatting, quoted names,
unsigned contributions, and shared notes before generalizing a pattern.
Successful detection in one source is a reusable technique to investigate,
not a guarantee for all books.
