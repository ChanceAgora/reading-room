import { createElement, Fragment, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

export type DataRecord = Record<string, unknown>;
export type SourceRange = { block_id: string; start: number; end: number };
export const record = (value: unknown): DataRecord =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as DataRecord) : {};
export const array = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
export const text = (value: unknown, fallback = ''): string =>
  typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
export const number = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;
export const humanize = (value: unknown): string => text(value).replaceAll('_', ' ');
export const encode = (value: unknown): string => encodeURIComponent(text(value));

/** Browser offsets use UTF-16; durable source coordinates use Unicode code points. */
export function codepointOffset(value: string, utf16Offset: number): number {
  return Array.from(value.slice(0, utf16Offset)).length;
}

export function sourceRanges(range: Range, root: HTMLElement): SourceRange[] {
  const sourceElement = (node: Node): Element | null =>
    (node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement)?.closest(
      '[data-source-text]',
    ) ?? null;
  const first = sourceElement(range.startContainer);
  const last = sourceElement(range.endContainer);
  if (!first || !last || !root.contains(first) || !root.contains(last)) {
    throw new Error('Begin and end the highlight within the source text.');
  }
  const elements = Array.from(root.querySelectorAll('[data-source-text]'));
  const startIndex = elements.indexOf(first);
  const endIndex = elements.indexOf(last);
  if (startIndex < 0 || endIndex < startIndex)
    throw new Error('Select one continuous range of source text.');
  const prefixOffset = (element: Element, container: Node, offset: number) => {
    const prefix = element.ownerDocument.createRange();
    prefix.selectNodeContents(element);
    prefix.setEnd(container, offset);
    return Array.from(prefix.toString()).length;
  };
  return elements
    .slice(startIndex, endIndex + 1)
    .map((element) => {
      const block = element.closest<HTMLElement>('[data-source-block]');
      if (!block?.dataset.sourceBlock)
        throw new Error('This text has no supported source coordinates.');
      const base = Number(block.dataset.sourceStart || 0);
      const start =
        element === first ? prefixOffset(element, range.startContainer, range.startOffset) : 0;
      const end =
        element === last
          ? prefixOffset(element, range.endContainer, range.endOffset)
          : Array.from(element.textContent ?? '').length;
      return { block_id: block.dataset.sourceBlock, start: base + start, end: base + end };
    })
    .filter((item) => item.end > item.start);
}

export function markedText(value: string, block: DataRecord, ranges: SourceRange[]): ReactNode {
  const chars = Array.from(value);
  const base = number(block.source_char_start);
  const spans = ranges
    .filter((range) => range.block_id === block.id)
    .map((range) => ({
      start: Math.max(0, range.start - base),
      end: Math.min(chars.length, range.end - base),
    }))
    .filter((range) => range.end > range.start)
    .sort((a, b) => a.start - b.start);
  if (!spans.length) return value;
  const merged: { start: number; end: number }[] = [];
  for (const span of spans) {
    const previous = merged.at(-1);
    if (previous && span.start <= previous.end) previous.end = Math.max(previous.end, span.end);
    else merged.push({ ...span });
  }
  const result: ReactNode[] = [];
  let cursor = 0;
  for (const [index, span] of merged.entries()) {
    result.push(chars.slice(cursor, span.start).join(''));
    result.push(<mark key={index}>{chars.slice(span.start, span.end).join('')}</mark>);
    cursor = span.end;
  }
  result.push(chars.slice(cursor).join(''));
  return result;
}

