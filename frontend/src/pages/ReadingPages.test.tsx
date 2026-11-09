import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { pageKey } from '../api';
import { BookPage, CitationPage, SelectionPage, UnitPage, citationMarkup } from './ReadingPages';

function view(
  path: string,
  page: string,
  data: Record<string, unknown>,
  component: React.ReactNode,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
  client.setQueryData(pageKey(path), { page, title: 'Test source', nav: 'books', data });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{component}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  if (!globalThis.CSS?.escape)
    vi.stubGlobal('CSS', {
      ...globalThis.CSS,
      escape: (value: string) => value.replaceAll(':', '\\:'),
    });
});

describe('citation formatting trust boundary', () => {
  it('keeps emphasis while rejecting attributes, links, scripts and external resources', () => {
    const { container } = render(
      <div>
        {citationMarkup(
          'A &amp; B, <em>Book &lt;One&gt;</em>. <img src="https://example.invalid/pixel"><script>alert(1)</script><a href="javascript:bad()">Words</a>',
        )}
      </div>,
    );
    expect(container.querySelector('em')).toHaveTextContent('Book <One>');
    expect(container.querySelector('img, script, a')).toBeNull();
    expect(container).toHaveTextContent('A & B, Book <One>. Words');
    expect(container).not.toHaveTextContent('alert(1)');
  });

  it('decodes source punctuation without interpreting it as markup', () => {
    render(<div>{citationMarkup('&#x1F600; &#39;quoted&#39; &lt;em&gt;literal&lt;/em&gt;')}</div>);
    expect(screen.getByText("😀 'quoted' <em>literal</em>")).toBeVisible();
  });
});

