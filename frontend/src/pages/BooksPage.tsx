import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { usePage } from '../api';
import { object, records, text } from '../data';
import { Catalog, CatalogCount, PageNav, PageState } from '../ui';
import { SuggestionInput } from '../components/SuggestionInput';

export function BooksPage() {
  const query = usePage(),
    navigate = useNavigate();
  return (
    <PageState query={query}>
      {(page) => (
        <BooksView
          key={text(page.data.q) + text(page.data.sort) + text(page.data.facet)}
          data={page.data}
          navigate={(path) => void navigate(path)}
        />
      )}
    </PageState>
  );
}
function BooksView({
  data,
  navigate,
}: {
  data: ReturnType<typeof object>;
  navigate: (path: string) => void;
}) {
  const [query, setQuery] = useState(text(data.q));
  return (
    <>
      <section className="page-intro catalog-intro">
        <p className="eyebrow">The current collection</p>
        <h1>The shelves.</h1>
        <p>
          <Link to="/taxonomy">Browse subjects & connections</Link>
        </p>
      </section>
      <form
        className="catalog-toolbar"
        onSubmit={(e) => {
          e.preventDefault();
          const fields = new FormData(e.currentTarget);
          navigate(
            '/books?' +
              new URLSearchParams({
                q: query,
                sort: String(fields.get('sort') ?? 'title'),
                ...(data.facet ? { facet: text(data.facet) } : {}),
              }),
          );
        }}
      >
        <div className="catalog-query">
          <SuggestionInput
            id="book-query"
            name="q"
            label="Find a book or creator"
            kind="catalog"
            maxLength={300}
            value={query}
            onChange={setQuery}
          />
        </div>
        <div className="catalog-sort">
          <label htmlFor="book-sort">Sort by</label>
          <select id="book-sort" name="sort" defaultValue={text(data.sort, 'title')}>
            <option value="title">Title A–Z</option>
            <option value="creator">Creator A–Z</option>
          </select>
        </div>
        <button type="submit">Find books</button>
      </form>
      {data.facet && (
        <p className="active-filters">
          Subject: <strong>{text(data.facet)}</strong>{' '}
          <Link to={text(data.clear_filter_url, '/books')}>Clear this filter</Link>
        </p>
      )}
      <CatalogCount result={data.result} matching={!!(data.q || data.facet)} />
      {records(data.books).length ? (
        <Catalog value={data.books} />
      ) : (
        <p className="empty-state">
          No books on this page.{' '}
          <Link to={text(data.first_page_url, '/books')}>Return to the first page</Link>, or{' '}
          <Link to="/status">check the library’s current index</Link>.
        </p>
      )}
      <PageNav previous={data.previous_url} next={data.next_url} label="Book list pages" />
    </>
  );
}
