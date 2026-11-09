import { useState } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { appendSuggestion, SuggestionInput } from '../src/components/SuggestionInput';
import { queryClient } from '../src/api';
import { number } from '../src/data';

afterEach(() => vi.unstubAllGlobals());
function Field({ kind = 'books' }: { kind?: string }) {
  const [value, setValue] = useState('');
  return (
    <form>
      <SuggestionInput
        id="example"
        name="book"
        label="Book"
        kind={kind}
        value={value}
        onChange={setValue}
      />
    </form>
  );
}
function start(kind?: string) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: queryClient.getDefaultOptions() })}
    >
      <Field kind={kind} />
    </QueryClientProvider>,
  );
}

it('preserves printed commas, duplicates, blank lines and existing whitespace when adding names', () => {
  const original = 'Levine, Amy-Jill\n\nMarc Zvi Brettler\n';
  expect(appendSuggestion(original, '  Gale, Aaron M. ')).toBe(original + 'Gale, Aaron M.');
  expect(appendSuggestion('A. Writer\nB. Writer', 'A. Writer')).toBe(
    'A. Writer\nB. Writer\nA. Writer',
  );
  expect(appendSuggestion('name  ', 'another')).toBe('name  \nanother');
  expect(() => appendSuggestion('abc', 'de', 5)).toThrow('field is full');
  expect(appendSuggestion('abc', 'd', 5)).toBe('abc\nd');
});

it('submits a selected book ID while displaying its title, and restores free text after editing', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            options: [{ value: 'work-1', label: 'A book', detail: 'Jane Doe' }],
            total: 1,
            more: false,
          }),
        ),
    ),
  );
  const { container } = start();
  const user = userEvent.setup();
  const input = screen.getByRole('combobox', { name: 'Book' });
  await user.click(input);
  await user.type(input, 'A');
  await user.click(await screen.findByRole('option', { name: /A book/ }));
  expect(input).toHaveValue('A book');
  expect(new FormData(container.querySelector('form')!).get('book')).toBe('work-1');
  await user.clear(input);
  await user.type(input, 'Unlisted title');
  expect(new FormData(container.querySelector('form')!).get('book')).toBe('Unlisted title');
});

it('ignores an obsolete response and never turns a hostile label into markup', async () => {
  let finishOld: ((response: Response) => void) | undefined;
  const hostile = '<img src=x onerror=alert(1)>';
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) => {
      if (new URL(path, 'http://localhost').searchParams.get('q') === 'old')
        return new Promise<Response>((resolve) => {
          finishOld = resolve;
        });
      return Promise.resolve(
        new Response(
          JSON.stringify({
            options: [{ value: 'new', label: hostile, detail: '' }],
            total: 1,
            more: false,
          }),
        ),
      );
    }),
  );
  const { container } = start('subjects');
  const user = userEvent.setup();
  const input = screen.getByRole('combobox');
  await user.type(input, 'old');
  await waitFor(() => expect(finishOld).toBeDefined());
  await user.clear(input);
  await user.type(input, 'new');
  await screen.findByRole('option', { name: hostile });
  await act(async () =>
    finishOld?.(
      new Response(
        JSON.stringify({
          options: [{ value: 'old', label: 'Obsolete', detail: '' }],
          total: 1,
          more: false,
        }),
      ),
    ),
  );
  expect(screen.queryByRole('option', { name: 'Obsolete' })).toBeNull();
  expect(container.querySelector('img')).toBeNull();
});

it('displays backend decimal spending values without treating them as zero', () => {
  expect(number('0.025')).toBe(0.025);
  expect(number('25.00')).toBe(25);
  expect(number('not a cost', -1)).toBe(-1);
});