function SourceTable({ block }: { block: DataRecord }) {
  return (
    <>
      <div
        className="source-table-region"
        role="region"
        aria-label={`Source table at ${text(block.location)}`}
        tabIndex={0}
      >
        <table className="source-table">
          <caption>Source table · {text(block.location)}</caption>
          <tbody>
            {array(block.table_rows).map((row, i) => (
              <tr key={i}>
                {array(row).map((value, j) => {
                  const cell = record(value);
                  return createElement(
                    cell.is_header ? 'th' : 'td',
                    {
                      key: j,
                      colSpan: Math.max(1, Math.min(100, number(cell.colspan, 1))),
                      rowSpan: Math.max(1, Math.min(100, number(cell.rowspan, 1))),
                    },
                    text(cell.text),
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {block.table_truncated === true && (
        <p className="notice">
          This table exceeds the display limit. Consult the original local copy for the complete
          table.
        </p>
      )}
    </>
  );
}

function SourceBlock({
  block,
  unit,
  ranges,
  showLocation,
  showAttribution,
  showSegment,
}: {
  block: DataRecord;
  unit?: DataRecord;
  ranges: SourceRange[];
  showLocation: boolean;
  showAttribution: boolean;
  showSegment: boolean;
}) {
  const content = markedText(text(block.text), block, ranges);
  const kind = text(block.kind);
  const depth = Math.max(2, number(block.heading_depth, 2));
  const heading =
    depth <= 6 ? (
      createElement(`h${depth}`, {}, <span data-source-text>{content}</span>)
    ) : (
      <div role="heading" aria-level={depth}>
        <span data-source-text>{content}</span>
      </div>
    );
  const unitId = encode(unit?.id);
  return (
    <div
      id={text(block.id) || undefined}
      className={`passage-block${unit ? ' unit-block' : ''}${block.selected ? ' selected-passage' : ''}`}
      tabIndex={unit ? -1 : undefined}
      data-source-block={unit ? text(block.id) : undefined}
      data-source-start={unit ? number(block.source_char_start) : undefined}
      data-source-end={
        unit ? number(block.source_char_end, Array.from(text(block.text)).length) : undefined
      }
      data-source-length={
        unit ? number(block.source_length, Array.from(text(block.text)).length) : undefined
      }
    >
      {showSegment && (
        <p className="passage-marker">
          {humanize(block.text_type)} ·{' '}
          <Link to={`/cite/${encode(block.passage_id)}?segment=${encode(block.segment_id)}`}>
            Cite this portion
          </Link>
        </p>
      )}
      {showLocation && <p className="block-location">{text(block.location)}</p>}
      {showAttribution && <p className="attribution">{text(block.attribution)}</p>}
      {!unit && kind === 'note' && <p className="passage-marker">Source note</p>}
      {!unit && array(block.table_rows).length > 0 ? (
        <SourceTable block={block} />
      ) : ['heading', 'title'].includes(kind) ? (
        heading
      ) : unit && kind === 'table' ? (
        <pre className="source-text source-table-text" data-source-text>
          {content}
        </pre>
      ) : text(block.text) ? (
        <p className="source-text" data-source-text={unit ? '' : undefined}>
          {content}
        </p>
      ) : null}
      {array(block.note_links).length > 0 ? (
        <p className="source-note-links">
          {array(block.note_links).map((value, i) => {
            const link = record(value);
            return (
              <Fragment key={i}>
                {i > 0 && ' · '}
                <Link
                  to={`/units/${unitId}?anchor=${encode(link.target_block_id)}#${encode(link.target_block_id)}`}
                >
                  Source note {text(link.label, String(i + 1))}
                </Link>
              </Fragment>
            );
          })}
        </p>
      ) : (
        array(block.note_refs).length > 0 && (
          <details className="source-references">
            <summary>{unit ? 'Source note references' : 'Note references in this passage'}</summary>
            <ul>
              {array(block.note_refs).map((value, i) => {
                const note = record(value);
                return (
                  <li key={i}>
                    {text(note.label) || humanize(note.type) || 'Note'} {text(note.id)}
                    {unit
                      ? ' — ownership or location requires source review.'
                      : text(record(note.target).member)
                        ? ` — ${text(record(note.target).member)}`
                        : ''}
                  </li>
                );
              })}
            </ul>
            {!unit && (
              <p className="hint">
                These identify notes in the source copy; a note may fall outside the surrounding
                passages shown here.
              </p>
            )}
          </details>
        )
      )}
      {array(block.backlinks).length > 0 && (
        <p className="source-note-links">
          {array(block.backlinks).map((backlink, i) => (
            <Fragment key={i}>
              {i > 0 && ' · '}
              <Link to={`/units/${unitId}?anchor=${encode(backlink)}#${encode(backlink)}`}>
                Return to reference{array(block.backlinks).length > 1 ? ` ${i + 1}` : ''}
              </Link>
            </Fragment>
          ))}
        </p>
      )}
      {array(block.image_refs).length > 0 && (
        <div className="source-references">
          <ul>
            {array(block.image_refs).map((member, i) => (
              <li key={i}>
                {block.file_id ? (
                  <Link to={`/illustration/${encode(block.file_id)}?member=${encode(member)}`}>
                    Open source illustration {i + 1}
                  </Link>
                ) : (
                  <>Illustration {i + 1} — consult the original source copy.</>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function SourceBlocks({
  blocks,
  unit,
  attribution = '',
  ranges = [],
}: {
  blocks: unknown;
  unit?: DataRecord;
  attribution?: string;
  ranges?: SourceRange[];
}) {
  let previousLocation = '';
  let previousAttribution = attribution || text(unit?.attribution);
  let previousSegment = '';
  let matchedSeen = false;
  const groups: { selected: boolean; content: ReactNode[] }[] = [];
  for (const [index, value] of array(blocks).entries()) {
    const block = record(value);
    const selected = Boolean(block.selected);
    const content = (
      <SourceBlock
        key={text(block.id, String(index))}
        block={block}
        unit={unit}
        ranges={ranges}
        showLocation={Boolean(block.location && block.location !== previousLocation)}
        showAttribution={Boolean(block.attribution && block.attribution !== previousAttribution)}
        showSegment={!unit && Boolean(block.segment_id && block.segment_id !== previousSegment)}
      />
    );
    previousLocation = text(block.location);
    previousAttribution = text(block.attribution);
    previousSegment = text(block.segment_id);
    const previous = groups.at(-1);
    if (previous?.selected === selected) previous.content.push(content);
    else groups.push({ selected, content: [content] });
  }
  return (
    <>
      {groups.map((group, i) => {
        if (!unit && group.selected && !matchedSeen) {
          matchedSeen = true;
          return (
            <section
              key={i}
              id="selected-passage"
              tabIndex={-1}
              aria-labelledby="matched-passage-label"
            >
              <p className="passage-marker" id="matched-passage-label">
                Matched passage
              </p>
              {group.content}
            </section>
          );
        }
        return <Fragment key={i}>{group.content}</Fragment>;
      })}
    </>
  );
}
