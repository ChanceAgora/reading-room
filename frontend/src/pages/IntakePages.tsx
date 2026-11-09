import { Link } from 'react-router-dom';
import {
  DefinitionList,
  Message,
  PageLoading,
  PageMessages,
  Pagination,
  SafeLink,
  humanize,
  number,
  object,
  records,
  strings,
  text,
  useAdminPage,
  type JsonObject,
} from './AdminShared';

function Readiness({ job }: { job: JsonObject }) {
  return (
    <dl className="intake-readiness">
      <div>
        <dt>Reading and text search</dt>
        <dd>{text(job.text_label)}</dd>
      </div>
      <div>
        <dt>Semantic search</dt>
        <dd>{text(job.semantic_label)}</dd>
      </div>
      <div>
        <dt>Automatic metadata review</dt>
        <dd>{text(job.review_label, 'Not requested')}</dd>
      </div>
    </dl>
  );
}

function QueuePause({ job }: { job: JsonObject }) {
  const paused = object(job.paid_blocked_by);
  return paused.id ? (
    <p className="notice">
      Paid intake work is paused across the queue. Text indexing and already-saved results can
      continue.{' '}
      <Link to={`/intake/${encodeURIComponent(text(paused.id))}`}>
        Review the stopped intake and resume when ready
      </Link>
      .
    </p>
  ) : null;
}

export function IntakeListPage() {
  const state = useAdminPage();
  if (!state.page) return <PageLoading query={state.query} />;
  const listing = object(state.data.listing);
  return (
    <section className="intake-page" aria-labelledby="intake-heading">
      <p className="eyebrow">Preparing your library</p>
      <h1 id="intake-heading">Book intake</h1>
      <p>
        See which books are ready to read, what the assistant has checked, and what still needs your
        attention.
      </p>
      <p className="hint">
        Only books you have asked to add or review enter this list. Opening this page does not start
        a review.
      </p>
      <button
        type="button"
        className="secondary"
        disabled={state.query.isFetching}
        onClick={() => void state.query.refetch()}
      >
        Refresh progress
      </button>
      <PageMessages data={state.data} error={state.error} />
      {number(listing.total) ? (
        <>
          <p>
            {number(listing.start)}–{number(listing.end)} of {number(listing.total)} intakes.
          </p>
          <ul className="intake-list">
            {records(listing.items).map((job) => {
              const counts = object(job.counts);
              return (
                <li key={text(job.id)}>
                  <article>
                    <h2>
                      <SafeLink href={job.url}>{text(job.display_title)}</SafeLink>
                    </h2>
                    <p>
                      <strong>{text(job.status_label)}</strong>
                      {text(job.reason) && ` · ${text(job.reason)}`}
                    </p>
                    <QueuePause job={job} />
                    <Readiness job={job} />
                    {Object.keys(counts).length > 0 && (
                      <p className="hint">
                        {number(counts.reviewed)} of {number(counts.total)} review targets processed
                        {number(counts.needs_attention) > 0 &&
                          ` · ${number(counts.needs_attention)} need attention`}
                        .
                      </p>
                    )}
                  </article>
                </li>
              );
            })}
          </ul>
          <Pagination
            label="Intake pages"
            previous={
              listing.previous !== null && listing.previous !== undefined
                ? `/intake?offset=${text(listing.previous)}`
                : ''
            }
            next={
              listing.next !== null && listing.next !== undefined
                ? `/intake?offset=${text(listing.next)}`
                : ''
            }
            previousLabel="Previous intakes"
            nextLabel="More intakes"
          />
        </>
      ) : (
        <>
          <p className="notice">No books are in intake yet.</p>
          <p>
            Ask Codex to add an EPUB or Word book, or use the Bookshare download skill. Your
            existing books are not automatically queued.
          </p>
        </>
      )}
    </section>
  );
}

