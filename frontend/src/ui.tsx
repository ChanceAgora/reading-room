import { useEffect, useId } from 'react';
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import type { JsonValue, UiPage } from './api';
import { humanize, number, object, records, text } from './data';

export function Button(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" {...props} />;
}

/** In-page jumps keep the current session snapshot and do not add a blank entry. */
export function FragmentLink({
  href,
  className,
  children,
}: {
  href: `#${string}`;
  className?: string;
  children: ReactNode;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <a
      href={href}
      className={className}
      onClick={(event) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
          return;
        event.preventDefault();
        const state = window.history.state as { usr?: unknown } | null;
        void navigate(
          { pathname: location.pathname, search: location.search, hash: href },
          {
            state: state?.usr,
            replace: true,
            preventScrollReset: true,
          },
        );
      }}
    >
      {children}
    </a>
  );
}
export function Field({
  label,
  help,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; help?: string }) {
  const generated = useId();
  const id = props.id ?? generated;
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        {...props}
        id={id}
        aria-describedby={help ? `${id}-help` : props['aria-describedby']}
      />
      {help && (
        <p id={`${id}-help`} className="hint">
          {help}
        </p>
      )}
    </div>
  );
}
export function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p className="notice" role="alert">
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}
export function PageState({
  query,
  children,
}: {
  query: UseQueryResult<UiPage, Error>;
  children?: ReactNode | ((page: UiPage) => ReactNode);
}) {
  useEffect(() => {
    if (query.data) document.title = `${query.data.title} · The Reading Room`;
  }, [query.data]);
  if (!query.data)
    return query.error ? (
      <>
        <h1>We couldn’t open that.</h1>
        <ErrorMessage error={query.error} />
        <Button onClick={() => void query.refetch()}>Try again</Button>
      </>
    ) : (
      <p role="status">Opening the reading room…</p>
    );
  return (
    <>
      <ErrorMessage error={query.error} />
      {typeof children === 'function' ? children(query.data) : children}
    </>
  );
}
export function ObjectDetails({ value }: { value: JsonValue | undefined }) {
  if (value == null) return <span className="muted">Not recorded</span>;
  if (typeof value === 'boolean') return <>{value ? 'Yes' : 'No'}</>;
  if (typeof value !== 'object') return <>{String(value)}</>;
  if (Array.isArray(value))
    return value.length ? (
      <ul>
        {value.map((item, i) => (
          <li key={i}>
            <ObjectDetails value={item} />
          </li>
        ))}
      </ul>
    ) : (
      <span className="muted">None recorded</span>
    );
  return (
    <dl className="details-list">
      {Object.entries(value).map(([key, item]) => (
        <div key={key}>
          <dt>{humanize(key)}</dt>
          <dd>
            <ObjectDetails value={item} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function Limitations({ items }: { items: JsonValue | undefined }) {
  if (!Array.isArray(items) || !items.length) return null;
  return (
    <div className="limitations">
      <p className="label">Source limitations</p>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{text(item)}</li>
        ))}
      </ul>
    </div>
  );
}
export function Catalog({ value }: { value: JsonValue | undefined }) {
  const books = records(value);
  return (
    <ul className="catalog-list">
      {books.map((item) => {
        const metadata = object(item.metadata),
          bibliography = object(item.bibliography);
        const edition = text(
          item.catalog_edition || bibliography.edition || item.edition || metadata.edition,
        );
        const year = text(
          item.catalog_year ||
            bibliography.year ||
            item.year ||
            metadata.publication_year ||
            metadata.year,
        );
        return (
          <li key={text(item.id)}>
            <article className="catalog-entry">
              <span className="catalog-cover" aria-hidden="true">
                <img
                  src={`/covers/${encodeURIComponent(text(item.id))}`}
                  alt=""
                  width="48"
                  height="72"
                  loading="lazy"
                  onError={(event) => {
                    event.currentTarget.hidden = true;
                  }}
                />
              </span>
              <div className="catalog-entry-body">
                <h2 className="catalog-title">
                  <Link to={`/books/${encodeURIComponent(text(item.id))}`}>{text(item.title)}</Link>
                </h2>
                <p className="catalog-credit">
                  {text(item.catalog_credit || item.author, 'Contributor not yet recorded')}
                </p>
                {(edition || year) && (
                  <p className="catalog-edition">{[edition, year].filter(Boolean).join(' · ')}</p>
                )}
              </div>
            </article>
          </li>
        );
      })}
    </ul>
  );
}
export function CatalogCount({
  result,
  matching = false,
}: {
  result: JsonValue | undefined;
  matching?: boolean;
}) {
  const data = object(result),
    total = number(data.total),
    offset = number(data.offset),
    count = records(data.books).length;
  return (
    <p className="catalog-summary" role="status">
      {count > 0 && (
        <>
          <strong>
            {offset + 1}–{offset + count}
          </strong>{' '}
          of{' '}
        </>
      )}
      {total}
      {matching ? ' matching' : ''} {total === 1 ? 'book' : 'books'}
      {count === 0 && total > 0 && ' · No books on this page'}
    </p>
  );
}
export function PageNav({
  previous,
  next,
  label = 'Pages',
}: {
  previous?: JsonValue;
  next?: JsonValue;
  label?: string;
}) {
  return (
    <nav className="page-nav" aria-label={label}>
      {typeof previous === 'string' && previous && <Link to={previous}>← Previous</Link>}
      {typeof next === 'string' && next && <Link to={next}>Next →</Link>}
    </nav>
  );
}
