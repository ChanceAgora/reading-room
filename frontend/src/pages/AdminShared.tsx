import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ApiError,
  apiAction,
  formFields,
  pageKey,
  usePage,
  type Fields,
  type JsonObject,
  type UiPage,
} from '../api';
import { humanize, list, number, object, records, safeHref, strings, text } from '../data';

export { humanize, list, number, object, records, safeHref, strings, text };
export type { Fields, JsonObject, UiPage };

export function SafeLink({
  href,
  children,
  ...props
}: {
  href: unknown;
  children: ReactNode;
  className?: string;
  'aria-label'?: string;
  'aria-current'?: 'step' | 'page';
}) {
  const target = safeHref(href, '');
  if (!target) return <span>{children}</span>;
  return target.startsWith('/') ? (
    <Link to={target} {...props}>
      {children}
    </Link>
  ) : (
    <a href={target} {...props}>
      {children}
    </a>
  );
}

export function Message({ error, children }: { error?: boolean; children: ReactNode }) {
  return children ? (
    <div className={`notice${error ? ' review-error' : ''}`} role={error ? 'alert' : 'status'}>
      {children}
    </div>
  ) : null;
}

export function PageLoading({ query }: { query: ReturnType<typeof usePage> }) {
  if (query.isPending) return <p role="status">Opening the Reading Room…</p>;
  if (query.error && !query.data)
    return (
      <Message error>
        {query.error.message}{' '}
        <button type="button" onClick={() => void query.refetch()}>
          Try again
        </button>
      </Message>
    );
  return null;
}

export function useAdminPage() {
  const location = useLocation();
  const currentLocation = useRef(location.key);
  currentLocation.current = location.key;
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const address = location.pathname + location.search;
  const query = usePage();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState('');
  const mutation = useMutation({
    mutationFn: ({ path, fields }: { path: string; fields: Fields }) => apiAction(path, fields),
    retry: false,
  });
  async function action(path: string, fields: Fields = {}) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError('');
    const origin = location.key;
    const stillHere = () => mounted.current && currentLocation.current === origin;
    try {
      const response = await mutation.mutateAsync({ path, fields });
      if ('redirect' in response) {
        if (stillHere()) await navigate(response.redirect);
      } else client.setQueryData(pageKey(address), response);
      return response;
    } catch (caught) {
      if (caught instanceof ApiError && caught.page)
        client.setQueryData(pageKey(address), caught.page);
      if (stillHere())
        setError(
          caught instanceof Error
            ? caught.message
            : 'The action could not finish. Your input has been kept.',
        );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  function submit(path: string) {
    return (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      void action(
        path,
        formFields(event.currentTarget, (event.nativeEvent as SubmitEvent).submitter),
      );
    };
  }
  return {
    query,
    data: object(query.data?.data),
    page: query.data,
    action,
    submit,
    busy,
    error: error || query.error?.message || '',
    address,
  };
}

export function PageMessages({ data, error }: { data: JsonObject; error?: string }) {
  return (
    <>
      <Message error>{error || text(data.error)}</Message>
      <Message>{text(data.message)}</Message>
    </>
  );
}

export function Pagination({
  previous,
  next,
  label = 'Pages',
  previousLabel = 'Previous',
  nextLabel = 'Next',
}: {
  previous: unknown;
  next: unknown;
  label?: string;
  previousLabel?: string;
  nextLabel?: string;
}) {
  return (
    <nav className="page-nav" aria-label={label}>
      {text(previous) && <SafeLink href={previous}>← {previousLabel}</SafeLink>}
      {text(next) && <SafeLink href={next}>{nextLabel} →</SafeLink>}
    </nav>
  );
}

export function DefinitionList({ data, labels }: { data: JsonObject; labels: [string, string][] }) {
  return (
    <dl className="details-list">
      {labels
        .filter(([key]) => data[key] !== undefined && data[key] !== null && data[key] !== '')
        .map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>{display(data[key])}</dd>
          </div>
        ))}
    </dl>
  );
}

