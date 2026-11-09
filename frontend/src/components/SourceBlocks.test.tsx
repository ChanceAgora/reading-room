import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { SourceBlocks, codepointOffset, sourceRanges } from './SourceBlocks';

describe('source text and durable coordinates', () => {
  it('keeps source markup inert and announces consecutive matched poetry only once', () => {
    const blocks = [
      {
        id: 'b1',
        selected: true,
        kind: 'paragraph',
        text: '<img src="https://example.invalid/tracker" onerror="alert(1)">',
        location: 'Page 10',
        attribution: 'Poem by C. Poet',
      },
      {
        id: 'b2',
        selected: true,
        kind: 'paragraph',
        text: 'A second line\nwith its own break.',
        location: 'Page 10',
        attribution: 'Poem by C. Poet',
      },
      {
        id: 'b3',
        selected: false,
        kind: 'paragraph',
        text: 'Following source.',
        location: 'Page 11',
        attribution: 'Another contributor',
      },
    ];
    const { container } = render(
      <MemoryRouter>
        <SourceBlocks blocks={blocks} attribution="Volume editor" />
      </MemoryRouter>,
    );
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(blocks[0].text)).toBeVisible();
    expect(screen.getAllByText('Page 10')).toHaveLength(1);
    expect(screen.getAllByText('Poem by C. Poet')).toHaveLength(1);
    expect(screen.getAllByText('Matched passage')).toHaveLength(1);
    expect(
      container.querySelector('#selected-passage')?.querySelectorAll('.passage-block'),
    ).toHaveLength(2);
    expect(container.querySelector('#b2 .source-text')?.textContent).toBe(blocks[1].text);
    expect(screen.getByText('Another contributor')).toBeVisible();
  });

  it('captures astral characters and partial source windows by code point, including nested marks', () => {
    const { container } = render(
      <MemoryRouter>
        <article>
          <SourceBlocks
            unit={{ id: 'u1' }}
            blocks={[
              { id: 'b1', text: 'A😀BC', source_char_start: 20, source_char_end: 24 },
              { id: 'b2', text: 'DéF', source_char_start: 0, source_char_end: 3 },
            ]}
            ranges={[{ block_id: 'b1', start: 21, end: 22 }]}
          />
        </article>
      </MemoryRouter>,
    );
    const root = container.querySelector('article')!;
    const first = root.querySelector('#b1 mark')!.firstChild!;
    const last = root.querySelector('#b2 [data-source-text]')!.firstChild!;
    const range = document.createRange();
    range.setStart(first, 0);
    range.setEnd(last, 2);
    expect(sourceRanges(range, root)).toEqual([
      { block_id: 'b1', start: 21, end: 24 },
      { block_id: 'b2', start: 0, end: 2 },
    ]);
    expect(codepointOffset('A😀BC', 3)).toBe(2);
  });

  it('rejects a selection that begins in descriptive metadata', () => {
    const { container } = render(
      <MemoryRouter>
        <article>
          <SourceBlocks
            unit={{ id: 'u1' }}
            blocks={[{ id: 'b1', location: 'Page 1', text: 'Source words' }]}
          />
        </article>
      </MemoryRouter>,
    );
    const root = container.querySelector('article')!;
    const range = document.createRange();
    range.setStart(root.querySelector('.block-location')!.firstChild!, 0);
    range.setEnd(root.querySelector('[data-source-text]')!.firstChild!, 5);
    expect(() => sourceRanges(range, root)).toThrow(
      'Begin and end the highlight within the source text.',
    );
  });

  it('retains note return links and safe structured table cells', () => {
    const { container } = render(
      <MemoryRouter>
        <SourceBlocks
          blocks={[
            {
              id: 'table',
              kind: 'table',
              location: 'Page 5',
              table_rows: [
                [{ text: '<script>no()</script>', is_header: true, colspan: 1, rowspan: 1 }],
              ],
              table_truncated: true,
            },
          ]}
        />
        <SourceBlocks
          unit={{ id: 'unit:1' }}
          blocks={[{ id: 'n1', kind: 'note', text: 'Note text.', backlinks: ['source:1'] }]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole('columnheader')).toHaveTextContent('<script>no()</script>');
    expect(container.querySelector('script')).toBeNull();
    expect(screen.getByRole('link', { name: 'Return to reference' })).toHaveAttribute(
      'href',
      '/units/unit%3A1?anchor=source%3A1#source%3A1',
    );
    expect(screen.getByText(/table exceeds the display limit/)).toBeVisible();
  });
});
