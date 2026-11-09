import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { pageKey, type Fields, type UiPage } from '../api';
import { ReviewPage } from './ReviewPage';

function reviewPage(
  version = 1,
  value = 'Current title',
  proposal = false,
): Extract<UiPage, { page: 'review' }> {
  const field = {
    key: 'title',
    label: 'Displayed title',
    kind: 'text',
    current_display: 'Current title',
    edit_value: value,
    edit_evidence: 'Title page',
    edit_verified: true,
    dom_id: 'review-field-title',
    editor_open: true,
    help: 'Changes the title shown in the library.',
    ...(proposal ? { proposal_prefill: 'proposal-1' } : {}),
  };
  return {
    page: 'review',
    title: 'Review and edit information',
    nav: 'books',
    data: {
      review: { revision: 'revision-1', source_current: true },
      target: {
        id: 'book-1',
        work_id: 'book-1',
        work_title: 'A book',
        title: 'A book',
        scope: 'work',
      },
      draft: {
        target_id: 'book-1',
        revision: 'revision-1',
        version,
        changes: {},
        suggestions: [],
        stale: false,
      },
      groups: { 'Display information': [field] },
      field_map: { title: field },
      guidance: [],
      current_recommendation: null,
      pending: [],
      message: '',
      error: '',
      review_url: '/review/book-1',
      request_id: 'request-1',
      busy: false,
      navigation: { section_offset: 0, passage: '' },
      edit_field: 'title',
      guided_step: 'summary',
      guided_view_url: '/review/book-1',
      summary_url: '/review/book-1?step=summary',
      action_groups: [],
      deferred: [],
      handled: [],
      important_guidance: [],
      optional_guidance: [],
    },
  };
}

