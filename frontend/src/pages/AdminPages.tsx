import { useState } from 'react';
import { Link } from 'react-router-dom';
import { appendSuggestion, SuggestionInput } from '../components/SuggestionInput';
import { StructuralIssues } from './ReadingPages';
import {
  BookRow,
  DefinitionList,
  Message,
  PageLoading,
  PageMessages,
  Pagination,
  QueryForm,
  ResultCount,
  SafeLink,
  SortOptions,
  StructuredDetails,
  display,
  humanize,
  list,
  number,
  object,
  records,
  strings,
  text,
  useAdminPage,
  type JsonObject,
} from './AdminShared';

function Intro({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <section className="page-intro">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      {children}
    </section>
  );
}

function Tags({
  name,
  label,
  value,
  kind,
  help,
  exclude,
  maximum = 6000,
}: {
  name: string;
  label: string;
  value: unknown;
  kind?: string;
  help?: string;
  exclude?: string;
  maximum?: number;
}) {
  const [entry, setEntry] = useState('');
  const [error, setError] = useState('');
  const [lines, setLines] = useState(
    Array.isArray(value) ? strings(value).join('\n') : text(value),
  );
  return (
    <div className="tag-editor">
      <label htmlFor={name}>{label}</label>
      <textarea
        id={name}
        name={name}
        rows={3}
        maxLength={maximum}
        value={lines}
        onChange={(event) => {
          setLines(event.target.value);
          setError('');
        }}
        aria-describedby={help ? `${name}-help` : undefined}
      />
      {help && (
        <p id={`${name}-help`} className="hint">
          {help}
        </p>
      )}
      {kind && (
        <div className="tag-picker">
          <SuggestionInput
            id={`${name}-find`}
            kind={kind}
            name={`${name}-lookup`}
            label={`Find or add ${label.toLowerCase()}`}
            value={entry}
            onChange={setEntry}
            maxLength={maximum}
            exclude={exclude}
          />
          <button
            type="button"
            className="secondary"
            onClick={() => {
              try {
                setLines(appendSuggestion(lines, entry, maximum));
                setEntry('');
                setError('');
              } catch (caught) {
                setError(
                  caught instanceof Error ? caught.message : 'The suggestion could not be added.',
                );
              }
            }}
          >
            Add to list
          </button>
        </div>
      )}
      <Message error>{error}</Message>
    </div>
  );
}

