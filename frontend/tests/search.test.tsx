import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SearchPage, restoreSearch } from '../src/pages/SearchPage';
import { queryClient } from '../src/api';
import type { UiPage } from '../src/api';

const hit = {
  id: 'passage-1',
  title: 'A source',
  text: '<script>alert(1)</script> The river.',
  attribution: 'By a contributor',
  reason: 'Text overlap',
  read_url: '/read/passage-1',
};
const result = { direct: [hit], connections: [], warnings: [], coverage: {} };
const fields = {
  q: 'river',
  focus: '',
  mode: '',
  engine: '',
  subject: '',
  form: '',
  book: '',
  author: '',
  text_type: '',
};
const empty: UiPage = {
  page: 'search',
  title: 'Find a thread',
  nav: 'search',
  data: { q: '', selected_focus: '', mode: '', filters: {}, focuses: [], result: null, engine: '' },
};
const completed = { ...empty, data: { ...empty.data, q: 'river', result } };
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

beforeEach(() => {
  window.history.replaceState(null, '', '/');
  sessionStorage.clear();
});

function start(state?: unknown, search = '', pathname = '/search') {
  const client = new QueryClient({ defaultOptions: queryClient.getDefaultOptions() });
  const router = createMemoryRouter(
    [
      { path: '/', Component: SearchPage },
      { path: '/search', Component: SearchPage },
      { path: '/books', element: <h1>The shelves</h1> },
    ],
    { initialEntries: [{ pathname, state, search }] },
  );
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router };
}

