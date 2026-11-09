import {
  createElement,
  Fragment,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  apiAction,
  apiDownload,
  formFields,
  pageKey,
  usePage,
  type Fields,
  type UiPage,
} from '../api';
import {
  SourceBlocks,
  array,
  encode,
  humanize,
  number,
  record,
  sourceRanges,
  text,
  type DataRecord,
  type SourceRange,
} from '../components/SourceBlocks';
import { SuggestionInput } from '../components/SuggestionInput';

const labels = [
  ['full_note', 'Full footnote or endnote'],
  ['short_note', 'Shortened note'],
  ['bibliography', 'Bibliography entry'],
] as const;
const errorText = (error: unknown): string =>
  error instanceof Error
    ? error.message
    : 'The request could not finish. Your input is still here; please try again.';

function ErrorNotice({ error }: { error: unknown }) {
  return error ? (
    <p className="notice error" role="alert">
      {errorText(error)}
    </p>
  ) : null;
}

function Values({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === '') return <span>Not recorded</span>;
  if (Array.isArray(value))
    return (
      <ul>
        {value.map((item, i) => (
          <li key={i}>
            <Values value={item} />
          </li>
        ))}
      </ul>
    );
  if (typeof value === 'object')
    return (
      <dl className="details-list">
        {Object.entries(record(value)).map(([key, item]) => (
          <div key={key}>
            <dt>{humanize(key)}</dt>
            <dd>
              {key === 'issues' && Array.isArray(item) ? (
                <StructuralIssues items={item} />
              ) : (
                <Values value={item} />
              )}
            </dd>
          </div>
        ))}
      </dl>
    );
  return <>{typeof value === 'boolean' ? (value ? 'Yes' : 'No') : text(value)}</>;
}