export function TaxonomyPage() {
  const s = useAdminPage();
  if (!s.page) return <PageLoading query={s.query} />;
  const vocabulary = object(s.data.vocabulary);
  return (
    <>
      <Intro eyebrow="Paths across the shelves" title="Subjects & connections.">
        <p className="lede">Follow an idea through the library, or give it another name.</p>
      </Intro>
      <QueryForm action="/taxonomy">
        <SuggestionInput
          id="vocabulary-query"
          name="q"
          kind="taxonomy"
          label="Find a subject, form, or other classification"
          defaultValue={text(vocabulary.query)}
          maxLength={300}
        />
        <button type="submit">Find classifications</button>
      </QueryForm>
      <p>
        <Link to="/taxonomy/new">Add a vocabulary term</Link>
      </p>
      <Message>{text(vocabulary.warning)}</Message>
      <section aria-labelledby="classifications-heading">
        <h2 id="classifications-heading">In the current collection</h2>
        <p>
          Counts are distinct books, including classifications attached to individual sections. A
          book can appear under several subjects. Missing labels do not mean missing content.
        </p>
        {records(vocabulary.facets).length ? (
          <ul className="book-list classification-list">
            {records(vocabulary.facets).map((item, i) => (
              <li key={i}>
                <h3>
                  <Link
                    to={`/taxonomy/browse?${new URLSearchParams({ facet: text(item.facet), value: text(item.value) })}`}
                  >
                    {text(item.label)}
                  </Link>
                </h3>
                <p>
                  {humanize(text(item.facet))} · {number(item.work_count)}{' '}
                  {number(item.work_count) === 1 ? 'book' : 'books'}
                </p>
                <p>
                  {item.term_id ? (
                    <Link to={`/taxonomy/term/${encodeURIComponent(text(item.term_id))}`}>
                      Edit {text(item.label)} in the vocabulary
                    </Link>
                  ) : (
                    <>
                      This classification is in use.{' '}
                      <Link
                        to={`/taxonomy/new?${new URLSearchParams({ label: text(item.value) })}`}
                      >
                        Add its aliases and connections
                      </Link>{' '}
                      when useful.
                    </>
                  )}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p>No indexed classifications match this search.</p>
        )}
      </section>
      <section aria-labelledby="vocabulary-heading">
        <h2 id="vocabulary-heading">The shared vocabulary</h2>
        <p>
          Aliases name the same idea. Broader and narrower terms organize it; related terms suggest
          lateral paths. These relationships are discovery aids, not claims of historical influence.
        </p>
        {records(vocabulary.terms).length ? (
          <ul className="book-list classification-list">
            {records(vocabulary.terms).map((term) => (
              <li key={text(term.id)}>
                <h3>
                  <Link to={`/taxonomy/term/${encodeURIComponent(text(term.id))}`}>
                    {text(term.label)}
                  </Link>
                </h3>
                {strings(term.aliases).length > 0 && (
                  <p>Also called: {strings(term.aliases).join(', ')}</p>
                )}
                <p className="hint">
                  {humanize(text(term.status, 'provisional'))} ·{' '}
                  {humanize(text(term.origin, 'codex'))}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p>
            No vocabulary terms match this search. Classification labels may exist before a
            vocabulary entry is added.
          </p>
        )}
      </section>
      <Pagination
        previous={s.data.previous_url}
        next={s.data.next_url}
        label="Classification pages"
        previousLabel="Previous classifications"
        nextLabel="Next classifications"
      />
    </>
  );
}

export function TaxonomyBooksPage() {
  const s = useAdminPage();
  if (!s.page) return <PageLoading query={s.query} />;
  const result = object(s.data.result);
  return (
    <>
      <p className="breadcrumb">
        <Link to="/taxonomy">Subjects & connections</Link>
      </p>
      <Intro eyebrow={humanize(text(result.facet))} title={`${text(s.data.label)}.`}>
        <p>
          Books classified at book or section level. Check the relevant passage and its attribution
          before citing.
        </p>
      </Intro>
      <QueryForm action="/taxonomy/browse" className="catalog-toolbar">
        <input type="hidden" name="facet" value={text(result.facet)} />
        <input type="hidden" name="value" value={text(result.value)} />
        <label htmlFor="classified-sort">Sort by</label>
        <select id="classified-sort" name="sort" defaultValue={text(s.data.sort, 'title')}>
          <SortOptions />
        </select>
        <button type="submit" className="secondary">
          Update order
        </button>
      </QueryForm>
      <ResultCount result={result} />
      {records(result.books).length ? (
        <ul className="catalog-list">
          {records(result.books).map((book) => (
            <li key={text(book.id)}>
              <BookRow book={book} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-state">
          {number(result.total) ? (
            <SafeLink href={s.data.first_page_url}>Return to the first page</SafeLink>
          ) : (
            'No currently available books have this classification. Unclassified books may still contain useful passages.'
          )}
        </p>
      )}
      <Pagination
        label="Classified book pages"
        previous={s.data.previous_url}
        next={s.data.next_url}
        previousLabel="Previous books"
        nextLabel="Next books"
      />
    </>
  );
}

export function TaxonomyTermPage() {
  const s = useAdminPage();
  if (!s.page) return <PageLoading query={s.query} />;
  const term = object(s.data.term),
    labels = object(s.data.relation_labels);
  return (
    <>
      <p className="breadcrumb">
        <Link to="/taxonomy">Subjects & connections</Link>
      </p>
      <Intro
        eyebrow="Shape the shared vocabulary"
        title={s.data.creating ? 'Add a term.' : `Edit ${text(term.label)}.`}
      >
        <p className="lede">Give an idea more than one route into the library.</p>
      </Intro>
      {Boolean(s.data.saved) && (
        <Message>
          The vocabulary term and its connections were saved. Source books and their classifications
          were not changed.
        </Message>
      )}
      <PageMessages data={s.data} error={s.error} />
      <form className="editor-form" onSubmit={s.submit(text(s.data.action))}>
        <label htmlFor="term-label">Name</label>
        <input
          id="term-label"
          name="label"
          defaultValue={text(term.label)}
          maxLength={160}
          required
        />
        <Tags
          name="aliases"
          label="Other names for the same idea"
          value={term.aliases}
          help="One name per line, or separate names with commas. For example, verse can be an alias for poetry."
        />
        <fieldset>
          <legend>Connections to existing vocabulary terms</legend>
          <p className="hint">
            Use names from the <Link to="/taxonomy">shared vocabulary</Link>. Add a missing term
            first. A connection can link disciplines without merging them.
          </p>
          <Tags
            name="broader"
            label="Broader ideas"
            value={labels.broader}
            kind="taxonomy"
            exclude={text(term.id)}
            help="For poetry, a broader idea might be literature."
          />
          <Tags
            name="narrower"
            label="More specific ideas"
            value={labels.narrower}
            kind="taxonomy"
            exclude={text(term.id)}
          />
          <Tags
            name="related"
            label="Related ideas"
            value={labels.related}
            kind="taxonomy"
            exclude={text(term.id)}
            help="Lateral connections, such as poetry and ecology. They suggest places to look, not agreement between authors."
          />
        </fieldset>
        <label htmlFor="term-evidence">Evidence or editorial reason</label>
        <textarea
          id="term-evidence"
          name="evidence"
          rows={4}
          maxLength={4000}
          required
          defaultValue={text(term.evidence)}
        />
        <p className="hint">
          Record why this wording or connection is useful. A source location or an explicit
          classification decision is enough.
        </p>
        <button disabled={s.busy} type="submit">
          {s.busy ? 'Saving…' : 'Save vocabulary term'}
        </button>
      </form>
    </>
  );
}

export function FocusesPage() {
  const s = useAdminPage();
  if (!s.page) return <PageLoading query={s.query} />;
  return (
    <>
      <Intro eyebrow="Questions worth returning to" title="Research focuses.">
        <p className="lede">
          Give an ongoing project a starting point, while leaving room for surprising connections.
        </p>
        <Link to="/focus/new" className="button">
          Create a focus
        </Link>
      </Intro>
      {records(s.data.focuses).length ? (
        <ul className="book-list focus-list">
          {records(s.data.focuses).map((focus) => (
            <li key={text(focus.id)}>
              <article>
                <h2>
                  <Link to={`/focus/${encodeURIComponent(text(focus.id))}`}>
                    {text(focus.name)}
                  </Link>
                </h2>
                <p>{text(focus.description)}</p>
                <p className="hint">Preferred breadth: {text(focus.breadth, 'balanced')}</p>
                <Link to={`/?focus=${encodeURIComponent(text(focus.id))}`}>
                  Search with {text(focus.name)}
                </Link>
              </article>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-state">
          No research focuses yet. A focus can follow a course, an article series, or a question
          that keeps finding you.
        </p>
      )}
    </>
  );
}

export function FocusPage() {
  const s = useAdminPage();
  if (!s.page) return <PageLoading query={s.query} />;
  const focus = object(s.data.focus),
    id = text(s.data.focus_id);
  return (
    <>
      <p className="breadcrumb">
        <Link to="/focus">Research focuses</Link>
      </p>
      <Intro eyebrow="A starting point, with room to wander" title={`${s.page.title}.`} />
      {Boolean(s.data.saved) && (
        <Message>
          Research focus saved.{' '}
          <Link to={`/?focus=${encodeURIComponent(id)}`}>Search with this focus</Link>.
        </Message>
      )}
      <PageMessages data={s.data} error={s.error} />
      <form onSubmit={s.submit(`/focus/${encodeURIComponent(id)}`)} className="editor-form">
        <label htmlFor="focus-name">Name</label>
        <input
          id="focus-name"
          name="name"
          defaultValue={text(focus.name)}
          maxLength={120}
          required
        />
        <label htmlFor="focus-description">What are you exploring?</label>
        <textarea
          id="focus-description"
          name="description"
          rows={4}
          maxLength={4000}
          defaultValue={text(focus.description)}
        />
        <p className="hint">
          These are discovery preferences; use explicit search filters when you want to exclude
          other material.
        </p>
        <Tags
          name="subjects"
          label="Subjects and questions (optional)"
          value={focus.subjects}
          kind="subjects"
          maximum={4000}
        />
        <Tags
          name="forms"
          label="Forms or genres (optional)"
          value={focus.forms}
          kind="forms"
          maximum={4000}
        />
        <label htmlFor="focus-breadth">Preferred search breadth</label>
        <select id="focus-breadth" name="breadth" defaultValue={text(focus.breadth, 'balanced')}>
          {['focused', 'balanced', 'exploratory'].map((mode) => (
            <option key={mode} value={mode}>
              {humanize(mode)}
            </option>
          ))}
        </select>
        <div className="form-actions">
          <button type="submit" disabled={s.busy}>
            {s.busy ? 'Saving…' : 'Save focus'}
          </button>
          <Link to="/focus">Cancel</Link>
        </div>
      </form>
      <section className="preferred-books-panel">
        <h2>Preferred books</h2>
        {id === 'new' ? (
          <p>Save this focus first, then choose preferred books from the full library.</p>
        ) : (
          <>
            <p>
              {list(focus.books).length} books currently selected. Save any changes to the details
              above before managing book choices.
            </p>
            <Link to={`/focus/${encodeURIComponent(id)}/books`}>
              Search and manage preferred books
            </Link>
          </>
        )}
      </section>
    </>
  );
}

export function FocusBooksPage() {
  const s = useAdminPage();
  if (!s.page) return <PageLoading query={s.query} />;
  const focus = object(s.data.focus),
    result = object(s.data.result),
    base = `/focus/${encodeURIComponent(text(focus.id))}/books`;
  return (
    <>
      <p className="breadcrumb">
        <Link to={`/focus/${encodeURIComponent(text(focus.id))}`}>{text(focus.name)}</Link>
      </p>
      <Intro eyebrow="Keep a few books close" title="Preferred books.">
        <p>
          Give selected books more emphasis in {text(focus.name)}. The rest of the library stays in
          reach.
        </p>
        <p>{list(focus.books).length} books selected across the library.</p>
      </Intro>
      {Boolean(s.data.saved) && (
        <Message>
          Your choices on this page were saved. Selections on other pages are unchanged.
        </Message>
      )}
      <PageMessages data={s.data} error={s.error} />
      <QueryForm action={base} className="catalog-toolbar">
        <SuggestionInput
          id="preferred-query"
          name="q"
          kind="catalog"
          label="Find a book or creator"
          defaultValue={text(s.data.q)}
          maxLength={300}
        />
        <label htmlFor="preferred-sort">Sort by</label>
        <select id="preferred-sort" name="sort" defaultValue={text(s.data.sort, 'title')}>
          <SortOptions />
        </select>
        <button type="submit">Find books</button>
      </QueryForm>
      <ResultCount result={result} />
      {records(s.data.books).length ? (
        <form
          className="editor-form catalog-selection"
          onSubmit={s.submit(base)}
          key={`${text(s.data.q)}:${text(s.data.offset)}:${text(s.data.sort)}`}
        >
          <input type="hidden" name="q" value={text(s.data.q)} />
          <input type="hidden" name="offset" value={text(s.data.offset, '0')} />
          <input type="hidden" name="sort" value={text(s.data.sort, 'title')} />
          <fieldset className="book-choices">
            <legend>Books on this page</legend>
            <p className="hint">
              Save your choices before searching or moving to another page. Unchecking a book
              removes its preference; your other selections stay intact.
            </p>
            <ul className="catalog-list">
              {records(s.data.books).map((book, i) => (
                <li key={text(book.id)}>
                  <BookRow
                    book={book}
                    choice={`preferred-${i}`}
                    checked={strings(focus.books).includes(text(book.id))}
                  />
                </li>
              ))}
            </ul>
          </fieldset>
          <button type="submit" disabled={s.busy}>
            Save choices on this page
          </button>
        </form>
      ) : (
        <p className="empty-state">
          {number(result.total) ? (
            <SafeLink href={s.data.first_page_url}>Return to the first page</SafeLink>
          ) : (
            'No books matched. Try a shorter title or a creator’s name.'
          )}
        </p>
      )}
      <Pagination
        label="Preferred-book pages"
        previous={s.data.previous_url}
        next={s.data.next_url}
        previousLabel="Previous books"
        nextLabel="Next books"
      />
      <p>
        <Link to={`/focus/${encodeURIComponent(text(focus.id))}`}>
          Return to {text(focus.name)}
        </Link>
      </p>
    </>
  );
}

export function HistoryPage() {
  const s = useAdminPage();
  if (!s.page) return <PageLoading query={s.query} />;
  return (
    <>
      <Intro eyebrow="Where the reading went" title="Research history.">
        <p className="lede">
          Your saved uses and notes, across classes, articles, and other projects.
        </p>
      </Intro>
      {records(s.data.entries).length ? (
        <ol className="history-list">
          {records(s.data.entries).map((entry, i) => {
            const href = entry.selection_id
              ? `/selections/${encodeURIComponent(text(entry.selection_id))}?action=record`
              : entry.unit_id
                ? `/units/${encodeURIComponent(text(entry.unit_id))}`
                : entry.passage_id
                  ? `/read/${encodeURIComponent(text(entry.passage_id))}`
                  : '';
            return (
              <li key={text(entry.id, String(i))}>
                <article>
                  <h2>
                    {href ? (
                      <Link to={href}>{text(entry.title, 'Saved source')}</Link>
                    ) : (
                      text(entry.title, 'Research note')
                    )}
                  </h2>
                  <DefinitionList
                    data={{
                      ...entry,
                      kind: humanize(text(entry.kind)),
                      purpose: humanize(text(entry.purpose)),
                      target_scope: humanize(text(entry.target_scope)),
                    }}
                    labels={[
                      ['target_scope', 'Source scope'],
                      ['created_at', 'Recorded'],
                      ['kind', 'Activity'],
                      ['purpose', 'Purpose'],
                      ['destination', 'Lesson, article, or project'],
                      ['attribution', 'Attribution'],
                      ['location', 'Source location'],
                      ['notes', 'Your note'],
                    ]}
                  />
                  {text(entry.evidence) && entry.evidence !== entry.notes && (
                    <p>
                      <strong>Evidence:</strong> {text(entry.evidence)}
                    </p>
                  )}
                </article>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="empty-state">
          No research uses recorded yet. Open a passage and use “Keep a research note” to save one.
        </p>
      )}
    </>
  );
}

export function StatusPage() {
  const s = useAdminPage();
  if (!s.page) return <PageLoading query={s.query} />;
  const status = object(s.data.status),
    semantic = object(status.semantic),
    freshness = object(status.freshness),
    structure = object(status.structure),
    citations = object(status.citations),
    budget = object(status.budget);
  return (
    <>
      <Intro eyebrow="A changing library" title="Library status.">
        <p className="lede">See what is indexed and where the collection still has gaps.</p>
      </Intro>
      <button
        className="secondary"
        type="button"
        disabled={s.query.isFetching || s.busy}
        onClick={() => void s.query.refetch()}
      >
        Refresh status
      </button>
      <PageMessages data={s.data} error={s.error} />
      {Boolean(s.data.synced) && (
        <Message>
          The library sync finished. Review the current coverage and any limitations below.
        </Message>
      )}
      <section className="status-panel" aria-labelledby="coverage-heading">
        <h2 id="coverage-heading">Current coverage</h2>
        <DefinitionList
          data={status}
          labels={[
            ['books', 'Books'],
            ['ready_files', 'Indexed source files'],
            ['sections', 'Sections'],
            ['passages', 'Passages'],
          ]}
        />
        {Object.keys(freshness).length > 0 && (
          <p className={freshness.fresh ? undefined : 'notice'}>
            {freshness.fresh
              ? 'The indexed file inventory matches the current local files.'
              : 'The local files have changed since indexing. Sync the library to include additions and changes and remove unavailable passages.'}
          </p>
        )}
        {number(status.metadata_pending) > 0 && (
          <p>{number(status.metadata_pending)} books still need subject or contributor review.</p>
        )}
        <h3>Semantic coverage</h3>
        {Object.keys(semantic).length > 0 ? (
          <>
            <p>
              <strong>{number(semantic.coverage_books)}</strong> of {number(status.books)} books
              available for meaning-based search.{' '}
              <span className="hint">{humanize(text(semantic.state, 'unknown'))}</span>
            </p>
            <details>
              <summary>Semantic index details</summary>
              <StructuredDetails value={semantic} />
            </details>
          </>
        ) : (
          <p>
            No semantic index is recorded. Exact-text and structural search can work independently.
          </p>
        )}
        {Boolean(status.failures) && (
          <>
            <h3>Files needing attention</h3>
            <StructuredDetails value={status.failures} />
          </>
        )}
        <details className="coverage">
          <summary>Full index details and file changes</summary>
          <StructuredDetails value={status} />
        </details>
      </section>
      {Object.keys(structure).length > 0 && (
        <section aria-labelledby="structure-status-heading">
          <h2 id="structure-status-heading">Book structure</h2>
          <p>
            {number(structure.supported)} books have supported structure;{' '}
            {number(structure.needs_review)} need structural review.
          </p>
          <p className="hint">
            Structural quality is separate from readable text and semantic coverage. Unresolved
            boundaries do not prevent research.
          </p>
          <details>
            <summary>Structural review list</summary>
            <p>
              Repeated findings are grouped by reason.{' '}
              <a href="/api/status">Detailed library report (JSON)</a>
            </p>
            <ul>
              {records(structure.review_books || structure.books).map((book, i) => (
                <li key={i}>
                  <Link to={`/books/${encodeURIComponent(text(book.work_id || book.id))}`}>
                    {text(book.title)}
                  </Link>
                  {Boolean(book.issues) && <StructuralIssues items={list(book.issues)} />}
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}
      {Object.keys(citations).length > 0 && (
        <section aria-labelledby="citation-coverage-heading">
          <h2 id="citation-coverage-heading">Citation metadata</h2>
          <p>
            {number(citations.books_with_title_creator_publisher_year_verified)} of{' '}
            {number(status.books)} books have source-verified title, creator, publisher, and
            publication year. {number(citations.books_needing_core_metadata_review)} still need some
            of those fields checked.
          </p>
          <p className="hint">
            This is book-level coverage. Each passage’s citation also checks contributor
            attribution, edition details, and its page or section locator.
          </p>
          {records(citations.review_sample).length > 0 && (
            <details>
              <summary>Books with metadata to review</summary>
              <ul>
                {records(citations.review_sample).map((book) => (
                  <li key={text(book.work_id)}>
                    <Link to={`/review/${encodeURIComponent(text(book.work_id))}`}>
                      {text(book.title)}
                    </Link>{' '}
                    — {strings(book.needs_review).join(', ')}
                  </li>
                ))}
              </ul>
              <p className="hint">
                Showing up to twelve books. Citation pages flag the specific gaps for any passage.
              </p>
            </details>
          )}
        </section>
      )}
      <section className="sync-panel" aria-labelledby="sync-heading">
        <h2 id="sync-heading">Changed something on the shelves?</h2>
        <p>
          Sync checks the current local files for additions, changes, and removals. This updates the
          text index and adds new or changed passages to the approved OpenAI semantic index within
          the library’s spending limits. Unchanged passages reuse cached embeddings.
        </p>
        <button type="button" disabled={s.busy} onClick={() => void s.action('/sync')}>
          {s.busy ? 'Syncing…' : 'Sync library'}
        </button>
        <p className="hint">
          Large changes may take a little time. Leave this page open while the sync completes.
        </p>
      </section>
      {Object.keys(budget).length > 0 && (
        <section aria-labelledby="budget-heading">
          <h2 id="budget-heading">Library API spending</h2>
          <p>
            Amounts include reservations for requests whose outcome is uncertain. Exact search
            remains available at every ceiling.
          </p>
          <dl className="metadata-grid">
            {Object.entries(object(budget.ceilings)).map(([scope, ceiling]) => (
              <div key={scope}>
                <dt>{humanize(scope)}</dt>
                <dd>
                  ${number(object(budget.spent_or_reserved)[scope]).toFixed(4)} of $
                  {number(ceiling).toFixed(2)}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}
    </>
  );
}

export function MetadataPage() {
  const s = useAdminPage();
  const [chosen, setChosen] = useState('');
  const [json, setJson] = useState(false);
  const [value, setValue] = useState(''),
    [suggestion, setSuggestion] = useState(''),
    [suggestionError, setSuggestionError] = useState('');
  if (!s.page) return <PageLoading query={s.query} />;
  const work = object(s.data.work),
    target = object(s.data.target),
    targetId = text(s.data.target_id);
  const field = chosen || strings(s.data.fields)[0] || '';
  const suggestionKind = text(object(s.data.suggestion_kinds)[field]);
  const textTypes = strings(s.data.text_types);
  const selectedType = textTypes.includes(value.trim()) ? value.trim() : '';
  const replacesValue = ['author', 'attribution'].includes(field);
  const valueHelp = json
    ? 'Enter valid JSON. Existing text is preserved; suggestions are disabled while you edit structured data.'
    : replacesValue
      ? 'Enter the complete credit, or find a recorded contributor and choose Use value. Check the source before assigning a name.'
      : ['title', 'notes'].includes(field)
        ? 'Enter the complete text supported by the source.'
        : 'Choose recorded values with Add, or type your own. Separate values with commas or new lines. These suggestions do not verify a classification.';
  const bookUrl = `/books/${encodeURIComponent(text(work.id))}?section_offset=${text(s.data.section_offset, '0')}`;
  return (
    <>
      <p className="breadcrumb">
        <Link to={bookUrl}>{text(work.title)}</Link>
      </p>
      <Intro eyebrow="Make the library more faithful" title="Edit library information.">
        <p className="lede">{text(target.title || work.title)}</p>
        <p>Your correction is recorded with its evidence. The original book file stays intact.</p>
      </Intro>
      {Boolean(s.data.saved) && <Message>Correction saved.</Message>}
      <PageMessages data={s.data} error={s.error} />
      <p className="notice">
        <Link
          to={`/review/${encodeURIComponent(targetId)}?section_offset=${text(s.data.section_offset, '0')}`}
        >
          Open the guided review for {text(target.title || work.title)}
        </Link>{' '}
        to see current values, source evidence, draft changes, and optional AI suggestions.
      </p>
      <form
        onSubmit={s.submit(`/metadata/${encodeURIComponent(targetId)}`)}
        className="editor-form"
      >
        <input type="hidden" name="work_id" value={text(work.id)} />
        <input type="hidden" name="section_offset" value={text(s.data.section_offset, '0')} />
        <label htmlFor="metadata-field">Field to correct</label>
        <select
          id="metadata-field"
          name="field"
          value={field}
          onChange={(event) => {
            setChosen(event.target.value);
            setSuggestion('');
            setSuggestionError('');
          }}
        >
          {strings(s.data.fields).map((key) => (
            <option key={key} value={key}>
              {humanize(key)}
            </option>
          ))}
        </select>
        {field === 'text_type' && !json ? (
          <>
            <label htmlFor="metadata-value">Correct kind of writing</label>
            <select
              id="metadata-value"
              name="value"
              required
              value={selectedType}
              onChange={(event) => setValue(event.target.value)}
              aria-describedby="metadata-value-help"
            >
              <option value="">Choose a kind of writing</option>
              {textTypes.map((type) => (
                <option value={type} key={type}>
                  {humanize(type)}
                </option>
              ))}
            </select>
            <p id="metadata-value-help" className="hint">
              Choose the type supported by this section’s actual content. Mixed preserves the
              distinction when more than one type occurs.
            </p>
          </>
        ) : (
          <>
            <label htmlFor="metadata-value">Correct value</label>
            <textarea
              id="metadata-value"
              name="value"
              rows={4}
              required
              maxLength={6000}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              aria-describedby="metadata-value-help"
            />
            <p id="metadata-value-help" className="hint">
              {valueHelp}
            </p>
          </>
        )}
        {!json && suggestionKind && (
          <div className="tag-picker">
            <SuggestionInput
              id="metadata-suggestion"
              name="metadata-suggestion"
              kind={suggestionKind}
              label="Find a recorded value"
              value={suggestion}
              onChange={setSuggestion}
              maxLength={6000}
            />
            <button
              type="button"
              className="secondary"
              onClick={() => {
                if (!suggestion.trim()) {
                  setSuggestionError('Enter or choose a value first.');
                  return;
                }
                try {
                  setValue(appendSuggestion(replacesValue ? '' : value, suggestion));
                  setSuggestion('');
                  setSuggestionError('');
                } catch (caught) {
                  setSuggestionError(
                    caught instanceof Error ? caught.message : 'The suggestion could not be added.',
                  );
                }
              }}
            >
              {replacesValue ? 'Use value' : 'Add to value'}
            </button>
          </div>
        )}
        <Message error>{suggestionError}</Message>
        <details>
          <summary>Structured value — advanced</summary>
          <label className="checkbox-label">
            <input
              type="checkbox"
              name="value_format"
              value="json"
              checked={json}
              onChange={(event) => {
                setJson(event.target.checked);
                setSuggestion('');
                setSuggestionError('');
              }}
            />{' '}
            Interpret the value above as JSON
          </label>
        </details>
        <label htmlFor="metadata-evidence">Source or reason for the correction</label>
        <textarea
          id="metadata-evidence"
          name="evidence"
          rows={3}
          required
          maxLength={4000}
          aria-describedby="metadata-evidence-help"
        />
        <p id="metadata-evidence-help" className="hint">
          For example, “Contributor name on the chapter title page,” with a page or section
          location.
        </p>
        <div className="form-actions">
          <button type="submit" disabled={s.busy}>
            Save correction
          </button>
          <Link to={bookUrl}>Back to book</Link>
        </div>
      </form>
      {Boolean(target.profile) && (
        <details className="coverage">
          <summary>Current recorded information</summary>
          <StructuredDetails value={target.profile} />
        </details>
      )}
    </>
  );
}

function NameRole({
  role,
  target,
  inherited,
}: {
  role: string;
  target: JsonObject;
  inherited: unknown;
}) {
  const record = object(target.record),
    people = records(record[role]);
  return (
    <fieldset>
      <legend>{humanize(role)}</legend>
      {role === 'translators' && Boolean(target.is_section) && (
        <>
          <label className="checkbox-label">
            <input
              type="checkbox"
              id="translators-override"
              name="translators_override"
              value="yes"
              defaultChecked={record.translators !== null && record.translators !== undefined}
              aria-describedby="translators-inheritance"
            />{' '}
            Override the book’s translation credit for this contribution.
          </label>
          <p id="translators-inheritance" className="hint">
            Leave unchecked to inherit the book’s translation credit. When checked, these names
            replace that credit; blank names explicitly mean no named translator.
          </p>
          <p>
            Current book translation credit:{' '}
            {records(inherited).length ? display(inherited) : 'None recorded'}.
          </p>
        </>
      )}
      <Tags
        name={role}
        label="Names as printed — one per line"
        value={people.map(display)}
        kind="authors"
      />
      <label htmlFor={`${role}-short`}>
        Short names or family names — corresponding lines (optional)
      </label>
      <textarea
        id={`${role}-short`}
        name={`${role}_short`}
        rows={2}
        defaultValue={people.map((person) => text(person.short)).join('\n')}
      />
      {role === 'authors' && (
        <>
          <label className="checkbox-label">
            <input
              type="checkbox"
              id="authors-absent"
              name="authors_absent"
              value="yes"
              defaultChecked={Array.isArray(record.authors) && record.authors.length === 0}
              aria-describedby="authors-unknown"
            />{' '}
            No named author appears in this source (verified).
          </label>
          <p id="authors-unknown" className="hint">
            Leave names blank and this box unchecked when authorship is unknown. Keep an editor or
            translator in the appropriate role.
          </p>
        </>
      )}
      <p className="hint">
        Names are preserved as entered. Use “Rowland Abiodun” above and “Abiodun” as the short name,
        for example. Corporate and culturally different name forms should not be guessed.
      </p>
    </fieldset>
  );
}

export function BibliographyPage() {
  const s = useAdminPage();
  if (!s.page) return <PageLoading query={s.query} />;
  const target = object(s.data.target),
    record = object(target.record);
  return (
    <>
      <p className="breadcrumb">
        <Link to={`/books/${encodeURIComponent(text(target.work_id))}`}>
          {text(target.work_title)}
        </Link>
        {text(s.data.passage_id) && (
          <>
            {' '}
            ·{' '}
            <Link to={`/cite/${encodeURIComponent(text(s.data.passage_id))}`}>
              Back to citation
            </Link>
          </>
        )}
      </p>
      <Intro eyebrow="Faithful attribution" title="Citation details.">
        <p className="lede">{text(target.title)}</p>
        <p>
          Enter details for the edition you actually read, using its title and publication pages.
          Leave unknown values blank. Suggestions reuse recorded spellings; check them against this
          edition before saving.
        </p>
      </Intro>
      {target.is_passage ? (
        <aside className="notice">
          <h2>This passage only</h2>
          <p>
            Changes apply only to this indexed passage, not the whole section or neighboring
            biblical text, quotations, or commentary. Unchanged details inherit the containing
            section. Check that the entire passage belongs to the credited contribution. If the
            source changes and this passage can no longer be identified, the correction is retained
            for review instead of transferred automatically.
          </p>
        </aside>
      ) : (
        Boolean(target.is_section) && (
          <p className="notice">
            Changes apply to the entire indexed section. Use passage-only attribution when the
            section includes different authors or source types.
          </p>
        )
      )}
      {Boolean(s.data.saved) && <Message>Citation details saved.</Message>}
      {Boolean(s.data.unchanged) && (
        <Message>
          No citation details changed. Existing verification and source evidence were preserved.
        </Message>
      )}
      <PageMessages data={s.data} error={s.error} />
      <details>
        <summary>Existing catalog clues — verify against the source</summary>
        <p>{text(target.catalog_author)}</p>
        <StructuredDetails value={target.catalog_hints} />
      </details>
      <p className="notice">
        <Link
          to={`/review/${encodeURIComponent(text(target.id))}${s.data.passage_id ? `?passage=${encodeURIComponent(text(s.data.passage_id))}` : ''}`}
        >
          Open the guided review for {text(target.title)}
        </Link>{' '}
        to see current values, source evidence, draft changes, and optional AI suggestions.
      </p>
      <form
        onSubmit={s.submit(`/bibliography/${encodeURIComponent(text(target.id))}`)}
        className="editor-form"
      >
        <input type="hidden" name="passage_id" value={text(s.data.passage_id)} />
        {Boolean(target.is_section) && (
          <>
            <label htmlFor="bibliography-type">Contribution type</label>
            <select name="type" id="bibliography-type" defaultValue={text(record.type, 'chapter')}>
              {['chapter', 'poem', 'entry', 'scripture'].map((key) => (
                <option key={key} value={key}>
                  {humanize(key)}
                </option>
              ))}
            </select>
            <p className="hint">
              Book-level publisher and edition details are inherited for commentary. For Scripture,
              record its translation and a verified biblical reference; do not enter the commentary
              scholar as its author.
            </p>
            <label htmlFor="scripture-scope">Scripture scope (Scripture only)</label>
            <select
              id="scripture-scope"
              name="scripture_scope"
              defaultValue={text(record.scripture_scope)}
              aria-describedby="scripture-scope-help"
            >
              <option value="">Not applicable or not checked</option>
              <option value="text_only">Entire target is biblical text</option>
              <option value="mixed">Includes notes, commentary, or other material</option>
            </select>
            <p id="scripture-scope-help" className="hint">
              Only confirm biblical text after checking every included block. A mixed target needs
              separate citations for its components.
            </p>
          </>
        )}
        {Object.entries(object(s.data.fields)).map(([key, label]) => {
          const kind = (
            {
              publisher: 'publishers',
              format: 'formats',
              bible_translation: 'translations',
              bible_translation_short: 'translation_short',
            } as Record<string, string>
          )[key];
          return kind ? (
            <SuggestionInput
              key={key}
              id={`bib-${key}`}
              name={key}
              label={text(label)}
              kind={kind}
              defaultValue={text(record[key])}
              maxLength={2000}
            />
          ) : (
            <div key={key}>
              <label htmlFor={`bib-${key}`}>{text(label)}</label>
              <input
                id={`bib-${key}`}
                name={key}
                type={key === 'url' ? 'url' : 'text'}
                defaultValue={text(record[key])}
                maxLength={2000}
                autoCapitalize={key === 'doi' || key === 'url' ? 'off' : undefined}
                spellCheck={key === 'doi' || key === 'url' ? false : undefined}
              />
            </div>
          );
        })}
        {strings(s.data.roles).map((role) => (
          <NameRole
            key={role}
            role={role}
            target={target}
            inherited={s.data.inherited_translators}
          />
        ))}
        <label className="checkbox-label">
          <input
            type="checkbox"
            id="verify-unchanged"
            name="verify_unchanged"
            value="yes"
            aria-describedby="verify-unchanged-help"
          />{' '}
          Also verify unchanged displayed details against this evidence.
        </label>
        <p id="verify-unchanged-help" className="hint">
          Leave unchecked to preserve the source and verification status of every unchanged field.
          Check only after verifying all displayed nonblank details and explicit author-absence or
          translation-override statements. Blank unknowns remain unknown; inherited book details and
          catalog clues are not included.
        </p>
        <label htmlFor="bibliography-evidence">What source details did you verify?</label>
        <textarea
          id="bibliography-evidence"
          name="evidence"
          rows={4}
          required
          maxLength={4000}
          aria-describedby="bibliography-evidence-help"
        />
        <p id="bibliography-evidence-help" className="hint">
          Identify the title page, publication page, chapter heading, or other evidence and its
          location. This evidence verifies your changed fields, plus unchanged displayed details
          only when you explicitly check the option above.
        </p>
        <button type="submit" disabled={s.busy}>
          Save citation details
        </button>
      </form>
    </>
  );
}
