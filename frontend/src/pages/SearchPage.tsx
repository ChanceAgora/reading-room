import { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { apiAction, isPage, usePage } from '../api';
import type { Fields, JsonObject, UiPage } from '../api';
import { humanize, object, records, safeHref, strings, text } from '../data';
import { ErrorMessage, FragmentLink, Limitations, ObjectDetails, PageState } from '../ui';
import { SuggestionInput } from '../components/SuggestionInput';

const names = [
  'q',
  'focus',
  'mode',
  'engine',
  'subject',
  'form',
  'book',
  'author',
  'text_type',
] as const;
type SearchFields = Record<(typeof names)[number], string>;
interface Snapshot {
  version: 2;
  fields: SearchFields;
  result: JsonObject | null;
  submitted: string;
  disclosures: string[];
}
export function restoreSearch(value: unknown): Snapshot | null {
  const saved = object(value),
    fields = object(saved.fields);
  if (
    saved.version !== 2 ||
    (saved.result !== null &&
      (!saved.result || typeof saved.result !== 'object' || Array.isArray(saved.result))) ||
    typeof saved.submitted !== 'string' ||
    names.some((name) => typeof fields[name] !== 'string' || text(fields[name]).length > 1500)
  )
    return null;
  return {
    version: 2,
    fields: fields as SearchFields,
    result: saved.result === null ? null : object(saved.result),
    submitted: saved.submitted,
    disclosures: strings(saved.disclosures),
  };
}
function readSnapshot(state: unknown): Snapshot | null {
  return restoreSearch(object(state).readingRoomSearch);
}
function initialFields(search: string): SearchFields {
  const params = new URLSearchParams(search);
  return Object.fromEntries(names.map((name) => [name, params.get(name) ?? ''])) as SearchFields;
}

export function SearchPage() {
  const location = useLocation();
  const carriedSession = object(location.state).readingRoomSearchSession;
  const sessionKey = typeof carriedSession === 'string' ? carriedSession : location.key;
  // Separate browser entries own separate drafts. An explicit submission carries
  // its session through the canonical-URL replacement, preserving newer typing
  // and focus while the request finishes.
  return <SearchEntry key={sessionKey} sessionKey={sessionKey} />;
}

function SearchEntry({ sessionKey }: { sessionKey: string }) {
  const location = useLocation(),
    navigate = useNavigate();
  const restored = useRef(readSnapshot(location.state));
  const [fields, setFields] = useState<SearchFields>(
    () => restored.current?.fields ?? initialFields(location.search),
  );
  const fieldsRef = useRef(fields);
  fieldsRef.current = fields;
  const [result, setResult] = useState<JsonObject | null>(restored.current?.result ?? null);
  const [submitted, setSubmitted] = useState(restored.current?.submitted ?? '');
  const [disclosures, setDisclosures] = useState<string[]>(
    restored.current?.disclosures ?? (location.search ? ['filters'] : []),
  );
  // Navigation loads only form metadata. URL fields and saved drafts never
  // execute a search; results come only from a snapshot or an explicit POST.
  const query = usePage('/');
  const [message, setMessage] = useState(() =>
    !restored.current?.result && fields.q
      ? 'This search has no saved results. Choose Search the library to run it.'
      : '',
  );
  const [storageNotice, setStorageNotice] = useState(false);
  const running = useRef(false),
    revision = useRef(0);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const mutation = useMutation({ mutationFn: (values: Fields) => apiAction('/search', values) });
  const currentResult = result;
  const currentSubmitted = submitted;

  useEffect(() => {
    const snapshot: Snapshot = {
      version: 2,
      fields,
      result: currentResult,
      submitted: currentSubmitted,
      disclosures,
    };
    try {
      if (JSON.stringify(snapshot).length > 2_000_000) throw new Error('Snapshot too large');
      const state = window.history.state as Record<string, unknown> | null;
      const usr = object(state?.usr);
      window.history.replaceState(
        {
          ...state,
          usr: { ...usr, readingRoomSearch: snapshot, readingRoomSearchSession: sessionKey },
        },
        '',
      );
    } catch {
      setStorageNotice(true);
    }
  }, [fields, currentResult, currentSubmitted, disclosures, sessionKey]);

  function update(name: keyof SearchFields, value: string) {
    revision.current++;
    setFields((old) => ({ ...old, [name]: value }));
  }
  async function search(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (running.current) return;
    running.current = true;
    const values = { ...fieldsRef.current },
      startRevision = revision.current,
      focus = document.activeElement,
      scroll = window.scrollY;
    setMessage('Searching the library…');
    try {
      const page = await mutation.mutateAsync(values);
      // A completed paid request must never navigate a user who already left.
      if (!mounted.current) return;
      if (!isPage(page)) throw new Error('The search returned an unexpected response.');
      const nextResult = object(page.data.result);
      const direct = records(nextResult.direct).length,
        connections = records(nextResult.connections).length;
      const snapshot: Snapshot = {
        version: 2,
        fields: fieldsRef.current,
        result: nextResult,
        submitted: values.q,
        disclosures,
      };
      // Commit the history entry before exposing result links. Otherwise a fast
      // click can navigate away while this replacement is still pending.
      if (location.pathname !== '/search' || location.search) {
        try {
          await navigate('/search', {
            replace: true,
            state: {
              ...object(location.state),
              readingRoomSearch: snapshot,
              readingRoomSearchSession: sessionKey,
            },
            preventScrollReset: true,
          });
        } catch {
          if (mounted.current) setStorageNotice(true);
        }
      }
      if (!mounted.current) return;
      setResult(nextResult);
      setSubmitted(values.q);
      setMessage(
        `${direct} direct ${direct === 1 ? 'match' : 'matches'}${connections ? ` and ${connections} wider ${connections === 1 ? 'connection' : 'connections'}` : ''} for ${values.q}.`,
      );
      if (
        revision.current === startRevision &&
        document.activeElement === focus &&
        window.scrollY === scroll
      )
        requestAnimationFrame(() =>
          document.getElementById('search-results')?.focus({ preventScroll: true }),
        );
    } catch {
      if (mounted.current)
        setMessage(
          'The search did not finish. Previous results are kept. Submit again only if you want to retry.',
        );
    } finally {
      running.current = false;
    }
  }
  function disclosure(name: string, open: boolean) {
    setDisclosures((old) =>
      open ? [...new Set([...old, name])] : old.filter((item) => item !== name),
    );
  }
  return (
    <PageState query={query}>
      {(page: UiPage) => (
        <>
          <section
            id="search-intro"
            className={`page-intro${currentResult ? ' search-results-intro' : ''}`}
          >
            <p className="eyebrow">Ideas have more than one address</p>
            <h1>Find a thread.</h1>
            {!currentResult && (
              <p className="lede">
                Start with a passage, a question, or something you can’t quite name. Follow it
                across the shelves.
              </p>
            )}
            {currentResult && (
              <p className="results-jump">
                <FragmentLink href="#search-results">Go to results</FragmentLink>
              </p>
            )}
          </section>
          <form
            onSubmit={(event) => void search(event)}
            className="search-form"
            id="research-search-form"
          >
            <label htmlFor="q">What are you researching?</label>
            <div className="search-row">
              <input
                id="q"
                name="q"
                type="search"
                value={fields.q}
                onChange={(e) => update('q', e.target.value)}
                maxLength={1500}
                required
                placeholder="A passage, a phrase, or a research question"
                aria-describedby="search-help"
              />
              <button type="submit" aria-disabled={mutation.isPending}>
                {mutation.isPending ? 'Searching…' : 'Search the library'}
              </button>
            </div>
            <p id="search-help" className="hint">
              Try “memory and place” or “how communities respond to change.”
            </p>
            <div className="form-grid">
              <div>
                <label htmlFor="focus">Research focus</label>
                <select
                  id="focus"
                  name="focus"
                  value={fields.focus}
                  onChange={(e) => update('focus', e.target.value)}
                >
                  <option value="">Whole library</option>
                  {records(page.data.focuses).map((item) => (
                    <option key={text(item.id)} value={text(item.id)}>
                      {text(item.name)}
                    </option>
                  ))}
                </select>
                <p className="hint">
                  A focus guides discovery; it does not replace the wider library.
                </p>
              </div>
              <div>
                <label htmlFor="mode">Search breadth</label>
                <select
                  id="mode"
                  name="mode"
                  value={fields.mode}
                  onChange={(e) => update('mode', e.target.value)}
                >
                  <option value="">Use focus preference — otherwise balanced</option>
                  <option value="focused">Focused — closer matches</option>
                  <option value="balanced">Balanced — matches and connections</option>
                  <option value="exploratory">Exploratory — more room to wander</option>
                </select>
              </div>
            </div>
            <details
              className="search-method"
              open={disclosures.includes('method')}
              onToggle={(e) => disclosure('method', e.currentTarget.open)}
            >
              <summary>Search method</summary>
              <label htmlFor="engine">How to search</label>
              <select
                id="engine"
                name="engine"
                value={fields.engine}
                onChange={(e) => update('engine', e.target.value)}
              >
                <option value="">Text and meaning — recommended</option>
                <option value="exact">Exact text only — entirely local</option>
              </select>
              <p className="hint">
                Text and meaning uses the configured OpenAI model to find related ideas. Exact
                search, reading, and citations work without an API connection.
              </p>
            </details>
            <details
              className="filter-details"
              open={disclosures.includes('filters')}
              onToggle={(e) => disclosure('filters', e.currentTarget.open)}
            >
              <summary>
                Limit the results <span className="hint">— optional filters</span>
              </summary>
              <p className="hint">
                Only these explicit filters narrow the search. Leave them blank to keep the library
                open.
              </p>
              <div className="form-grid">
                {(
                  [
                    ['subject', 'Subject', 'subjects'],
                    ['form', 'Form or genre', 'forms'],
                    ['book', 'Book', 'books'],
                    ['author', 'Author or contributor', 'authors'],
                  ] as const
                ).map(([name, label, kind]) => (
                  <SuggestionInput
                    key={name}
                    id={`filter-${name}`}
                    name={name}
                    label={label}
                    kind={kind}
                    value={fields[name]}
                    onChange={(value) => update(name, value)}
                  />
                ))}
                <div>
                  <label htmlFor="text-type">Text type</label>
                  <select
                    id="text-type"
                    name="text_type"
                    value={fields.text_type}
                    onChange={(e) => update('text_type', e.target.value)}
                  >
                    <option value="">All text types</option>
                    {[
                      'scripture',
                      'commentary',
                      'poetry',
                      'quotation',
                      'caption',
                      'translation_note',
                      'editorial',
                      'index',
                      'reference',
                      'prose',
                      'mixed',
                      'unknown',
                    ].map((kind) => (
                      <option key={kind} value={kind}>
                        {humanize(kind)}
                      </option>
                    ))}
                  </select>
                  <p className="hint">
                    Classification is incomplete. Mixed passages can contain more than one type.
                  </p>
                </div>
              </div>
            </details>
          </form>
          <p className="search-feedback" role="status" aria-live="polite" aria-atomic="true">
            {message}
          </p>
          <ErrorMessage error={mutation.error} />
          {mutation.isPending && currentResult && (
            <p className="hint">Previous results are shown below while your new search runs.</p>
          )}
          {storageNotice && (
            <p className="notice">
              This browser could not retain this search. After returning or reloading, submit the
              search again explicitly.
            </p>
          )}
          <div id="search-content" aria-busy={mutation.isPending}>
            {currentResult ? (
              <SearchResults result={currentResult} query={currentSubmitted} />
            ) : (
              <section className="start-points">
                <h2>Three ways in</h2>
                <div className="three-columns">
                  <article>
                    <p className="eyebrow">01 / Look closely</p>
                    <h3>A particular passage</h3>
                    <p>Search an exact phrase, a chapter title, or the name of an artwork.</p>
                  </article>
                  <article>
                    <p className="eyebrow">02 / Follow an idea</p>
                    <h3>A question across books</h3>
                    <p>
                      Let science, poetry, history, and visual culture speak into the same question.
                    </p>
                  </article>
                  <article>
                    <p className="eyebrow">03 / Keep a place</p>
                    <h3>A recurring focus</h3>
                    <p>
                      <Link to="/focus">Create a research focus</Link> for the questions you return
                      to.
                    </p>
                  </article>
                </div>
              </section>
            )}
          </div>
        </>
      )}
    </PageState>
  );
}

function SearchResults({ result, query }: { result: JsonObject; query: string }) {
  const direct = records(result.direct),
    connections = records(result.connections);
  return (
    <>
      <div className="results-summary" id="search-results" tabIndex={-1}>
        <p>
          {direct.length} direct {direct.length === 1 ? 'match' : 'matches'}
          {connections.length > 0 &&
            ` and ${connections.length} wider ${connections.length === 1 ? 'connection' : 'connections'}`}{' '}
          for <strong>{query}</strong>.
        </p>
      </div>
      {strings(result.warnings).length > 0 && (
        <aside className="notice" aria-label="Search limitations">
          <h2>Before you read</h2>
          <ul>
            {strings(result.warnings).map((warning, i) => (
              <li key={i}>{warning}</li>
            ))}
          </ul>
        </aside>
      )}
      {result.holdings_gap && (
        <aside className="notice">
          <h2>A gap in the shelves</h2>
          <p>{text(result.holdings_gap)}</p>
          <p>
            A missing result is not evidence that a subject is absent from the book or from
            scholarship.
          </p>
        </aside>
      )}
      <div className="results-layout">
        {[
          { items: direct, connection: false, title: 'Direct matches', eyebrow: 'Close reading' },
          {
            items: connections,
            connection: true,
            title: 'Wider connections',
            eyebrow: 'Across the shelves',
          },
        ].map((group) => (
          <section
            key={group.title}
            className={group.connection ? 'connections-section' : undefined}
          >
            <div className="section-heading">
              <p className="eyebrow">{group.eyebrow}</p>
              <h2>{group.title}</h2>
            </div>
            {group.connection && (
              <p className="section-note">
                Related ideas can open another path. These connections are suggestions, not evidence
                that two sources agree.
              </p>
            )}
            {group.items.length ? (
              <ol className="result-list">
                {group.items.map((item, index) => {
                  const href = safeHref(
                    item.read_url ||
                      `/read/${encodeURIComponent(text(item.id))}${item.read_offset ? `?offset=${text(item.read_offset)}` : ''}`,
                  );
                  return (
                    <li className="result-item" key={text(item.id) + index}>
                      <article>
                        <p className="eyebrow">
                          {group.connection ? 'A wider connection' : 'From the library'}{' '}
                          <span aria-hidden="true">/</span> {String(index + 1).padStart(2, '0')}
                        </p>
                        <h3>
                          <Link to={href}>{text(item.title)}</Link>
                        </h3>
                        <p className="attribution">
                          {text(item.attribution, 'Attribution not yet recorded')}
                          {item.location && <span className="location">{text(item.location)}</span>}
                        </p>
                        {item.text_type && item.text_type !== 'unknown' && (
                          <p className="hint">
                            Text type: {humanize(text(item.text_type))}
                            {item.text_type_status !== 'confirmed' &&
                              ` (${text(item.text_type_status, 'unverified')})`}
                          </p>
                        )}
                        <p className="excerpt">{text(item.text)}</p>
                        {item.reason && (
                          <p className="match-reason">
                            <strong>
                              {group.connection ? 'Possible connection' : 'Why this appeared'}:
                            </strong>{' '}
                            {text(item.reason)}
                          </p>
                        )}
                        <Limitations items={item.limitations} />
                        <Link className="text-link" to={href}>
                          Read {text(item.title)} in context <span aria-hidden="true">→</span>
                        </Link>
                      </article>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className="empty-state">
                {group.connection
                  ? 'No wider connections surfaced in this search.'
                  : 'No direct matches surfaced. Try a shorter phrase, another spelling, or fewer filters.'}
              </p>
            )}
          </section>
        ))}
      </div>
      {result.coverage && (
        <details className="coverage">
          <summary>What this search covered</summary>
          <ObjectDetails value={result.coverage} />
        </details>
      )}
    </>
  );
}