export function StructuralIssues({ items }: { items: unknown[] }) {
  const grouped = new Map<
    string,
    { message: string; count: number; examples: string[]; more: boolean }
  >();
  for (const value of items) {
    const item = record(value);
    const message =
      text(item.message) || humanize(item.code) || text(value, 'Unresolved source structure');
    const key = text(item.code) + ':' + message;
    const group = grouped.get(key) ?? { message, count: 0, examples: [], more: false };
    group.count += 1;
    const label = text(item.label) || text(item.heading);
    if (label && !group.examples.includes(label)) {
      if (group.examples.length < 3) group.examples.push(label);
      else group.more = true;
    }
    grouped.set(key, group);
  }
  return (
    <ul className="structural-issues">
      {Array.from(grouped.entries()).map(([key, item]) => (
        <li key={key}>
          {item.message}
          {item.count > 1 && <span className="hint"> ({item.count} occurrences)</span>}
          {item.examples.length > 0 && (
            <p className="hint">
              Examples:{' '}
              {item.examples
                .map((label) => (label.length > 140 ? label.slice(0, 139) + '…' : label))
                .join('; ')}
              {item.more ? '; and others' : ''}.
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

function Limitations({ value }: { value: unknown }) {
  const items = array(value);
  return items.length ? (
    <aside className="notice" aria-label="Source limitations">
      <ul>
        {items.map((item, i) => (
          <li key={i}>
            <Values value={item} />
          </li>
        ))}
      </ul>
    </aside>
  ) : null;
}

function Resource({ children }: { children: (data: DataRecord) => ReactNode }) {
  const query = usePage();
  const location = useLocation();
  if (query.isPending) return <p role="status">Opening the source…</p>;
  if (query.error)
    return (
      <>
        <h1>We couldn’t open that.</h1>
        <ErrorNotice error={query.error} />
        <button type="button" onClick={() => void query.refetch()}>
          Try again
        </button>
      </>
    );
  return (
    <Fragment key={location.pathname + location.search}>
      {children(record(query.data.data))}
    </Fragment>
  );
}

function LocalForm({
  action,
  children,
  className,
  onSaved,
}: {
  action: string;
  children: ReactNode;
  className?: string;
  onSaved?: (page: UiPage) => void;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const client = useQueryClient();
  const pending = useRef(false);
  const mutation = useMutation({
    mutationFn: (fields: Fields) => apiAction(action, fields),
    retry: false,
    networkMode: 'always',
    onSettled: () => {
      pending.current = false;
    },
    onSuccess: async (result) => {
      await client.invalidateQueries({ queryKey: ['page'], refetchType: 'none' });
      if ('redirect' in result) {
        const target = new URL(result.redirect, window.location.origin);
        await navigate(target.pathname + target.search + target.hash);
        await client.invalidateQueries({ queryKey: pageKey(target.pathname + target.search) });
      } else {
        client.setQueryData(pageKey(location.pathname + location.search), result);
        onSaved?.(result);
      }
    },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
    mutation.mutate(formFields(event.currentTarget, (event.nativeEvent as SubmitEvent).submitter));
  }
  return (
    <form
      method="post"
      action={action}
      className={className}
      onSubmit={submit}
      aria-busy={mutation.isPending}
    >
      {children}
      <p role="status">{mutation.isPending ? 'Saving…' : ''}</p>
      <ErrorNotice error={mutation.error} />
    </form>
  );
}

function ResearchForm({
  scope,
  target,
}: {
  scope: 'passage' | 'unit' | 'selection';
  target: string;
}) {
  return (
    <section className="research-record" id="research-record" aria-labelledby="record-heading">
      <h2 id="record-heading">Keep a research note</h2>
      <p>
        This records use of{' '}
        {scope === 'selection'
          ? 'the exact selected text'
          : scope === 'unit'
            ? 'the whole reading unit'
            : 'this passage'}
        . Opening it does not add a research-use event.
      </p>
      <LocalForm action={scope === 'passage' ? '/usage' : '/usage/target'}>
        {scope === 'passage' ? (
          <input type="hidden" name="passage_id" value={target} />
        ) : (
          <>
            <input type="hidden" name="scope" value={scope} />
            <input type="hidden" name="target_id" value={target} />
          </>
        )}
        <div className="form-grid">
          <div>
            <label htmlFor="purpose">Purpose</label>
            <select id="purpose" name="purpose">
              <option value="research">General research</option>
              <option value="class-prep">Class preparation</option>
              <option value="substack">Substack</option>
              <option value="efm">EfM</option>
            </select>
          </div>
          <div>
            <SuggestionInput
              id="destination"
              name="destination"
              kind="destinations"
              label="Lesson, article, or project (optional)"
              maxLength={1000}
            />
          </div>
        </div>
        <label htmlFor="kind">How did you engage with this source?</label>
        <select id="kind" name="kind">
          <option value="inspected">Inspected — read or considered it</option>
          <option value="offered">Offered — included among possible sources</option>
          <option value="recommended">Recommended — suggested using it</option>
          <option value="selected">Selected — chose it for a project</option>
          <option value="used">Used — incorporated it into the work</option>
        </select>
        <label htmlFor="notes">
          Your note <span className="optional">(optional)</span>
        </label>
        <textarea id="notes" name="notes" rows={4} maxLength={4000} />
        <button type="submit">Save research note</button>
      </LocalForm>
    </section>
  );
}

function restoreObject(key: string): DataRecord {
  try {
    return record(JSON.parse(sessionStorage.getItem(key) || '{}'));
  } catch {
    return {};
  }
}

function saveObject(key: string, value: DataRecord) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* Reading works without optional browser storage. */
  }
}

function Outline({ outline, work }: { outline: DataRecord; work: DataRecord }) {
  const location = useLocation();
  const key = `reading-room:outline:${text(work.id)}:${number(outline.offset)}`;
  const root = useRef<HTMLDivElement>(null);
  const [opened, setOpened] = useState<Record<string, boolean>>(() => {
    const stored = record(restoreObject(key).open);
    return Object.fromEntries(
      Object.entries(stored).filter(
        (entry): entry is [string, boolean] => typeof entry[1] === 'boolean',
      ),
    );
  });
  function persist(next: Record<string, boolean>) {
    setOpened(next);
    saveObject(key, { ...restoreObject(key), open: next });
  }
  function toggle(id: string, value: boolean) {
    if (!value && document.getElementById(`${id}-children`)?.contains(document.activeElement))
      root.current
        ?.querySelector<HTMLButtonElement>(`[aria-controls="${CSS.escape(id)}-children"]`)
        ?.focus();
    persist({ ...opened, [id]: value });
  }
  function all(expanded: boolean) {
    const result: Record<string, boolean> = {};
    const visit = (nodes: unknown) =>
      array(nodes).forEach((value) => {
        const node = record(value);
        if (array(node.children).length) {
          result[`outline-${text(node.id)}`] = expanded;
          visit(node.children);
        }
      });
    visit(outline.nodes);
    persist(result);
  }
  function remember(node: DataRecord) {
    saveObject(key, { ...restoreObject(key), open: opened, focus: text(node.id), returning: true });
    try {
      sessionStorage.setItem(
        `reading-room:return:${text(node.unit_id)}`,
        `${location.pathname}?outline_offset=${number(outline.offset)}#outline-${text(node.id)}`,
      );
    } catch {
      /* Optional browser history. */
    }
  }
  useEffect(() => {
    const saved = restoreObject(key);
    if (saved.returning && saved.focus) {
      const node = root.current?.querySelector<HTMLElement>(
        `[data-outline-link="${CSS.escape(text(saved.focus))}"]`,
      );
      if (node) {
        node.focus({ preventScroll: true });
        node.scrollIntoView({ block: 'center' });
      }
      saveObject(key, { ...saved, returning: false });
    }
  }, [key]);
  function branch(nodes: unknown, level = 3): ReactNode {
    return (
      <ol className="outline-list">
        {array(nodes).map((value, i) => {
          const node = record(value);
          const id = `outline-${text(node.id, String(i))}`;
          const children = array(node.children);
          const expanded = opened[id] ?? level === 3;
          const href = node.unit_id
            ? `/units/${encode(node.unit_id)}${node.anchor_block_id ? `?anchor=${encode(node.anchor_block_id)}#${encode(node.anchor_block_id)}` : ''}`
            : node.passage_id
              ? `/read/${encode(node.passage_id)}`
              : '';
          const title = text(node.title, 'Untitled section');
          const link = (
            <Link to={href} data-outline-link={text(node.id)} onClick={() => remember(node)}>
              {title}
            </Link>
          );
          const heading = children.length ? (
            <button
              type="button"
              className="outline-toggle"
              aria-expanded={expanded}
              aria-controls={`${id}-children`}
              onClick={() => toggle(id, !expanded)}
            >
              <span aria-hidden="true" className="outline-indicator">
                {expanded ? '−' : '+'}
              </span>{' '}
              {title}
            </button>
          ) : href ? (
            link
          ) : (
            title
          );
          return (
            <li id={id} key={id} className="outline-node">
              <div
                role="heading"
                aria-level={Math.max(3, number(node.depth, level - 2) + 2)}
                className="outline-heading"
              >
                {heading}
              </div>
              {Boolean(
                node.attribution &&
                (node.attribution_verified || node.attribution_status === 'confirmed'),
              ) && <p className="outline-credit">{text(node.attribution)}</p>}
              {node.continued === true && (
                <p className="outline-continuation">Continued from the previous contents page</p>
              )}
              {children.length > 0 && Boolean(node.unit_id) && (
                <p className="outline-read">
                  <Link to={href} data-outline-link={text(node.id)} onClick={() => remember(node)}>
                    Read {title}
                  </Link>
                </p>
              )}
              {Boolean(node.section_id) && (
                <p className="outline-edit">
                  <Link to={`/review/${encode(node.section_id)}?work=${encode(work.id)}`}>
                    Review and edit information for {title}
                  </Link>
                </p>
              )}
              {children.length > 0 && (
                <div id={`${id}-children`} hidden={!expanded}>
                  {branch(children, level + 1)}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    );
  }
  const report = record(outline.report);
  return (
    <>
      {(report.status === 'needs_review' || report.state === 'needs_review') && (
        <div className="notice">
          <p>
            <strong>Some book structure needs review.</strong> The outline shows supported
            relationships; unresolved text remains readable.
          </p>
          {array(report.issues).length > 0 && (
            <details>
              <summary>Structural review notes</summary>
              <StructuralIssues items={array(report.issues)} />
              <p>
                <a href={`/api/contents/${encode(work.id)}`}>Detailed structure report (JSON)</a>
              </p>
            </details>
          )}
        </div>
      )}
      {array(outline.ancestors).length > 0 && (
        <p className="breadcrumb">
          Continued within{' '}
          {array(outline.ancestors)
            .map((a) => text(record(a).title))
            .join(' / ')}
        </p>
      )}
      <div ref={root} className="book-outline">
        <div className="outline-actions">
          <button type="button" className="secondary" onClick={() => all(true)}>
            Expand all on this page
          </button>
          <button type="button" className="secondary" onClick={() => all(false)}>
            Collapse all on this page
          </button>
        </div>
        {array(outline.nodes).length ? (
          branch(outline.nodes)
        ) : (
          <p className="empty-state">No outline entries are available on this page.</p>
        )}
      </div>
      <nav className="page-nav" aria-label="Book contents pages">
        {outline.previous_offset != null && (
          <Link
            to={`/books/${encode(work.id)}?outline_offset=${number(outline.previous_offset)}#contents-heading`}
          >
            ← Previous contents
          </Link>
        )}
        {outline.next_offset != null && (
          <Link
            to={`/books/${encode(work.id)}?outline_offset=${number(outline.next_offset)}#contents-heading`}
          >
            Continue contents →
          </Link>
        )}
      </nav>
    </>
  );
}

function BookContent({ data }: { data: DataRecord }) {
  const work = record(data.work);
  const profile = record(work.profile);
  const metadata = record(work.metadata);
  const edition = text(work.edition) || text(metadata.edition);
  const year = text(work.year) || text(metadata.publication_year);
  const offset = number(data.section_offset);
  return (
    <>
      <p className="breadcrumb">
        <Link to="/books">The shelves</Link> / Book
      </p>
      <section className="page-intro book-intro">
        <p className="eyebrow">On the shelf</p>
        <h1>{text(work.title)}</h1>
        <p className="lede">
          {array(work.contributors).some((v) => record(v).role === 'editor') && 'Edited by '}
          {text(work.author) || text(work.attribution) || 'Author not yet recorded'}
        </p>
        {(edition || year) && <p>{[edition, year].filter(Boolean).join(' · ')}</p>}
      </section>
      <Limitations value={work.limitations} />
      {['source_quality_note', 'source_scope_note', 'catalog_discrepancy']
        .filter((key) => metadata[key])
        .map((key) => (
          <p key={key} className="notice">
            {text(metadata[key])}
          </p>
        ))}
      <div className="reading-layout">
        <section aria-labelledby="contents-heading">
          <h2 id="contents-heading">Contents</h2>
          {data.outline != null ? (
            <Outline outline={record(data.outline)} work={work} />
          ) : array(work.sections).length ? (
            <>
              <p className="hint">
                Sections {offset + 1}–{offset + array(work.sections).length}
                {work.sections_total != null && ` of ${text(work.sections_total)}`}
              </p>
              <ol className="contents-list" start={offset + 1}>
                {array(work.sections).map((value, i) => {
                  const section = record(value);
                  return (
                    <li key={text(section.id, String(i))}>
                      <div>
                        {section.passage_id ? (
                          <Link to={`/read/${encode(section.passage_id)}`}>
                            {text(section.title, 'Untitled section')}
                          </Link>
                        ) : (
                          text(section.title, 'Untitled section')
                        )}
                        {section.count != null && (
                          <span className="hint">{text(section.count)} indexed passages</span>
                        )}
                      </div>
                      <Link
                        className="small-link"
                        to={`/review/${encode(section.id)}?work=${encode(work.id)}&section_offset=${offset}`}
                      >
                        Review and edit information for {text(section.title, 'this section')}
                      </Link>
                    </li>
                  );
                })}
              </ol>
              <nav className="page-nav" aria-label="Book contents pages">
                {work.previous_section_offset != null && (
                  <Link
                    to={`/books/${encode(work.id)}?section_offset=${number(work.previous_section_offset)}#contents-heading`}
                  >
                    ← Previous sections
                  </Link>
                )}
                {work.next_section_offset != null && (
                  <Link
                    to={`/books/${encode(work.id)}?section_offset=${number(work.next_section_offset)}#contents-heading`}
                  >
                    Next sections →
                  </Link>
                )}
              </nav>
            </>
          ) : (
            <p className="empty-state">
              No readable sections are indexed on this page.{' '}
              <Link to="/status">Check library status</Link> for extraction limitations.
            </p>
          )}
        </section>
        <aside className="book-aside" aria-labelledby="book-info-heading">
          <h2 id="book-info-heading">About this copy</h2>
          {Object.keys(profile).length ? (
            <>
              {Boolean(profile.description) && <p>{text(profile.description)}</p>}
              {['subjects', 'forms'].map((key) =>
                profile[key] ? (
                  <p key={key}>
                    <strong>{key === 'subjects' ? 'Subjects' : 'Form or genre'}</strong>
                    <br />
                    {Array.isArray(profile[key])
                      ? array(profile[key])
                          .map((v) => text(v))
                          .join(', ')
                      : text(profile[key])}
                  </p>
                ) : null,
              )}
              <details>
                <summary>Full book profile</summary>
                <Values value={profile} />
              </details>
            </>
          ) : (
            <p>No subject profile has been recorded yet.</p>
          )}
          <p>
            <Link to={`/review/${encode(work.id)}?work=${encode(work.id)}`}>
              Review book details
            </Link>
          </p>
          <p>
            <Link to={`/review/${encode(work.id)}`}>Review book citation details</Link>
          </p>
          {array(work.files).length > 0 && (
            <details>
              <summary>Local source files</summary>
              <Values value={work.files} />
            </details>
          )}
        </aside>
      </div>
    </>
  );
}

export function BookPage() {
  return <Resource>{(data) => <BookContent data={data} />}</Resource>;
}
export function ContentsPage() {
  return (
    <Resource>
      {(data) => (
        <>
          <h1>Book contents</h1>
          <Outline work={record(data.work)} outline={record(data.outline)} />
        </>
      )}
    </Resource>
  );
}

function PassageContent({ data }: { data: DataRecord }) {
  const navigate = useNavigate();
  const reading = record(data.reading);
  const passage = record(reading.passage);
  const context = number(data.context, 3);
  const id = encode(passage.id);
  function updateContext(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new URLSearchParams();
    for (const [key, value] of new FormData(event.currentTarget))
      if (typeof value === 'string') values.set(key, value);
    void navigate(`/read/${id}?${values}`);
  }
  return (
    <>
      <p className="breadcrumb">
        <Link to="/books">The shelves</Link> /{' '}
        <Link to={`/books/${encode(passage.work_id)}`}>{text(passage.title)}</Link>
      </p>
      <section className="page-intro reading-intro">
        <p className="eyebrow">Read in context</p>
        <h1>{text(passage.title)}</h1>
        <p className="lede">{text(passage.attribution, 'Attribution not yet recorded')}</p>
        <p className="source-location">{text(passage.location)}</p>
      </section>
      {Boolean(passage.text_type && passage.text_type !== 'unknown') && (
        <p>Text type: {humanize(passage.text_type)}</p>
      )}
      <Limitations value={passage.limitations} />
      {reading.truncated === true && (
        <p className="notice">
          This context view reached its length limit. Continue the matched passage below, or follow
          an adjacent passage for more context.
        </p>
      )}
      {array(passage.source_paths).length > 0 && (
        <details className="source-copy">
          <summary>Source copy and citation details</summary>
          <p>
            {text(passage.attribution)}. <cite>{text(passage.title)}</cite>
            {passage.edition ? `, ${text(passage.edition)}` : ''}. {text(passage.location)}.
          </p>
          <p className="hint">Local source files:</p>
          <ul>
            {array(passage.source_paths).map((path, i) => (
              <li key={i} className="source-path">
                {text(path)}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p>
        <Link className="button" to={`/cite/${id}`}>
          Cite this passage
        </Link>
      </p>
      <div className="reading-toolbar">
        <a href="#selected-passage">Jump to the matched passage</a>
        <form method="get" onSubmit={updateContext}>
          {number(reading.offset) > 0 && (
            <input type="hidden" name="offset" value={number(reading.offset)} />
          )}
          <label htmlFor="context">Surrounding passages</label>
          <select id="context" name="context" defaultValue={context}>
            {[0, 1, 3, 5, 8].map((count) => (
              <option key={count} value={count}>
                {count} on each side
              </option>
            ))}
          </select>
          <button type="submit" className="secondary">
            Update context
          </button>
        </form>
      </div>
      <section className="reading-text" aria-label="Source passages">
        <SourceBlocks blocks={reading.blocks} attribution={text(passage.attribution)} />
      </section>
      <nav className="page-nav" aria-label="Continue this long passage">
        {reading.previous_offset != null && (
          <Link to={`/read/${id}?context=${context}&offset=${number(reading.previous_offset)}`}>
            ← Earlier in this passage
          </Link>
        )}
        {reading.next_offset != null && (
          <Link to={`/read/${id}?context=${context}&offset=${number(reading.next_offset)}`}>
            Continue this passage →
          </Link>
        )}
      </nav>
      <nav className="page-nav reading-nav" aria-label="Adjacent passages">
        {Boolean(reading.previous) && (
          <Link to={`/read/${encode(reading.previous)}?context=${context}`}>
            ← Previous passage
          </Link>
        )}
        {Boolean(reading.next) && (
          <Link to={`/read/${encode(reading.next)}?context=${context}`}>Next passage →</Link>
        )}
      </nav>
      {data.saved === true && (
        <p className="notice" role="status">
          Your research note was saved.
        </p>
      )}
      <ResearchForm scope="passage" target={text(passage.id)} />
    </>
  );
}

export function PassagePage() {
  return <Resource>{(data) => <PassageContent data={data} />}</Resource>;
}

function UnitContent({ data }: { data: DataRecord }) {
  const reading = record(data.reading);
  const unit = record(reading.unit);
  const work = record(reading.work);
  const selection = record(reading.selection);
  const root = useRef<HTMLElement>(null);
  const [ranges, setRanges] = useState<SourceRange[]>([]);
  const [message, setMessage] = useState('');
  const matchRanges = array(selection.source_ranges ?? reading.source_ranges).map((value) => {
    const r = record(value);
    return { block_id: text(r.block_id), start: number(r.start), end: number(r.end) };
  });
  const baseReturn = `/books/${encode(work.id)}`;
  let returnUrl = baseReturn;
  try {
    const saved = sessionStorage.getItem(`reading-room:return:${text(unit.id)}`);
    if (saved?.startsWith(baseReturn + '?')) returnUrl = saved;
  } catch {
    /* Optional storage. */
  }
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    function changed() {
      const selected = window.getSelection();
      if (!root.current || !selected || selected.isCollapsed || !selected.rangeCount) return;
      clearTimeout(timer);
      try {
        if (selected.rangeCount !== 1) throw new Error('Choose one continuous source selection.');
        const next = sourceRanges(selected.getRangeAt(0), root.current);
        if (!next.length) throw new Error('Highlight source text before choosing an action.');
        setRanges(next);
        timer = setTimeout(
          () =>
            setMessage(
              `${next.reduce((sum, item) => sum + item.end - item.start, 0)} source characters selected. Choose a citation or research-use action to review the words.`,
            ),
          250,
        );
      } catch (error) {
        setRanges([]);
        timer = setTimeout(() => setMessage(errorText(error)), 250);
      }
    }
    document.addEventListener('selectionchange', changed);
    const anchor = text(reading.anchor);
    const target = anchor ? document.getElementById(anchor) : null;
    if (target && root.current?.contains(target)) {
      target.focus({ preventScroll: true });
      target.scrollIntoView({ block: 'start' });
    }
    return () => {
      clearTimeout(timer);
      document.removeEventListener('selectionchange', changed);
    };
  }, [reading.anchor, unit.id]);
  const blocks = array(reading.blocks);
  const notes = blocks.filter((v) => record(v).role === 'note');
  return (
    <>
      <nav className="breadcrumb" aria-label="Location in the book">
        <Link to="/books">The shelves</Link> / <Link to={returnUrl}>{text(work.title)}</Link>
        {array(reading.ancestors).map((value, i) => {
          const ancestor = record(value);
          return (
            <Fragment key={i}>
              {' '}
              /{' '}
              {ancestor.unit_id ? (
                <Link to={`/units/${encode(ancestor.unit_id)}`}>{text(ancestor.title)}</Link>
              ) : (
                <span>{text(ancestor.title)}</span>
              )}
            </Fragment>
          );
        })}
      </nav>
      <section className="page-intro reading-intro">
        <p className="eyebrow">
          {unit.structure_status === 'needs_review'
            ? 'Source excerpt — boundaries need review'
            : unit.kind === 'contribution'
              ? 'Contribution'
              : 'Read the complete section'}
        </p>
        <h1>{text(unit.contextual_title) || text(unit.title)}</h1>
        <p className="lede">{text(unit.attribution) || 'Contributor not yet verified'}</p>
      </section>
      <Limitations value={reading.limitations} />
      {unit.structure_status === 'needs_review' && (
        <p className="notice">
          Some surrounding structure remains unresolved. This view follows the supported boundaries
          recorded for this section.
        </p>
      )}
      {data.saved === true && (
        <p className="notice" role="status">
          Your research note was saved.
        </p>
      )}
      {(reading.next_cursor != null || reading.previous_cursor != null) && (
        <p className="notice">
          This long reading unit continues across pages. The controls below stay within the same
          unit.
        </p>
      )}
      {Boolean(selection.id) && (
        <aside className="notice">
          <p>This reading contains your saved exact selection.</p>
          <blockquote className="selection-quotation">
            {text(selection.quotation) || text(selection.text)}
          </blockquote>
          <Link to={`/cite/selection/${encode(selection.id)}`}>Cite this selection</Link>
        </aside>
      )}
      <div className="reading-toolbar unit-actions">
        <Link className="button" to={`/cite/unit/${encode(unit.id)}`}>
          Cite this whole reading unit
        </Link>
        <a href="#research-record">Record use of the whole unit</a>
        {Boolean(reading.anchor) && (
          <a href={`#${encode(reading.anchor)}`}>Jump to the matched text</a>
        )}
      </div>
      <LocalForm className="selection-toolbar" action="/selections">
        <input type="hidden" name="unit_id" value={text(unit.id)} />
        <input type="hidden" name="source_ranges" value={JSON.stringify(ranges)} />
        <p>
          Highlight source text, then choose an action. You’ll review the exact words before citing
          or recording use.
        </p>
        <div className="selection-actions">
          <button type="submit" name="action" value="cite" disabled={!ranges.length}>
            Cite selected text
          </button>
          <button
            type="submit"
            name="action"
            value="record"
            className="secondary"
            disabled={!ranges.length}
          >
            Record use of selection
          </button>
        </div>
        <p role="status" aria-live="polite">
          {message}
        </p>
      </LocalForm>
      <article
        ref={root}
        className="reading-text unit-source"
        aria-label="Source text"
        data-unit-id={text(unit.id)}
      >
        <SourceBlocks
          blocks={blocks.filter((v) => record(v).role !== 'note')}
          unit={unit}
          ranges={matchRanges}
        />
        {notes.length > 0 && (
          <section className="unit-source-notes" aria-labelledby="source-notes-heading">
            <h2 id="source-notes-heading">Source notes</h2>
            <SourceBlocks blocks={notes} unit={unit} ranges={matchRanges} />
          </section>
        )}
      </article>
      <nav className="page-nav" aria-label="Continue this reading unit">
        {reading.previous_cursor != null && (
          <Link to={`/units/${encode(unit.id)}?cursor=${number(reading.previous_cursor)}`}>
            ← Earlier in this unit
          </Link>
        )}
        {reading.next_cursor != null && (
          <Link to={`/units/${encode(unit.id)}?cursor=${number(reading.next_cursor)}`}>
            Continue this unit →
          </Link>
        )}
      </nav>
      <nav className="page-nav" aria-label="Adjacent reading units">
        {Boolean(reading.previous) && (
          <Link to={`/units/${encode(record(reading.previous).id)}`}>
            ←{' '}
            {text(record(reading.previous).contextual_title) ||
              text(record(reading.previous).title)}
          </Link>
        )}
        {Boolean(reading.next) && (
          <Link to={`/units/${encode(record(reading.next).id)}`}>
            {text(record(reading.next).contextual_title) || text(record(reading.next).title)} →
          </Link>
        )}
      </nav>
      <ResearchForm scope="unit" target={text(unit.id)} />
    </>
  );
}

export function UnitPage() {
  return <Resource>{(data) => <UnitContent data={data} />}</Resource>;
}

export function SelectionPage() {
  return (
    <Resource>
      {(data) => {
        const selection = record(data.selection);
        const available = selection.available !== false;
        return (
          <>
            <p className="breadcrumb">
              {available ? (
                <Link to={`/units/${encode(selection.unit_id)}?selection=${encode(selection.id)}`}>
                  Back to the selected text in context
                </Link>
              ) : selection.work_id ? (
                <Link to={`/books/${encode(selection.work_id)}`}>View current book contents</Link>
              ) : null}
            </p>
            <section className="page-intro">
              <p className="eyebrow">Exact source selection</p>
              <h1>Review selected text.</h1>
              <p className="lede">{text(selection.title) || 'Source quotation'}</p>
            </section>
            {data.saved === true && (
              <p className="notice" role="status">
                Your research note was saved.
              </p>
            )}
            <p>
              Check the words and boundaries below. This selection retains its original source
              location; it does not create or verify printed page numbers.
            </p>
            <blockquote className="selection-quotation">
              {text(selection.quotation) || text(selection.text)}
            </blockquote>
            {Boolean(selection.location) && <p>{text(selection.location)}</p>}
            <Limitations value={selection.warnings} />
            {!available ? (
              <p className="notice">
                <strong>This saved selection needs source review.</strong> {text(selection.error)}{' '}
                Its saved quotation remains here; it has not been transferred to different text.
              </p>
            ) : data.action === 'record' ? (
              <ResearchForm scope="selection" target={text(selection.id)} />
            ) : (
              <>
                <p>
                  <Link className="button" to={`/cite/selection/${encode(selection.id)}`}>
                    Confirm selection and show citation
                  </Link>
                </p>
                <p>
                  <Link to={`/selections/${encode(selection.id)}?action=record`}>
                    Record use of this selection
                  </Link>
                </p>
              </>
            )}
          </>
        );
      }}
    </Resource>
  );
}

function decodeCitationText(value: string): string {
  const entities: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
  return value.replace(
    /&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi,
    (whole: string, name: string) => {
      if (name.startsWith('#')) {
        const code =
          name[1]?.toLowerCase() === 'x'
            ? Number.parseInt(name.slice(2), 16)
            : Number.parseInt(name.slice(1), 10);
        return code >= 0 && code <= 0x10ffff ? String.fromCodePoint(code) : whole;
      }
      return entities[name.toLowerCase()] ?? whole;
    },
  );
}

/** Citation formatting accepts emphasis only. No HTML parser, attributes, or resource loading. */
export function citationMarkup(value: string): ReactNode {
  const cleaned = value.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '');
  const root: { tag: string; children: ReactNode[] } = { tag: '', children: [] };
  const stack = [root];
  let serial = 0;
  for (const token of cleaned.split(/(<\/?(?:em|i|strong|b|cite|sup|sub)>|<br\s*\/?>)/gi)) {
    const match = /^<(\/?)(em|i|strong|b|cite|sup|sub)>$/i.exec(token);
    const current = stack.at(-1)!;
    if (match) {
      const tag = match[2].toLowerCase();
      if (!match[1]) stack.push({ tag, children: [] });
      else if (stack.length > 1 && current.tag === tag) {
        stack.pop();
        stack.at(-1)!.children.push(createElement(tag, { key: serial++ }, ...current.children));
      }
    } else if (/^<br\s*\/?>$/i.test(token)) current.children.push(<br key={serial++} />);
    else current.children.push(decodeCitationText(token.replace(/<[^>]*>/g, '')));
  }
  while (stack.length > 1) {
    const current = stack.pop()!;
    stack.at(-1)!.children.push(createElement(current.tag, { key: serial++ }, ...current.children));
  }
  return root.children;
}

function CitationFormat({
  value,
  field,
  label,
  prefix,
  onMessage,
}: {
  value: DataRecord;
  field: string;
  label: string;
  prefix: string;
  onMessage: (value: string) => void;
}) {
  const formatted = useRef<HTMLDivElement>(null);
  const selectable = useRef<HTMLTextAreaElement>(null);
  const [copying, setCopying] = useState(false);
  const plain = text(value[field]);
  const html = text(record(value.html)[field]);
  async function copy() {
    if (copying) return;
    setCopying(true);
    onMessage('Copying citation…');
    try {
      if (typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write) {
        await navigator.clipboard.write([
          new ClipboardItem({
            'text/plain': new Blob([plain], { type: 'text/plain' }),
            'text/html': new Blob([formatted.current?.innerHTML ?? ''], { type: 'text/html' }),
          }),
        ]);
      } else await navigator.clipboard.writeText(plain);
      onMessage(`${label} copied.`);
    } catch {
      selectable.current?.focus();
      selectable.current?.select();
      onMessage('The citation is selected. Press Command+C or Control+C to copy it.');
    } finally {
      setCopying(false);
    }
  }
  return (
    <section className="citation-format" aria-labelledby={`label-${prefix}-${field}`}>
      <h3 id={`label-${prefix}-${field}`}>{label}</h3>
      <div ref={formatted} className="citation-preview">
        {html ? citationMarkup(html) : plain}
      </div>
      <label htmlFor={`copy-${prefix}-${field}`} className="hint">
        {label} — selectable text
      </label>
      <textarea ref={selectable} readOnly id={`copy-${prefix}-${field}`} rows={4} value={plain} />
      <button
        className="secondary citation-copy"
        type="button"
        aria-disabled={copying}
        onClick={() => void copy()}
      >
        Copy {label.toLowerCase()}
      </button>
    </section>
  );
}

function CitationFormats({
  citation,
  prefix = 'target',
  onMessage,
}: {
  citation: DataRecord;
  prefix?: string;
  onMessage: (message: string) => void;
}) {
  const components = array(citation.component_citations);
  return (
    <>
      {components.length ? (
        <>
          <p className="notice">
            The selected source contains separately credited portions. Keep their citations
            separate.
          </p>
          {components.map((value, i) => {
            const component = record(value);
            return (
              <section key={i}>
                <h3>
                  {text(component.attribution) || text(component.title) || 'Source component'}
                </h3>
                {Boolean(component.quotation || component.excerpt) && (
                  <blockquote className="selection-quotation">
                    {text(component.quotation) || text(component.excerpt)}
                  </blockquote>
                )}
                <CitationFormats
                  citation={component.citation ? record(component.citation) : component}
                  prefix={`${prefix}-${i}`}
                  onMessage={onMessage}
                />
              </section>
            );
          })}
        </>
      ) : (
        labels
          .filter(
            ([key]) =>
              Boolean(citation[key]) &&
              (key !== 'bibliography' || citation.bibliography_required !== false),
          )
          .map(([key, label]) => (
            <CitationFormat
              key={key}
              value={citation}
              field={key}
              label={label}
              prefix={prefix}
              onMessage={onMessage}
            />
          ))
      )}
      <Limitations value={citation.warnings} />
    </>
  );
}

function CitationContent({ data }: { data: DataRecord }) {
  const citation = record(data.citation);
  const passage = record(data.passage);
  const section = record(data.section);
  const locator = record(data.locator);
  const passageScope = Boolean(passage.id);
  const scope = passageScope ? 'passage' : text(data.scope);
  const target = passageScope ? text(passage.id) : text(data.target_id);
  const base = passageScope
    ? `/cite/${encode(target)}`
    : `/cite/${encode(scope)}/${encode(target)}`;
  const components = array(citation.component_citations);
  const [message, setMessage] = useState('');
  const download = useMutation({
    mutationFn: (fields: Fields) => apiDownload(`${base}/export`, fields),
    onSuccess: () => setMessage('Citation download is ready.'),
  });
  function exportCitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!download.isPending) download.mutate(formFields(event.currentTarget));
  }
  const back = passageScope ? `/read/${encode(target)}` : text(data.back_url, '/books');
  return (
    <>
      <p className="breadcrumb">
        <Link to={back}>Back to {passageScope ? 'the passage' : 'the source in context'}</Link>
      </p>
      <section className="page-intro">
        <p className="eyebrow">Keep the source in view</p>
        <h1>
          {passageScope
            ? 'Cite this passage.'
            : scope === 'selection'
              ? 'Cite selected text.'
              : 'Cite this reading unit.'}
        </h1>
        <p className="lede">{passageScope ? text(passage.title) : text(data.target_title)}</p>
        <p>
          Chicago notes and bibliography.{' '}
          {passageScope
            ? 'Check your instructor’s requirements before submitting academic work.'
            : `This citation targets ${scope === 'selection' ? 'only your confirmed selection' : 'the whole reading unit'}.`}
        </p>
      </section>
      {data.saved === true && (
        <p role="status" className="notice">
          Citation details saved. The formats below use your correction.
        </p>
      )}
      {Boolean(citation.quotation) && (
        <blockquote className="selection-quotation">{text(citation.quotation)}</blockquote>
      )}
      {Boolean(citation.needs_review) && (!passageScope || !components.length) && (
        <aside className="notice" aria-labelledby="citation-review">
          <h2 id="citation-review">Review needed</h2>
          <p>
            This citation is a draft. Resolve missing or uncertain information before using it in a
            paper.
          </p>
          {array(citation.missing_fields).length > 0 && (
            <p>
              Missing:{' '}
              {array(citation.missing_fields)
                .map((v) => text(v))
                .join(', ')}
              .
            </p>
          )}
          {array(citation.review_fields).length > 0 && (
            <p>
              Needs verification:{' '}
              {array(citation.review_fields)
                .map((v) => text(v))
                .join(', ')}
              .
            </p>
          )}
        </aside>
      )}
      {!citation.needs_review && !components.length && (
        <p className="notice">
          The required details have recorded verification. Check that the locator identifies the
          exact words you are citing.
        </p>
      )}
      {passageScope && components.length ? (
        <>
          <p className="notice">
            This passage contains separately credited portions. Choose the text you used below to
            get its citation.
          </p>
          <section aria-labelledby="source-components">
            <h2 id="source-components">Choose the source text you used</h2>
            <ol>
              {components.map((value, i) => {
                const component = record(value);
                const href = text(record(component.links).local_citation);
                const safe =
                  (href.startsWith('/') && !href.startsWith('//')) ||
                  href.startsWith('http://127.0.0.1:') ||
                  href.startsWith('http://localhost:');
                const path = safe
                  ? new URL(href, window.location.origin).pathname +
                    new URL(href, window.location.origin).search
                  : '';
                return (
                  <li key={i}>
                    <h3>{humanize(component.text_type)}</h3>
                    <p>{text(component.attribution)}</p>
                    <p>{text(record(component.locator).display)}</p>
                    <blockquote>{text(component.excerpt)}</blockquote>
                    <p>
                      {component.ready
                        ? 'Required citation details verified.'
                        : `Citation needs review: ${[...array(component.missing_fields), ...array(component.review_fields)].map((v) => text(v)).join(', ')}.`}
                    </p>
                    {path && (
                      <Link to={path}>
                        Cite this {humanize(component.text_type).toLowerCase()} component
                      </Link>
                    )}
                  </li>
                );
              })}
            </ol>
          </section>
        </>
      ) : (
        <>
          {citation.bibliography_required === false && (
            <p className="notice">
              Scripture normally needs no separate bibliography entry. Use the biblical reference
              and translation below; cite study notes or commentary separately.
            </p>
          )}
          <section aria-labelledby="citation-formats-heading">
            <h2 id="citation-formats-heading">Citation formats</h2>
            <CitationFormats citation={citation} onMessage={setMessage} />
          </section>
          <p role="status" aria-live="polite">
            {message}
          </p>
          <p className="hint">
            Copy buttons preserve italics where the destination supports formatted text. You can
            also select the text above and copy it with your keyboard.
          </p>
          <section aria-labelledby="citation-location">
            <h2 id="citation-location">Exact location</h2>
            {passageScope && <p>{text(passage.location)}</p>}
            <p>
              {passageScope
                ? 'Source page markers can support page citations. Word layout pages and extraction block numbers are navigation aids, not printed pages.'
                : 'Text selection preserves the exact words. Printed pages and other bibliographic locators still require source evidence.'}
            </p>
            <LocalForm action={`${base}/preview`}>
              {passageScope && <input type="hidden" name="segment" value={text(data.segment_id)} />}
              <label htmlFor="locator-type">Locator type</label>
              <select
                id="locator-type"
                name="locator_type"
                defaultValue={text(locator.type) || text(data.locator_type) || 'page'}
              >
                {['page', 'chapter', 'section', 'paragraph', 'verse'].map((kind) => (
                  <option key={kind} value={kind}>
                    {humanize(kind)}
                  </option>
                ))}
              </select>
              <label htmlFor="locator-value">Citation location (optional)</label>
              <input
                id="locator-value"
                name="locator_value"
                defaultValue={text(locator.value) || text(data.locator_value)}
                maxLength={300}
              />
              <label className="checkbox-label" htmlFor="locator-verified">
                <input
                  type="checkbox"
                  id="locator-verified"
                  name="locator_verified"
                  value="yes"
                  defaultChecked={Boolean(locator.verified)}
                />{' '}
                I checked this locator against the source.
              </label>
              <label htmlFor="locator-evidence">Locator evidence (required if checked)</label>
              <textarea
                id="locator-evidence"
                name="locator_evidence"
                rows={2}
                maxLength={4000}
                defaultValue={text(locator.evidence)}
              />
              <p className="hint">
                This location applies to this citation only. Leave it blank to use the source
                markers. It does not change the entire section’s location.
              </p>
              <button className="secondary" type="submit">
                Preview this location
              </button>
            </LocalForm>
          </section>
          {passageScope ? (
            <>
              {citation.metadata_scope !== 'segment' ? (
                <section aria-labelledby="citation-correct">
                  <h2 id="citation-correct">Review and edit citation details</h2>
                  <p>
                    <Link to={`/review/${encode(passage.work_id)}?passage=${encode(target)}`}>
                      Review and edit book publication details
                    </Link>
                    {Boolean(citation.contribution_target_id) && (
                      <>
                        {' '}
                        ·{' '}
                        <Link
                          to={`/review/${encode(citation.contribution_target_id)}?passage=${encode(target)}`}
                        >
                          Review and edit this contribution’s author and title
                        </Link>
                      </>
                    )}
                  </p>
                  <p>
                    <Link to={`/review/${encode(target)}?passage=${encode(target)}`}>
                      Review and edit attribution for this passage only
                    </Link>
                    {citation.metadata_scope === 'passage' && Boolean(section.id) && (
                      <>
                        {' '}
                        ·{' '}
                        <Link to={`/review/${encode(section.id)}?passage=${encode(target)}`}>
                          Review and edit the containing section
                        </Link>
                      </>
                    )}
                  </p>
                  <p>
                    Keep a chapter or poem’s author separate from the editors of its volume. For a
                    section mixing commentary, quotations, or biblical text, apply a verified credit
                    only to the passage it covers. Your evidence-backed corrections are shared with
                    Codex.
                  </p>
                </section>
              ) : (
                <p className="notice">
                  This citation belongs only to the selected source component. Ask Codex to revise
                  its recorded source boundaries or credits; editing the entire passage could affect
                  other components.{' '}
                  <Link to={`/review/${encode(passage.work_id)}?passage=${encode(target)}`}>
                    Review and edit book publication details
                  </Link>
                  .
                </p>
              )}
              <form onSubmit={exportCitation} aria-busy={download.isPending}>
                <input type="hidden" name="segment" value={text(data.segment_id)} />
                <input
                  type="hidden"
                  name="locator_type"
                  value={text(locator.type) || text(data.locator_type)}
                />
                <input
                  type="hidden"
                  name="locator_value"
                  value={text(locator.value) || text(data.locator_value)}
                />
                <input
                  type="hidden"
                  name="locator_verified"
                  value={locator.verified ? 'yes' : ''}
                />
                <input type="hidden" name="locator_evidence" value={text(locator.evidence)} />
                <label htmlFor="export-format">Export this citation</label>
                <select id="export-format" name="format">
                  <option value="txt">Plain text</option>
                  <option value="md">Markdown</option>
                  <option value="json">Structured citation data</option>
                </select>
                <button className="secondary" type="submit" disabled={download.isPending}>
                  Download citation
                </button>
                <ErrorNotice error={download.error} />
              </form>
            </>
          ) : (
            Boolean(citation.work_id) && (
              <p>
                <Link to={`/review/${encode(citation.work_id)}`}>
                  Review book publication details
                </Link>
              </p>
            )
          )}
        </>
      )}
    </>
  );
}

export function CitationPage() {
  return <Resource>{(data) => <CitationContent data={data} />}</Resource>;
}

export function IllustrationPage() {
  return (
    <Resource>
      {(data) => {
        const illustration = record(data.illustration);
        return (
          <>
            <p className="breadcrumb">
              <Link to="/books">The shelves</Link>
              {Boolean(illustration.work_id) && (
                <>
                  {' '}
                  / <Link to={`/books/${encode(illustration.work_id)}`}>Book contents</Link>
                </>
              )}
            </p>
            <section className="page-intro">
              <p className="eyebrow">Reading context</p>
              <h1>Source illustration</h1>
              <p className="lede">{text(illustration.filename)}</p>
            </section>
            {illustration.description_status === 'description_missing' ? (
              <p className="notice">
                The source supplies no alternative text for this illustration. Its content has not
                been interpreted automatically; consult the nearby caption and passage, or ask for a
                visual inspection.
              </p>
            ) : (
              <section aria-labelledby="description-heading">
                <h2 id="description-heading">Description supplied by the source</h2>
                {array(illustration.alt_texts).map((value, i) => (
                  <p key={i}>{text(value)}</p>
                ))}
              </section>
            )}
            <figure className="source-illustration">
              <img
                src={`/image/${encode(illustration.file_id)}?member=${encode(illustration.member)}`}
                alt={text(illustration.alt)}
                decoding="async"
              />
              {array(illustration.captions).length > 0 && (
                <figcaption>
                  {array(illustration.captions).map((value, i) => (
                    <p key={i}>{text(value)}</p>
                  ))}
                </figcaption>
              )}
            </figure>
            <details className="source-copy">
              <summary>Source location</summary>
              <p className="source-path">{text(illustration.source_path)}</p>
              <p className="source-path">Package image: {text(illustration.member)}</p>
              <p className="hint">
                This image is read directly from the local book. It has not been downloaded again or
                altered. The reading room displays PNG, JPEG, GIF, and WebP images up to 20 MiB;
                other source formats remain available in the original copy.
              </p>
            </details>
          </>
        );
      }}
    </Resource>
  );
}