export function display(value: unknown): string {
  if (value === true) return 'Yes';
  if (value === false) return 'No';
  if (value === null || value === undefined || value === '') return 'Not recorded';
  if (Array.isArray(value)) return value.map(display).join('; ') || 'None explicitly recorded';
  if (typeof value === 'object') {
    const data = object(value);
    if (data.literal) return text(data.literal);
    if (data.given || data.family)
      return (
        [text(data.given), text(data.family)].filter(Boolean).join(' ') +
        (data.suffix ? `, ${text(data.suffix)}` : '')
      );
    if (data.title || data.label || data.name) return text(data.title || data.label || data.name);
    return Object.entries(data)
      .map(([key, item]) => `${humanize(key)}: ${display(item)}`)
      .join('; ');
  }
  return String(value);
}

export function StructuredDetails({ value }: { value: unknown }) {
  if (Array.isArray(value))
    return (
      <ul>
        {value.map((item, index) => (
          <li key={index}>
            <StructuredDetails value={item} />
          </li>
        ))}
      </ul>
    );
  if (value && typeof value === 'object')
    return (
      <dl className="details-list">
        {Object.entries(object(value)).map(([key, item]) => (
          <div key={key}>
            <dt>{humanize(key)}</dt>
            <dd>
              <StructuredDetails value={item} />
            </dd>
          </div>
        ))}
      </dl>
    );
  return <>{display(value)}</>;
}

export function BookRow({
  book,
  choice,
  checked,
}: {
  book: JsonObject;
  choice?: string;
  checked?: boolean;
}) {
  const title = text(book.title, 'Untitled book');
  const metadata = object(book.metadata),
    bibliography = object(book.bibliography);
  const creators = text(book.catalog_credit || book.author, 'Contributor not yet recorded');
  const edition = text(
    book.catalog_edition || bibliography.edition || book.edition || metadata.edition,
  );
  const year = text(
    book.catalog_year ||
      bibliography.year ||
      book.year ||
      metadata.publication_year ||
      metadata.year,
  );
  return (
    <article className={`catalog-entry${choice ? ' catalog-choice' : ''}`}>
      {choice && (
        <input
          type="checkbox"
          name="books"
          id={choice}
          value={text(book.id)}
          defaultChecked={checked}
          aria-label={`Prefer ${title}`}
        />
      )}
      <span className="catalog-cover" aria-hidden="true">
        <img
          src={`/covers/${encodeURIComponent(text(book.id))}`}
          alt=""
          width={48}
          height={72}
          loading="lazy"
          decoding="async"
          onError={(event) => {
            event.currentTarget.hidden = true;
          }}
        />
      </span>
      <div className="catalog-entry-body">
        <h2 className="catalog-title">
          {choice ? (
            <label className="catalog-choice-label" htmlFor={choice}>
              {title}
            </label>
          ) : (
            <SafeLink href={`/books/${encodeURIComponent(text(book.id))}`}>{title}</SafeLink>
          )}
        </h2>
        <p className="catalog-credit">{creators}</p>
        {(edition || year) && (
          <p className="catalog-edition">
            {edition}
            {edition && year ? ' · ' : ''}
            {year}
          </p>
        )}
        {choice && (
          <Link
            className="small-link"
            to={`/books/${encodeURIComponent(text(book.id))}`}
            aria-label={`View ${title}`}
          >
            View book
          </Link>
        )}
      </div>
    </article>
  );
}

export function ResultCount({ result }: { result: JsonObject }) {
  return (
    <p className="catalog-summary" role="status">
      {records(result.books).length
        ? `${number(result.offset) + 1}–${number(result.offset) + records(result.books).length} of ${number(result.total)} ${number(result.total) === 1 ? 'book' : 'books'}`
        : `${number(result.total)} books${number(result.total) ? ' · No books on this page' : ''}`}
    </p>
  );
}

export function QueryForm({
  action,
  children,
  className = 'compact-form',
}: {
  action: string;
  children: ReactNode;
  className?: string;
}) {
  const navigate = useNavigate();
  return (
    <form
      method="get"
      action={action}
      className={className}
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        const query = new URLSearchParams();
        data.forEach((value, key) => {
          if (typeof value === 'string' && value) query.append(key, value);
        });
        void navigate(action + (query.size ? `?${query}` : ''));
      }}
    >
      {children}
    </form>
  );
}

export function SortOptions() {
  return (
    <>
      <option value="title">Title A–Z</option>
      <option value="creator">Creator A–Z</option>
    </>
  );
}