describe('reading page behavior carried forward from server-rendered markup', () => {
  const work = {
    id: 'w1',
    title: 'An anthology',
    author: 'Volume editor',
    files: [],
    profile: {},
    sections: [],
  };
  const nodes = [
    {
      id: 'day',
      title: 'Proper 17',
      depth: 1,
      children: [
        {
          id: 'reading',
          title: 'Jeremiah 15:15–21',
          depth: 2,
          children: [
            {
              id: 'essay',
              title: 'Theological Perspective',
              depth: 3,
              unit_id: 'u1',
              attribution: 'B. Writer',
              attribution_verified: true,
              children: [],
            },
          ],
        },
      ],
    },
  ];

  it('renders nested disclosures with verified credits and remembers expansion', async () => {
    const user = userEvent.setup();
    const { container } = view(
      '/books/w1',
      'book',
      { work, outline: { nodes, offset: 0, next_offset: null, previous_offset: null } },
      <BookPage />,
    );
    const top = screen.getByRole('button', { name: 'Proper 17' });
    const child = screen.getByRole('button', { name: 'Jeremiah 15:15–21' });
    expect(top).toHaveAttribute('aria-expanded', 'true');
    expect(child).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('link', { name: 'Theological Perspective' })).toBeNull();
    await user.click(child);
    expect(screen.getByRole('link', { name: 'Theological Perspective' })).toHaveAttribute(
      'href',
      '/units/u1',
    );
    expect(screen.getByText('B. Writer')).toBeVisible();
    expect(screen.getByRole('heading', { level: 5 })).toHaveTextContent('Theological Perspective');
    for (const button of container.querySelectorAll('[aria-controls]'))
      expect(document.getElementById(button.getAttribute('aria-controls')!)).not.toBeNull();
    const ids = Array.from(container.querySelectorAll('[id]'), (element) => element.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(container.querySelector('[role="tree"]')).toBeNull();
    expect(
      JSON.parse(sessionStorage.getItem('reading-room:outline:w1:0')!).open['outline-reading'],
    ).toBe(true);
  });

  it('restores the link focus and expanded outline on return from a unit', () => {
    sessionStorage.setItem(
      'reading-room:outline:w1:0',
      JSON.stringify({
        open: { 'outline-day': true, 'outline-reading': true },
        returning: true,
        focus: 'essay',
      }),
    );
    view('/books/w1', 'book', { work, outline: { nodes, offset: 0 } }, <BookPage />);
    expect(screen.getByRole('link', { name: 'Theological Perspective' })).toHaveFocus();
    expect(JSON.parse(sessionStorage.getItem('reading-room:outline:w1:0')!).returning).toBe(false);
  });

  it('groups structural findings with bounded examples and treats source labels as text', () => {
    const issues: unknown[] = Array.from({ length: 415 }, (_, i) => ({
      code: 'navigation',
      message: 'Navigation target needs review.',
      label: i === 0 ? '<script>source label</script>' : `Source heading ${i}`,
    }));
    issues.push(
      ...Array.from({ length: 312 }, () => ({
        code: 'ancestry',
        message: 'Parent heading is unresolved.',
      })),
      'An unclassified boundary.',
      'An unclassified boundary.',
      { code: 'different_evidence', message: 'Navigation target needs review.' },
    );
    const { container } = view(
      '/books/w1',
      'book',
      { work, outline: { nodes: [], offset: 0, report: { status: 'needs_review', issues } } },
      <BookPage />,
    );
    const groups = container.querySelector('.structural-issues')!;
    expect(groups.children).toHaveLength(4);
    expect(groups).toHaveTextContent('(415 occurrences)');
    expect(groups).toHaveTextContent('(312 occurrences)');
    expect(groups).toHaveTextContent('(2 occurrences)');
    expect(groups).toHaveTextContent('Source heading 2');
    expect(groups).not.toHaveTextContent('Source heading 3');
    expect(groups).toHaveTextContent('and others');
    expect(groups).toHaveTextContent('<script>source label</script>');
    expect(groups.querySelector('script')).toBeNull();
  });

  it('retains selected source words without offering citation or use actions after a source change', () => {
    const { container } = view(
      '/selections/s1?action=record',
      'selection',
      {
        action: 'record',
        selection: {
          id: 's1',
          unit_id: 'u1',
          work_id: 'w1',
          title: 'A quotation',
          quotation: '🌿 luminous',
          available: false,
          error: 'The source changed.',
        },
      },
      <SelectionPage />,
    );
    expect(screen.getByText('🌿 luminous')).toBeVisible();
    expect(screen.getByText(/The source changed/)).toBeVisible();
    expect(screen.queryByRole('link', { name: /Confirm selection/ })).toBeNull();
    expect(container.querySelector('form')).toBeNull();
  });

  it('renders unit scope separately from exact selection controls and preserves source note navigation', () => {
    const { container } = view(
      '/units/u1',
      'unit',
      {
        reading: {
          unit: { id: 'u1', title: 'An essay', attribution: 'B. Writer' },
          work,
          blocks: [
            {
              id: 'b1',
              text: 'A 🌿 luminous thought.',
              kind: 'paragraph',
              role: 'body',
              note_links: [{ target_block_id: 'n1', label: '1' }],
            },
            { id: 'n1', text: 'A source note.', kind: 'note', role: 'note', backlinks: ['b1'] },
          ],
        },
      },
      <UnitPage />,
    );
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Source note 1' })).toHaveAttribute(
      'href',
      '/units/u1?anchor=n1#n1',
    );
    expect(screen.getByRole('link', { name: 'Return to reference' })).toHaveAttribute(
      'href',
      '/units/u1?anchor=b1#b1',
    );
    expect(screen.getByRole('button', { name: 'Cite selected text' })).toBeDisabled();
    expect(container.querySelector('form[action="/selections"] input[name="scope"]')).toBeNull();
    expect(container.querySelector('#research-record input[name="scope"]')).toHaveValue('unit');
  });

  it('provides labeled readonly citation formats, rich emphasis, locator controls and all export formats', () => {
    const citation = {
      full_note: 'Jane Doe, A Book, 42.',
      short_note: 'Doe, Book, 42.',
      bibliography: 'Doe, Jane. A Book.',
      html: { full_note: 'Jane Doe, <i>A Book</i>, 42.' },
      needs_review: false,
      warnings: [],
      contribution_target_id: 'section1',
    };
    const { container } = view(
      '/cite/p1',
      'citation',
      {
        passage: { id: 'p1', work_id: 'w1', title: 'A Book' },
        citation,
        locator: { type: 'page', value: '42', verified: true, evidence: 'Printed page.' },
      },
      <CitationPage />,
    );
    for (const [label, value] of [
      ['Full footnote or endnote', citation.full_note],
      ['Shortened note', citation.short_note],
      ['Bibliography entry', citation.bibliography],
    ]) {
      const control = screen.getByRole('textbox', { name: `${label} — selectable text` });
      expect(control).toHaveAttribute('readonly');
      expect(control).toHaveValue(value);
      expect(screen.getByRole('button', { name: `Copy ${label.toLowerCase()}` })).toHaveAttribute(
        'type',
        'button',
      );
    }
    expect(container.querySelector('.citation-preview i')).toHaveTextContent('A Book');
    expect(
      screen.getByRole('checkbox', { name: 'I checked this locator against the source.' }),
    ).toBeChecked();
    expect(
      within(screen.getByRole('combobox', { name: 'Export this citation' }))
        .getAllByRole('option')
        .map((option) => option.getAttribute('value')),
    ).toEqual(['txt', 'md', 'json']);
    for (const control of container.querySelectorAll('input:not([type="hidden"]),textarea,select'))
      expect(control).toHaveAccessibleName();
    expect(container.querySelector('[tabindex="1"]')).toBeNull();
  });
});