function setup(
  page = reviewPage(),
  post?: (fields: Fields, path: string) => Promise<Response>,
  address = '/review/book-1',
) {
  const requests: { path: string; fields: Fields }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/ui/bootstrap') return Response.json({ csrf: 'test-token' });
      if (init?.method === 'POST') {
        const fields = (JSON.parse(String(init.body)) as { fields: Fields }).fields;
        requests.push({ path, fields });
        return post
          ? post(fields, path)
          : Response.json(
              reviewPage(Number(fields.version) + 1, String(fields.value || 'Current title')),
            );
      }
      return Response.json(page);
    }),
  );
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        retry: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
      mutations: { retry: false },
    },
  });
  client.setQueryData(pageKey(address), page);
  const router = createMemoryRouter(
    [
      { path: '/review/:id', element: <ReviewPage /> },
      { path: '/books/:id', element: <h1>Book details destination</h1> },
    ],
    { initialEntries: [address] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { requests, client, router };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('review drafts', () => {
  it('saves a local draft after typing and clears verification without applying it', async () => {
    const { requests } = setup();
    const input = screen.getByRole('textbox', { name: 'Proposed displayed title' });
    fireEvent.change(input, { target: { value: 'A source-supported title' } });
    expect(
      screen.getByRole('checkbox', { name: 'I verified this field against the evidence.' }),
    ).not.toBeChecked();
    expect(requests).toHaveLength(0);
    await waitFor(() => expect(requests).toHaveLength(1), { timeout: 2200 });
    expect(requests[0]).toEqual({
      path: '/api/ui/review/book-1/draft',
      fields: expect.objectContaining({
        field: 'title',
        value: 'A source-supported title',
        verified: '',
        version: '1',
        revision: 'revision-1',
      }),
    });
    expect(requests.some((request) => request.path.endsWith('/apply'))).toBe(false);
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Draft saved locally.'),
    );
    expect(screen.getAllByText(/Draft saved locally\./)).toHaveLength(1);
  });

  it('keeps newer typing when an earlier save returns and serializes against the new version', async () => {
    let finishFirst!: (response: Response) => void;
    let first = true;
    const { requests } = setup(reviewPage(), async (fields) => {
      if (first) {
        first = false;
        return new Promise<Response>((resolve) => {
          finishFirst = resolve;
        });
      }
      return Response.json(reviewPage(Number(fields.version) + 1, String(fields.value)));
    });
    const input = screen.getByRole('textbox', { name: 'Proposed displayed title' });
    fireEvent.change(input, { target: { value: 'First edit' } });
    await waitFor(() => expect(requests).toHaveLength(1), { timeout: 2200 });
    fireEvent.change(input, { target: { value: 'Newer edit while saving' } });
    await act(async () => finishFirst(Response.json(reviewPage(2, 'First edit'))));
    expect(input).toHaveValue('Newer edit while saving');
    await waitFor(() => expect(requests).toHaveLength(2), { timeout: 2200 });
    expect(requests[1].fields).toMatchObject({ value: 'Newer edit while saving', version: '2' });
  });

  it('flushes a pending draft before navigation', async () => {
    let finishSave!: (response: Response) => void;
    const { requests } = setup(
      reviewPage(),
      () =>
        new Promise<Response>((resolve) => {
          finishSave = resolve;
        }),
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Proposed displayed title' }), {
      target: { value: 'Before leaving' },
    });
    fireEvent.click(screen.getByRole('link', { name: 'A book' }));
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(
      screen.queryByRole('heading', { name: 'Book details destination' }),
    ).not.toBeInTheDocument();
    await act(async () => finishSave(Response.json(reviewPage(2, 'Before leaving'))));
    expect(
      await screen.findByRole('heading', { name: 'Book details destination' }),
    ).toBeInTheDocument();
  });

  it('requires Add to draft for an edited suggestion and blocks leaving it unresolved', async () => {
    const { requests } = setup(reviewPage(1, 'Suggested title', true));
    fireEvent.change(screen.getByRole('textbox', { name: 'Proposed displayed title' }), {
      target: { value: 'Edited suggestion' },
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1300));
    });
    expect(requests).toHaveLength(0);
    fireEvent.click(screen.getByRole('link', { name: 'A book' }));
    await screen.findByText(
      'Choose Add to draft or Cancel suggestion edit before continuing. The suggestion has not been accepted.',
    );
    expect(
      screen.queryByRole('heading', { name: 'Book details destination' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add to draft' }));
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].fields).toMatchObject({
      proposal_item_id: 'proposal-1',
      value: 'Edited suggestion',
      verified: '',
    });
  });

  it('retains input after a conflict and never retries the failed save automatically', async () => {
    const conflict = reviewPage(2, 'Another editor’s title');
    conflict.data.error = 'This draft changed in another window. Recheck it before saving.';
    const { requests } = setup(reviewPage(), async () => Response.json(conflict, { status: 409 }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Proposed displayed title' }), {
      target: { value: 'My unsaved title' },
    });
    await waitFor(() => expect(requests).toHaveLength(1), { timeout: 2200 });
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This draft changed in another window.',
    );
    expect(screen.getByRole('textbox', { name: 'Proposed displayed title' })).toHaveValue(
      'My unsaved title',
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1300));
    });
    expect(requests).toHaveLength(1);
  });

  it('removes the accepted proposal URL while keeping newer typing for the next draft save', async () => {
    let finishSave!: (response: Response) => void;
    const { requests, router, client } = setup(
      reviewPage(1, 'Suggested title', true),
      () =>
        new Promise<Response>((resolve) => {
          finishSave = resolve;
        }),
      '/review/book-1?proposal=proposal-1&edit=title',
    );
    const input = screen.getByRole('textbox', { name: 'Proposed displayed title' });
    fireEvent.change(input, { target: { value: 'My accepted version' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add to draft' }));
    await waitFor(() => expect(requests).toHaveLength(1));
    fireEvent.change(input, { target: { value: 'Newer typing during acceptance' } });
    await act(async () => finishSave(Response.json(reviewPage(2, 'My accepted version'))));
    await waitFor(() => expect(router.state.location.search).toBe(''));
    expect(screen.getByRole('textbox', { name: 'Proposed displayed title' })).toHaveValue(
      'Newer typing during acceptance',
    );
    const cached = client.getQueryData<UiPage>(pageKey('/review/book-1'));
    expect(
      cached?.page === 'review' ? cached.data.field_map.title.proposal_prefill : true,
    ).toBeUndefined();
    expect(requests).toHaveLength(1);
  });

  it('shows a decimal-string review cost accurately', () => {
    const page = reviewPage();
    page.data.draft.suggestion_cost = { charged_or_reserved: '0.0221915', uncertain: false };
    setup(page);
    fireEvent.click(screen.getByText('AI review limits and consulted sources'));
    expect(screen.getByText('This review cost $0.0222.')).toBeInTheDocument();
  });

  it('includes a newly autosaved field in the final apply after flushing', async () => {
    const page = reviewPage(2, 'Earlier accepted title');
    const title = page.data.field_map.title;
    const notes = {
      ...title,
      key: 'notes',
      label: 'Research notes',
      dom_id: 'review-field-notes',
      edit_value: '',
      edit_evidence: '',
      edit_verified: false,
    };
    page.data.field_map.notes = notes;
    page.data.groups['Display information'].push(notes);
    page.data.pending = [
      {
        field: title,
        change: { value: 'Earlier accepted title', evidence: 'Title page', verified: false },
        proposed_display: 'Earlier accepted title',
      },
    ];
    page.data.draft.changes = {
      title: { value: 'Earlier accepted title', evidence: 'Title page', verified: false },
    };
    const { requests } = setup(page, async (fields, path) => {
      if (path.endsWith('/draft')) {
        const after = structuredClone(page);
        after.data.draft.version = 3;
        after.data.pending.push({
          field: notes,
          change: { value: fields.value, evidence: '', verified: false },
          proposed_display: fields.value,
        });
        after.data.draft.changes!.notes = { value: fields.value, evidence: '', verified: false };
        return Response.json(after);
      }
      return Response.json(reviewPage(4, 'Earlier accepted title'));
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Proposed research notes' }), {
      target: { value: 'A new note immediately before saving' },
    });
    fireEvent.click(screen.getByText('Changes ready to save (1)'));
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[0].path).toBe('/api/ui/review/book-1/draft');
    expect(requests[1].path).toBe('/api/ui/review/book-1/apply');
    expect(requests[1].fields).toMatchObject({
      count: '2',
      field_0: 'title',
      selected_0: 'yes',
      field_1: 'notes',
      selected_1: 'yes',
      version: '3',
    });
  });

  it('does not pull the user back after a recommendation finishes on a departed page', async () => {
    const page = reviewPage();
    const rec = {
      id: 'recommendation-1',
      question: 'Is the title correct?',
      recommendation: 'Keep the current title.',
      status: 'pending',
      priority: 'important',
      primary_action: 'keep',
      action_label: 'Keep this title',
      change_items: [],
      field_education: [],
    };
    page.data.current_recommendation = rec;
    page.data.guidance = [rec];
    let finishAction!: (response: Response) => void;
    const { requests, router } = setup(
      page,
      () =>
        new Promise<Response>((resolve) => {
          finishAction = resolve;
        }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Keep this title: Is the title correct?' }));
    await waitFor(() => expect(requests).toHaveLength(1));
    fireEvent.click(screen.getByRole('link', { name: 'A book' }));
    expect(
      await screen.findByRole('heading', { name: 'Book details destination' }),
    ).toBeInTheDocument();
    const after = reviewPage(2);
    after.data.guided_view_url = '/review/book-1?step=summary';
    await act(async () => finishAction(Response.json(after)));
    expect(router.state.location.pathname).toBe('/books/book-1');
    expect(screen.getByRole('heading', { name: 'Book details destination' })).toBeInTheDocument();
  });

  it('does not poll a running review', async () => {
    const page = reviewPage();
    page.data.busy = true;
    setup(page);
    expect(screen.getByRole('button', { name: 'AI review is running…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Refresh review progress' })).toBeEnabled();
    const fetcher = vi.mocked(fetch);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    expect(fetcher.mock.calls.some(([input]) => String(input).endsWith('/state'))).toBe(false);
  });
});
