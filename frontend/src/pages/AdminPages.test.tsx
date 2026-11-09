import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { pageKey, type Fields, type UiPage } from '../api';
import {
  BibliographyPage,
  FocusBooksPage,
  MetadataPage,
  TaxonomyPage,
  TaxonomyTermPage,
} from './AdminPages';
import { BookRow } from './AdminShared';
import { IntakeDetailPage } from './IntakePages';

function renderPage(
  element: ReactNode,
  page: UiPage,
  path: string,
  post?: (fields: Fields) => Response,
) {
  const requests: { path: string; fields: Fields }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/ui/bootstrap') return Response.json({ csrf: 'test-token' });
      if (init?.method === 'POST') {
        const fields = (JSON.parse(String(init.body)) as { fields: Fields }).fields;
        requests.push({ path: String(input), fields });
        return post?.(fields) ?? Response.json(page);
      }
      if (String(input).includes('form-options')) return Response.json({ items: [] });
      return Response.json(page);
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(pageKey(path), page);
  const router = createMemoryRouter([{ path: '*', element }], { initialEntries: [path] });
  const result = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { requests, router, ...result };
}

afterEach(() => vi.unstubAllGlobals());

function bibliography(): UiPage {
  return {
    page: 'bibliography',
    title: 'Citation details',
    nav: 'books',
    data: {
      target: {
        id: 'section-1',
        work_id: 'book-1',
        work_title: 'A book',
        title: 'A chapter',
        is_section: true,
        record: {
          title: null,
          short_title: null,
          type: 'chapter',
          authors: [{ given: 'Martin', family: 'King', suffix: 'Jr.', short: 'King' }],
          translators: null,
        },
      },
      fields: { title: 'Citation title', short_title: 'Shortened title' },
      roles: ['authors', 'translators'],
      inherited_translators: [{ literal: 'A. Translator' }],
      passage_id: '',
      saved: false,
      unchanged: false,
    },
  };
}

describe('citation metadata controls', () => {
  it('preserves source names and suffixes, blanks unknowns, and keeps verification explicit', () => {
    renderPage(<BibliographyPage />, bibliography(), '/bibliography/section-1');
    expect(screen.getByRole('textbox', { name: 'Citation title' })).toHaveValue('');
    expect(screen.getByRole('textbox', { name: 'Shortened title' })).toHaveValue('');
    const authors = within(screen.getByRole('group', { name: 'Authors' }));
    expect(authors.getByRole('textbox', { name: 'Names as printed — one per line' })).toHaveValue(
      'Martin King, Jr.',
    );
    expect(
      authors.getByRole('textbox', {
        name: 'Short names or family names — corresponding lines (optional)',
      }),
    ).toHaveValue('King');
    expect(
      screen.getByRole('checkbox', { name: 'No named author appears in this source (verified).' }),
    ).not.toBeChecked();
    expect(
      screen.getByRole('checkbox', {
        name: 'Override the book’s translation credit for this contribution.',
      }),
    ).not.toBeChecked();
    expect(
      screen.getByRole('checkbox', {
        name: 'Also verify unchanged displayed details against this evidence.',
      }),
    ).not.toBeChecked();
    expect(screen.getByText('Current book translation credit: A. Translator.')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Publisher' })).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Publication year' })).not.toBeInTheDocument();
  });

  it('submits explicit author absence separately from unknown authorship', async () => {
    const page = bibliography();
    const { requests } = renderPage(<BibliographyPage />, page, '/bibliography/section-1');
    const authors = within(screen.getByRole('group', { name: 'Authors' }));
    fireEvent.change(authors.getByRole('textbox', { name: 'Names as printed — one per line' }), {
      target: { value: '' },
    });
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'No named author appears in this source (verified).' }),
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'What source details did you verify?' }), {
      target: { value: 'The chapter states no named author. Opening page.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save citation details' }));
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].fields).toMatchObject({
      authors: '',
      authors_absent: 'yes',
      evidence: 'The chapter states no named author. Opening page.',
    });
    expect(requests[0].fields).not.toHaveProperty('translators_override');
    expect(requests[0].fields).not.toHaveProperty('verify_unchanged');
  });

  it('keeps unknown translation credit distinct from verified absence and describes verification choices', () => {
    const page = bibliography();
    if (page.page !== 'bibliography') throw new Error('Expected bibliography fixture');
    page.data.inherited_translators = [];
    renderPage(<BibliographyPage />, page, '/bibliography/section-1');
    expect(screen.getByText('Current book translation credit: None recorded.')).toBeInTheDocument();
    expect(screen.queryByText(/None explicitly recorded/)).not.toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', {
        name: 'Override the book’s translation credit for this contribution.',
      }),
    ).toHaveAccessibleDescription(/Leave unchecked to inherit the book’s translation credit/);
    expect(
      screen.getByRole('checkbox', { name: 'No named author appears in this source (verified).' }),
    ).toHaveAccessibleDescription(
      /Leave names blank and this box unchecked when authorship is unknown/,
    );
    expect(
      screen.getByRole('combobox', { name: 'Scripture scope (Scripture only)' }),
    ).toHaveAccessibleDescription(/Only confirm biblical text after checking every included block/);
    expect(
      screen.getByRole('checkbox', {
        name: 'Also verify unchanged displayed details against this evidence.',
      }),
    ).toHaveAccessibleDescription(/Leave unchecked to preserve the source and verification status/);
    expect(
      screen.getByRole('textbox', { name: 'What source details did you verify?' }),
    ).toHaveAccessibleDescription(/Identify the title page, publication page, chapter heading/);
  });

  it('appends contributor suggestions once without changing printed names or paired short names', () => {
    renderPage(<BibliographyPage />, bibliography(), '/bibliography/section-1');
    const authors = within(screen.getByRole('group', { name: 'Authors' }));
    const names = authors.getByRole('textbox', { name: 'Names as printed — one per line' });
    fireEvent.change(names, { target: { value: 'King, Martin, Jr.\n\n' } });
    const helper = authors.getByRole('combobox', {
      name: 'Find or add names as printed — one per line',
    });
    expect(authors.getAllByRole('combobox')).toHaveLength(1);
    expect(helper).toHaveAttribute('maxlength', '6000');
    fireEvent.change(helper, { target: { value: 'King, Martin, Jr.' } });
    fireEvent.click(authors.getByRole('button', { name: 'Add to list' }));
    expect(names).toHaveValue('King, Martin, Jr.\n\nKing, Martin, Jr.');
    expect(
      authors.getByRole('textbox', {
        name: 'Short names or family names — corresponding lines (optional)',
      }),
    ).toHaveValue('King');
  });
});