export function IntakeDetailPage() {
  const state = useAdminPage();
  if (!state.page) return <PageLoading query={state.query} />;
  const d = state.data;
  const job = object(d.job),
    counts = object(d.counts),
    changePage = object(d.change_page),
    targetPage = object(d.target_page);
  const base = `/intake/${encodeURIComponent(text(job.id))}`;
  const fields = { version: text(job.version) };
  return (
    <section className="intake-page" aria-labelledby="intake-heading">
      <p>
        <Link to="/intake">All book intake</Link>
      </p>
      <p className="eyebrow">Book preparation</p>
      <h1 id="intake-heading">{text(job.display_title)}</h1>
      {text(job.source_label) && <p className="hint">Source: {text(job.source_label)}</p>}
      {(records(d.duplicate_links).length > 0 || strings(d.discrepancies).length > 0) && (
        <aside className="notice" aria-labelledby="source-questions-heading">
          <h2 id="source-questions-heading">Source details to check</h2>
          {records(d.duplicate_links).length > 0 && (
            <>
              <p>
                There may already be a related copy in your library. Compare the edition, format,
                and contents before deciding whether these records describe the same copy.
              </p>
              <ul>
                {records(d.duplicate_links).map((candidate, i) => (
                  <li key={i}>
                    <SafeLink href={candidate.url}>Compare with {text(candidate.title)}</SafeLink>
                  </li>
                ))}
              </ul>
              {number(d.duplicate_count) > records(d.duplicate_links).length && (
                <p className="hint">
                  {number(d.duplicate_count)} possible related records were found; the first{' '}
                  {records(d.duplicate_links).length} are shown.
                </p>
              )}
            </>
          )}
          {strings(d.discrepancies).length > 0 && (
            <ul>
              {strings(d.discrepancies).map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          )}
        </aside>
      )}
      <PageMessages data={d} error={state.error} />
      <section id="intake-progress" aria-labelledby="progress-heading">
        <h2 id="progress-heading" tabIndex={-1}>
          {text(job.status_label)}
        </h2>
        <Message>{text(job.reason)}</Message>
        <QueuePause job={job} />
        <Readiness job={job} />
        <p>
          {number(counts.reviewed)} of {number(counts.total)} heading outcomes accounted for.
        </p>
        <p className="hint">
          An outcome does not always mean fully inspected or verified.{' '}
          {number(counts.needs_attention)} review targets need attention
          {number(counts.incomplete) > 0 &&
            `; ${number(counts.incomplete)} have incomplete text coverage`}
          .
        </p>
        {number(counts.needs_attention) > 0 && (
          <p>
            <SafeLink href={d.attention_url}>
              Review {number(counts.needs_attention)} questions needing attention
            </SafeLink>
          </p>
        )}
        {Boolean(job.refresh_pending) && (
          <p className="notice">
            Changes are saved. Search and reading views still need a refresh; the last healthy index
            remains available.
          </p>
        )}
        <div className="intake-actions">
          <button
            type="button"
            className="secondary"
            disabled={state.query.isFetching || state.busy}
            onClick={() => void state.query.refetch()}
          >
            Refresh progress
          </button>
          {Boolean(d.can_request_review) && (
            <button
              type="button"
              className="secondary"
              disabled={state.busy}
              aria-describedby="review-consent-description"
              onClick={() => void state.action(`${base}/review`, fields)}
            >
              Request AI metadata review
            </button>
          )}
          {Boolean(d.can_pause) && (
            <button
              type="button"
              className="secondary"
              disabled={state.busy}
              onClick={() => void state.action(`${base}/pause`, fields)}
            >
              Pause this intake
            </button>
          )}
          {Boolean(d.can_resume) && (
            <button
              type="button"
              disabled={state.busy}
              onClick={() => void state.action(`${base}/resume`, fields)}
            >
              {d.retry_semantic ? 'Retry semantic indexing' : 'Resume this intake'}
            </button>
          )}
        </div>
        {Boolean(d.can_request_review) && (
          <p className="hint" id="review-consent-description">
            Requesting AI review sends bounded source evidence to OpenAI and uses your accepted
            monthly allowance. It checks book details and indexed headings; it does not verify every
            word or change the original book.
          </p>
        )}
        <p className="hint">
          Reviews share the library’s configured monthly allowance. A budget pause waits for you to
          resume, even after a new month begins. Refreshing this page does not start another review.
        </p>
      </section>
      {records(d.work_targets).length > 0 && (
        <nav className="intake-books" aria-label="Books in this intake">
          <h2>Read or review the book</h2>
          <ul>
            {records(d.work_targets).map((target) => (
              <li key={text(target.id)}>
                <Link to={`/books/${encodeURIComponent(text(target.id))}`}>
                  Read {text(target.title)}
                </Link>{' '}
                ·{' '}
                <SafeLink href={target.review_url}>
                  Review book details for {text(target.title)}
                </SafeLink>
                {records(d.work_targets).length > 1 && (
                  <>
                    {' '}
                    ·{' '}
                    <Link to={`${base}?work=${encodeURIComponent(text(target.id))}`}>
                      Intake progress for this book
                    </Link>
                  </>
                )}
              </li>
            ))}
          </ul>
        </nav>
      )}
      <details id="intake-changes" open={records(d.skipped).length > 0 || undefined}>
        <summary>Automatic changes ({number(changePage.total)})</summary>
        <h2>Automatically saved changes</h2>
        <p>
          These changes are already saved as provisional assistant work. They do not mean you have
          personally verified the information.
        </p>
        {records(d.skipped).length > 0 && (
          <div className="notice">
            <h3>Changes kept because they need a separate decision</h3>
            <ul>
              {records(d.skipped).map((item, i) => (
                <li key={i}>{text(item.reason)}</li>
              ))}
            </ul>
          </div>
        )}
        {Boolean(d.can_undo) && !d.work && (
          <>
            <button
              type="button"
              className="secondary"
              disabled={state.busy}
              onClick={() => void state.action(`${base}/undo`, fields)}
            >
              Undo this intake’s changes
            </button>
            <p className="hint">
              Only this intake’s still-current automatic changes are undone. Your later edits are
              kept.
            </p>
          </>
        )}
        {number(changePage.total) ? (
          <>
            <p className="hint">
              Showing {number(changePage.start)}–{number(changePage.end)} of{' '}
              {number(changePage.total)} changes.
            </p>
            <ol className="intake-changes" start={number(changePage.start, 1)}>
              {records(changePage.items).map((change, i) => (
                <li key={text(change.event_id, String(i))}>
                  <article>
                    <h3>{text(change.field_label)}</h3>
                    <p>
                      <strong>{text(change.after_display)}</strong> · {text(change.status_label)}
                      {change.status === 'active' && ' · Provisional'}
                    </p>
                    <details>
                      <summary>
                        Previous value and evidence for {text(change.field_label).toLowerCase()}
                      </summary>
                      <DefinitionList
                        data={change}
                        labels={[
                          ['before_display', 'Before'],
                          ['after_display', 'After'],
                        ]}
                      />
                      <p className="intake-evidence">{text(change.evidence)}</p>
                      <SafeLink href={change.review_url}>
                        Review this information and its source
                      </SafeLink>
                    </details>
                    {Boolean(change.undoable) && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={state.busy}
                        aria-label={`Undo this automatic change: ${text(change.field_label)}`}
                        onClick={() =>
                          void state.action(`${base}/undo`, {
                            ...fields,
                            event_id: text(change.event_id),
                          })
                        }
                      >
                        Undo this automatic change
                      </button>
                    )}
                  </article>
                </li>
              ))}
            </ol>
            <Pagination
              label="Automatic change pages"
              previous={
                changePage.previous_url ? `${text(changePage.previous_url)}#intake-changes` : ''
              }
              next={changePage.next_url ? `${text(changePage.next_url)}#intake-changes` : ''}
              previousLabel="Previous changes"
              nextLabel="More changes"
            />
          </>
        ) : (
          <p>No automatic changes have been saved.</p>
        )}
      </details>
      <details id="intake-targets" open={d.view === 'attention' || undefined}>
        <summary>
          {d.view === 'attention'
            ? 'Questions needing attention'
            : 'Review outcomes and source coverage'}{' '}
          ({number(targetPage.total)})
        </summary>
        <h2>Checks and questions</h2>
        <p>
          {d.view === 'attention' ? (
            <SafeLink href={d.all_outcomes_url}>Show all review outcomes</SafeLink>
          ) : (
            number(counts.needs_attention) > 0 && (
              <SafeLink href={d.attention_url}>Show only questions needing attention</SafeLink>
            )
          )}
        </p>
        <p>
          Book details are checked first. Every indexed heading then gets an outcome; small headings
          and incomplete sections can need further inspection.
        </p>
        {number(targetPage.total) ? (
          <>
            <p className="hint">
              Showing {number(targetPage.start)}–{number(targetPage.end)} of{' '}
              {number(targetPage.total)} targets.
            </p>
            <ol className="intake-targets" start={number(targetPage.start, 1)}>
              {records(targetPage.items).map((target, i) => (
                <li key={text(target.id, String(i))}>
                  <article>
                    <h3>
                      <SafeLink href={target.review_url}>
                        {target.scope === 'work' && 'Book details: '}
                        {text(target.title)}
                      </SafeLink>
                    </h3>
                    <p>
                      <strong>{text(target.status_label)}</strong>
                    </p>
                    {text(target.reason) && <p>{text(target.reason)}</p>}
                    {text(target.coverage_text) && (
                      <p className="hint">
                        {text(target.coverage_text)}
                        {Boolean(target.incomplete) &&
                          ' This was a partial inspection; a whole-section conclusion is not established.'}
                      </p>
                    )}
                  </article>
                </li>
              ))}
            </ol>
            <Pagination
              label="Review outcome pages"
              previous={
                targetPage.previous_url ? `${text(targetPage.previous_url)}#intake-targets` : ''
              }
              next={targetPage.next_url ? `${text(targetPage.next_url)}#intake-targets` : ''}
              previousLabel="Previous outcomes"
              nextLabel="More outcomes"
            />
          </>
        ) : (
          <p>Review targets will appear after the source text has been indexed.</p>
        )}
      </details>
      <details>
        <summary>Intake history and source</summary>
        <DefinitionList
          data={{
            created_at: text(job.created_at, 'Not recorded'),
            updated_at: text(job.updated_at, 'Not recorded'),
            stage: humanize(text(job.stage)),
          }}
          labels={[
            ['created_at', 'Started'],
            ['updated_at', 'Last progress'],
            ['stage', 'Current stage'],
          ]}
        />
        <p className="hint">
          Original files remain unchanged. Acquisition information, suggestions, automatic changes,
          and personal verification are kept separately.
        </p>
      </details>
    </section>
  );
}
