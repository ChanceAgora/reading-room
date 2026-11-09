import { afterEach, expect, it, vi } from 'vitest';
import { apiGet, queryClient } from '../src/api';
afterEach(() => vi.unstubAllGlobals());
it('follows local read-only redirect envelopes without posting', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ redirect: '/review/target' })))
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ page: 'review', title: 'Review', data: {} })),
    );
  vi.stubGlobal('fetch', fetcher);
  expect(await apiGet('/review/target/draft')).toMatchObject({ page: 'review' });
  expect(fetcher.mock.calls[1][0]).toBe('/api/ui/review/target');
  expect(fetcher.mock.calls.every(([, init]) => init.method === undefined)).toBe(true);
});
it('rejects external redirect envelopes and bounds redirect loops', async () => {
  const fetcher = vi.fn(
    async () => new Response(JSON.stringify({ redirect: 'https://example.com/' })),
  );
  vi.stubGlobal('fetch', fetcher);
  await expect(apiGet('/review/target/draft')).rejects.toThrow('could not be reopened');
  fetcher.mockImplementation(
    async () => new Response(JSON.stringify({ redirect: '/review/target/draft' })),
  );
  await expect(apiGet('/review/target/draft')).rejects.toThrow('could not be reopened');
  expect(fetcher).toHaveBeenCalledTimes(7);
});
it('never schedules retries, polling, reconnect or focus refresh; localhost works offline', () => {
  expect(queryClient.getDefaultOptions().queries).toMatchObject({
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: false,
    networkMode: 'always',
  });
  expect(queryClient.getDefaultOptions().mutations).toMatchObject({
    retry: false,
    networkMode: 'always',
  });
});