describe('vocabulary and catalog controls', () => {
  it('keeps vocabulary search editable and preserves the query', () => {
    const page: UiPage = {
      page: 'taxonomy',
      title: 'Subjects & connections',
      nav: 'taxonomy',
      data: {
        vocabulary: { query: 'Oríkì & poetry', facets: [], terms: [] },
        next_url: null,
        previous_url: null,
      },
    };
    renderPage(<TaxonomyPage />, page, '/taxonomy?q=Or%C3%ADk%C3%AC');
    const control = screen.getByRole('combobox', {
      name: 'Find a subject, form, or other classification',
    });
    expect(control).toHaveValue('Oríkì & poetry');
    expect(control).not.toHaveAttribute('readonly');
    fireEvent.change(control, { target: { value: 'Verse and ecology' } });
    expect(control).toHaveValue('Verse and ecology');
  });

  it('labels term editors and retains submitted text when a relation is rejected', async () => {
    const page: UiPage = {
      page: 'taxonomy_term',
      title: 'Add a term',
      nav: 'taxonomy',
      data: {
        term: { label: '', aliases: [] },
        relation_labels: { broader: [], narrower: [], related: [] },
        creating: true,
        action: '/taxonomy/new',
        saved: false,
        error: null,
      },
    };
    const { container } = renderPage(<TaxonomyTermPage />, page, '/taxonomy/new', (fields) =>
      Response.json(
        {
          ...page,
          data: {
            ...page.data,
            term: { label: fields.label, aliases: [], evidence: fields.evidence },
            error: 'Create the vocabulary term before linking it.',
          },
        },
        { status: 400 },
      ),
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), {
      target: { value: '<script>bad()</script>' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Related ideas' }), {
      target: { value: 'Unknown term' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Evidence or editorial reason' }), {
      target: { value: 'Keep this editorial reason.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save vocabulary term' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Create the vocabulary term');
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('<script>bad()</script>');
    expect(screen.getByRole('textbox', { name: 'Related ideas' })).toHaveValue('Unknown term');
    expect(screen.getByRole('textbox', { name: 'Evidence or editorial reason' })).toHaveValue(
      'Keep this editorial reason.',
    );
    expect(container.querySelector('script')).toBeNull();
  });

  it('renders compact escaped catalog entries with decorative covers and separate choice labels', () => {
    const page: UiPage = { page: 'focuses', title: 'Focuses', nav: 'focus', data: { focuses: [] } };
    const { container } = renderPage(
      <BookRow
        book={{
          id: 'unsafe',
          title: '<script>bad()</script>',
          author: '<img src=x onerror=bad()>',
          catalog_edition: 'Second edition',
          catalog_year: '2025',
          metadata: { edition: { private: 'internal' } },
        }}
        choice="pick-book"
      />,
      page,
      '/focus',
    );
    expect(
      screen.getByRole('checkbox', { name: 'Prefer <script>bad()</script>' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View <script>bad()</script>' })).toHaveAttribute(
      'href',
      '/books/unsafe',
    );
    expect(container.querySelector('label a')).toBeNull();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelectorAll('img')).toHaveLength(1);
    expect(container.querySelector('img')).toHaveAttribute('alt', '');
    expect(container.querySelector('img')).toHaveAttribute('width', '48');
    expect(container.querySelector('img')).toHaveAttribute('height', '72');
    expect(screen.getByText('Second edition · 2025')).toBeInTheDocument();
    expect(screen.queryByText(/internal/)).not.toBeInTheDocument();
  });

  it('submits preferred books with the current page, query, and sort', async () => {
    const books = [
      { id: 'book-100', title: 'Book100', author: '', catalog_credit: 'A. Author' },
      { id: 'book-099', title: 'Book099', author: '', catalog_credit: 'B. Author' },
    ];
    const page = {
      page: 'focus-books',
      title: 'Preferred books',
      nav: 'focus',
      data: {
        focus: {
          id: 'fixture',
          name: 'Research',
          description: '',
          breadth: 'balanced',
          books: ['book-001', 'book-100'],
        },
        books,
        result: { total: 100, offset: 0, limit: 50, sort: 'creator', books, has_more: true },
        q: '',
        offset: 0,
        sort: 'creator',
        saved: false,
        next_url: null,
        previous_url: null,
      },
    } as UiPage;
    const { requests } = renderPage(<FocusBooksPage />, page, '/focus/fixture/books?sort=creator');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Prefer Book100' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Prefer Book099' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save choices on this page' }));
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].fields).toMatchObject({
      sort: 'creator',
      offset: '0',
      q: '',
      books: 'book-099',
    });
  });

  it('offers source text-type choices only when the server includes that editable field', () => {
    const page = {
      page: 'metadata',
      title: 'Edit information',
      nav: 'books',
      data: {
        target_id: 'section-1',
        work: { id: 'book-1', title: 'Book', author: '' },
        target: { title: 'Chapter' },
        section_offset: 0,
        saved: false,
        fields: ['text_type', 'title'],
        suggestion_kinds: {},
        text_types: ['prose', 'commentary', 'mixed'],
      },
    } as UiPage;
    renderPage(<MetadataPage />, page, '/metadata/section-1?work=book-1');
    expect(screen.getByRole('combobox', { name: 'Correct kind of writing' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Mixed' })).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Field to correct' }), {
      target: { value: 'title' },
    });
    expect(screen.getByRole('textbox', { name: 'Correct value' })).toBeInTheDocument();
    expect(
      screen.queryByRole('combobox', { name: 'Correct kind of writing' }),
    ).not.toBeInTheDocument();
  });

  it('preserves raw metadata across field and JSON switches and submits the selected text type', async () => {
    const page: UiPage = {
      page: 'metadata',
      title: 'Edit information',
      nav: 'books',
      data: {
        target_id: 'section-1',
        work: { id: 'book-1', title: 'Book', author: '' },
        target: { title: 'Chapter' },
        section_offset: 50,
        saved: false,
        fields: ['title', 'text_type', 'author'],
        suggestion_kinds: { author: 'authors' },
        text_types: ['prose', 'commentary', 'mixed'],
      },
    };
    const { requests } = renderPage(
      <MetadataPage />,
      page,
      '/metadata/section-1?work=book-1&section_offset=50',
    );
    const field = screen.getByRole('combobox', { name: 'Field to correct' });
    fireEvent.change(screen.getByRole('textbox', { name: 'Correct value' }), {
      target: { value: ' commentary \n' },
    });
    fireEvent.change(field, { target: { value: 'text_type' } });
    expect(screen.getByRole('combobox', { name: 'Correct kind of writing' })).toHaveValue(
      'commentary',
    );
    fireEvent.click(screen.getByText('Structured value — advanced'));
    const json = screen.getByRole('checkbox', { name: 'Interpret the value above as JSON' });
    fireEvent.click(json);
    const raw = screen.getByRole('textbox', { name: 'Correct value' });
    expect(raw).toHaveValue(' commentary \n');
    expect(raw).toHaveAccessibleDescription(/Enter valid JSON. Existing text is preserved/);
    fireEvent.change(raw, { target: { value: ' {"custom":"value"} \n' } });
    fireEvent.click(json);
    expect(screen.getByRole('combobox', { name: 'Correct kind of writing' })).toHaveValue('');
    fireEvent.click(json);
    expect(screen.getByRole('textbox', { name: 'Correct value' })).toHaveValue(
      ' {"custom":"value"} \n',
    );
    fireEvent.change(field, { target: { value: 'title' } });
    fireEvent.click(json);
    expect(screen.getByRole('textbox', { name: 'Correct value' })).toHaveValue(
      ' {"custom":"value"} \n',
    );
    fireEvent.change(field, { target: { value: 'text_type' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Correct kind of writing' }), {
      target: { value: 'mixed' },
    });
    fireEvent.change(field, { target: { value: 'title' } });
    expect(screen.getByRole('textbox', { name: 'Correct value' })).toHaveValue('mixed');
    fireEvent.change(field, { target: { value: 'text_type' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Source or reason for the correction' }), {
      target: { value: 'Poetry and commentary on pages 2–3.' },
    });
    expect(screen.getByRole('link', { name: 'Back to book' })).toHaveAttribute(
      'href',
      '/books/book-1?section_offset=50',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].fields).toMatchObject({
      field: 'text_type',
      value: 'mixed',
      section_offset: '50',
    });
    expect(requests[0].fields).not.toHaveProperty('value_format');
  });

  it('uses one credit suggestion helper and preserves the raw credit while toggling JSON', () => {
    const page: UiPage = {
      page: 'metadata',
      title: 'Edit information',
      nav: 'books',
      data: {
        target_id: 'book-1',
        work: { id: 'book-1', title: 'Book', author: '' },
        target: { title: 'Book' },
        section_offset: 0,
        saved: false,
        fields: ['author'],
        suggestion_kinds: { author: 'authors' },
        text_types: [],
      },
    };
    renderPage(<MetadataPage />, page, '/metadata/book-1');
    const raw = screen.getByRole('textbox', { name: 'Correct value' });
    fireEvent.change(raw, { target: { value: 'Old credit' } });
    expect(screen.getAllByRole('combobox', { name: 'Find a recorded value' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Use value' }));
    expect(raw).toHaveValue('Old credit');
    fireEvent.change(screen.getByRole('combobox', { name: 'Find a recorded value' }), {
      target: { value: 'King, Martin, Jr.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Use value' }));
    expect(raw).toHaveValue('King, Martin, Jr.');
    fireEvent.click(screen.getByText('Structured value — advanced'));
    const json = screen.getByRole('checkbox', { name: 'Interpret the value above as JSON' });
    fireEvent.click(json);
    expect(raw).toHaveValue('King, Martin, Jr.');
    expect(
      screen.queryByRole('combobox', { name: 'Find a recorded value' }),
    ).not.toBeInTheDocument();
    fireEvent.click(json);
    expect(screen.getAllByRole('combobox', { name: 'Find a recorded value' })).toHaveLength(1);
    expect(raw).toHaveValue('King, Martin, Jr.');
  });
});

it('keeps intake progress manual and submits the job version with an undo', async () => {
  const page = {
    page: 'intake_detail',
    title: 'Intake',
    nav: 'intake',
    data: {
      job: {
        id: 'intake-1',
        display_title: 'A book',
        version: 4,
        status_label: 'Finished',
        text_label: 'Ready',
        semantic_label: 'Ready',
      },
      counts: { reviewed: 1, total: 1 },
      change_page: {
        total: 1,
        start: 1,
        end: 1,
        items: [
          {
            field_label: 'Displayed title',
            after_display: '<script>unsafe()</script>',
            before_display: 'Old title',
            status: 'active',
            status_label: 'Automatically saved',
            event_id: 'event-1',
            undoable: true,
            review_url: '/review/book-1',
          },
        ],
      },
      target_page: { total: 0, items: [] },
      can_undo: true,
      can_pause: false,
      can_request_review: false,
      can_resume: false,
      work: '',
      work_targets: [],
      skipped: [],
      duplicate_links: [],
      discrepancies: [],
      view: 'all',
      refresh_url: '/intake/intake-1',
      message: '',
      error: '',
    },
  } as UiPage;
  const { requests, container } = renderPage(<IntakeDetailPage />, page, '/intake/intake-1');
  expect(screen.getByRole('button', { name: 'Refresh progress' })).toBeEnabled();
  fireEvent.click(screen.getByText('Automatic changes (1)'));
  fireEvent.click(
    screen.getByRole('button', { name: 'Undo this automatic change: Displayed title' }),
  );
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0]).toEqual({
    path: '/api/ui/intake/intake-1/undo',
    fields: { version: '4', event_id: 'event-1' },
  });
  expect(container.querySelector('script')).toBeNull();
});
