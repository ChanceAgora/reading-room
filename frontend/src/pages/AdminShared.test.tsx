import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, Link, RouterProvider, useParams } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { UiPage } from '../api';
import { useAdminPage } from './AdminShared';

const page: UiPage = {
  page: 'focuses',
  title: 'Research focuses',
  nav: 'focus',
  data: { focuses: [] },
};

function Editor() {
  const state = useAdminPage();
  const { id } = useParams();
  return (
    <>
      <h1>Editor {id}</h1>
      <button
        disabled={state.busy}
        onClick={() => void state.action(`/focus/${id}`, { name: 'Saved focus' })}
      >
        Save focus
      </button>
      <Link to="/shelves">The shelves</Link>
      <Link to="/editor/second">Another editor</Link>
    </>
  );
}

function setup() {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === '/api/ui/bootstrap') return Response.json({ csrf: 'test-token' });
    if (init?.method === 'POST')
      return new Promise<Response>((resolve) => {
        finish = resolve;
      });
    return Response.json(page);
  });
  vi.stubGlobal('fetch', fetcher);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: '/editor/:id', element: <Editor /> },
      { path: '/shelves', element: <h1>Shelves destination</h1> },
      { path: '/saved', element: <h1>Save confirmed</h1> },
    ],
    { initialEntries: ['/editor/first'] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, fetcher, finish: (response: Response) => finish(response) };
}

afterEach(() => vi.unstubAllGlobals());

describe('admin action navigation', () => {
  it('follows a successful save redirect while the originating page is open', async () => {
    const state = setup();
    fireEvent.click(screen.getByRole('button', { name: 'Save focus' }));
    await waitFor(() =>
      expect(state.fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true),
    );
    await act(async () => state.finish(Response.json({ redirect: '/saved' })));
    expect(await screen.findByRole('heading', { name: 'Save confirmed' })).toBeInTheDocument();
  });

  it.each([
    ['The shelves', '/shelves', 'Shelves destination'],
    ['Another editor', '/editor/second', 'Editor second'],
  ])(
    'keeps the chosen destination after leaving for %s during a save',
    async (label, destination, heading) => {
      const state = setup();
      fireEvent.click(screen.getByRole('button', { name: 'Save focus' }));
      await waitFor(() =>
        expect(state.fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true),
      );
      fireEvent.click(screen.getByRole('link', { name: label }));
      expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
      await act(async () => state.finish(Response.json({ redirect: '/saved' })));
      expect(state.router.state.location.pathname).toBe(destination);
      expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
    },
  );
});