describe('explicit research searches', () => {
  it('prefills a historical search URL without fetching or executing its query', async () => {
    const fetcher = vi.fn(async (_url: string) => json(empty));
    vi.stubGlobal('fetch', fetcher);
    start(undefined, '?q=river&engine=exact&mode=exploratory&text_type=poetry');
    expect(await screen.findByRole('searchbox')).toHaveValue('river');
    expect(screen.getByLabelText('Search breadth')).toHaveValue('exploratory');
    expect(screen.getByLabelText('Text type')).toHaveValue('poetry');
    expect(screen.getByRole('status')).toHaveTextContent('no saved results');
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/ui/']);
    expect(document.querySelector('#search-results')).toBeNull();
  });

  it.each([false, true])(
    'restores form-only snapshots after a first search failure: %s',
    async (failFirst) => {
      const fetcher = vi.fn(async (url: string, options?: RequestInit) =>
        url.endsWith('/bootstrap')
          ? json({ csrf: 'fixture' })
          : options?.method === 'POST'
            ? json({ error: 'Allowance unavailable.' }, 400)
            : json(empty),
      );
      vi.stubGlobal('fetch', fetcher);
      const view = start();
      const user = userEvent.setup();
      await user.type(await screen.findByRole('searchbox'), 'an unfinished thought');
      await user.selectOptions(screen.getByLabelText('Search breadth'), 'exploratory');
      await user.click(screen.getByText('Search method', { exact: true }));
      await user.selectOptions(screen.getByLabelText('How to search'), 'exact');
      if (failFirst) {
        await user.click(screen.getByRole('button', { name: 'Search the library' }));
        await screen.findByRole('alert');
      }
      const saved = window.history.state.usr.readingRoomSearch;
      expect(saved.result).toBeNull();
      expect(saved.disclosures).toContain('method');
      view.unmount();
      start({ readingRoomSearch: saved });
      expect(await screen.findByRole('searchbox')).toHaveValue('an unfinished thought');
      expect(screen.getByLabelText('Search breadth')).toHaveValue('exploratory');
      expect(screen.getByLabelText('How to search')).toHaveValue('exact');
      expect(document.querySelector('details.search-method')).toHaveAttribute('open');
      expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
        failFirst ? 1 : 0,
      );
      expect(screen.getByRole('status')).toHaveTextContent('no saved results');
    },
  );

  it('never executes a search when restoring results or receiving focus/online events', async () => {
    const fetcher = vi.fn(async (_url: string) => json(empty));
    vi.stubGlobal('fetch', fetcher);
    start({
      readingRoomSearch: { version: 2, fields, result, submitted: 'river', disclosures: [] },
    });
    await screen.findByText('<script>alert(1)</script> The river.');
    expect(document.querySelector('main script, .excerpt script')).toBeNull();
    expect(screen.getByRole('searchbox').getAttribute('value')).toBe('river');
    fireEvent(window, new Event('focus'));
    fireEvent(window, new Event('online'));
    expect(fetcher.mock.calls.every((call) => !String(call[0]).endsWith('/search'))).toBe(true);
  });

  it.each(['/', '/search'])(
    'prevents duplicate submissions and preserves newer typing/focus from %s',
    async (pathname) => {
      let finish: (value: Response) => void = () => undefined;
      const fetcher = vi.fn((url: string, options?: RequestInit) => {
        if (url.endsWith('/bootstrap')) return Promise.resolve(json({ csrf: 'fixture' }));
        if (options?.method === 'POST')
          return new Promise<Response>((resolve) => {
            finish = resolve;
          });
        return Promise.resolve(json(empty));
      });
      vi.stubGlobal('fetch', fetcher);
      start(undefined, '', pathname);
      const user = userEvent.setup();
      const input = await screen.findByRole('searchbox');
      await user.type(input, 'river');
      const form = input.closest('form')!;
      fireEvent.submit(form);
      fireEvent.submit(form);
      await waitFor(() =>
        expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
          1,
        ),
      );
      await user.clear(input);
      await user.type(input, 'another thought');
      await act(async () => finish(json(completed)));
      await screen.findByText('<script>alert(1)</script> The river.');
      expect(input).toHaveValue('another thought');
      expect(input).toHaveFocus();
      expect(document.querySelector('#search-content [role="status"]')).toBeNull();
      expect(screen.getByRole('status')).toHaveTextContent('1 direct match for river.');
    },
  );

  it('keeps previous results after failure and does not retry the paid request', async () => {
    const fetcher = vi.fn(async (url: string, options?: RequestInit) =>
      url.endsWith('/bootstrap')
        ? json({ csrf: 'fixture' })
        : options?.method === 'POST'
          ? json({ error: 'Allowance unavailable.' }, 400)
          : json(empty),
    );
    vi.stubGlobal('fetch', fetcher);
    start({
      readingRoomSearch: { version: 2, fields, result, submitted: 'river', disclosures: [] },
    });
    await screen.findByText('<script>alert(1)</script> The river.');
    await userEvent.click(screen.getByRole('button', { name: 'Search the library' }));
    await screen.findByRole('alert');
    expect(screen.getByText('<script>alert(1)</script> The river.')).toBeVisible();
    expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
  });

  it('does not navigate back when an in-flight request completes after leaving search', async () => {
    let finish: (value: Response) => void = () => undefined;
    const fetcher = vi.fn((url: string, options?: RequestInit) =>
      options?.method === 'POST'
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(json(url.endsWith('/bootstrap') ? { csrf: 'fixture' } : empty)),
    );
    vi.stubGlobal('fetch', fetcher);
    const { router } = start();
    const input = await screen.findByRole('searchbox');
    await userEvent.type(input, 'river');
    await userEvent.click(screen.getByRole('button', { name: 'Search the library' }));
    await waitFor(() =>
      expect(fetcher.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(true),
    );
    await act(async () => {
      await router.navigate('/books');
    });
    await act(async () => finish(json(completed)));
    expect(router.state.location.pathname).toBe('/books');
    expect(screen.getByRole('heading', { name: 'The shelves' })).toBeVisible();
  });

  it('rejects incompatible or malformed saved searches without executing them', () => {
    expect(restoreSearch({ version: 1, fields, result })).toBeNull();
    expect(
      restoreSearch({ version: 2, fields: { q: 'river' }, result, submitted: 'river' }),
    ).toBeNull();
  });
});
