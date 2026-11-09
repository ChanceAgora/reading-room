import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useBlocker, useLocation, useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ApiError,
  apiAction,
  apiGet,
  formFields,
  pageKey,
  usePage,
  type Fields,
  type UiPage,
} from '../api';
import {
  DefinitionList,
  Message,
  PageLoading,
  SafeLink,
  humanize,
  number,
  object,
  records,
  strings,
  text,
  type JsonObject,
} from './AdminShared';

type DraftEdit = {
  action: 'draft' | 'draft-evidence';
  fields: Fields;
  sequence: number;
  proposal: boolean;
};
type ChangeEditor = (
  key: string,
  action: DraftEdit['action'],
  defaults: Fields,
  name: string,
  value: string,
  proposal?: boolean,
) => void;
type ReviewController = {
  edits: Record<string, DraftEdit>;
  change: ChangeEditor;
  save: (key: string, defaults?: DraftEdit) => Promise<void>;
  cancel: (key: string, url: string) => void;
  act: (action: string, fields?: Fields) => Promise<void>;
  busy: boolean;
};

function reviewCost(value: unknown): string {
  const amount =
    typeof value === 'number'
      ? value
      : typeof value === 'string' && value.length < 40 && /^\d+(?:\.\d+)?$/.test(value)
        ? Number(value)
        : NaN;
  return Number.isFinite(amount) && amount >= 0 ? `$${amount.toFixed(4)}` : 'an unconfirmed amount';
}

function Disclosure({
  id,
  className,
  summary,
  openWhen = false,
  children,
}: {
  id?: string;
  className?: string;
  summary: ReactNode;
  openWhen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(openWhen);
  useEffect(() => {
    if (openWhen) setOpen(true);
  }, [openWhen]);
  return (
    <details
      id={id}
      className={className}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>{summary}</summary>
      {children}
    </details>
  );
}

function Evidence({ items }: { items: unknown }) {
  return records(items).length ? (
    <ul className="review-evidence">
      {records(items).map((source, i) => (
        <li key={i}>
          {text(source.quote) ? (
            <blockquote>{text(source.quote)}</blockquote>
          ) : (
            text(source.summary) && <p>{text(source.summary)}</p>
          )}
          {text(source.href || source.url) && (
            <SafeLink href={source.href || source.url}>
              {text(source.link_label || source.title, 'Read supporting source')}
            </SafeLink>
          )}
          {text(source.relationship_label) && (
            <p className="hint">
              <strong>{text(source.relationship_label)}</strong>
              {text(source.link_help) && ` · ${text(source.link_help)}`}
            </p>
          )}
          {Boolean(source.url) && (
            <span className="hint">External evidence summary; check the linked edition.</span>
          )}
        </li>
      ))}
    </ul>
  ) : null;
}

function ValuePair({
  current,
  proposed,
  proposedLabel = 'Proposed',
}: {
  current: unknown;
  proposed: unknown;
  proposedLabel?: string;
}) {
  return (
    <dl className="review-value-list">
      <div>
        <dt>Current</dt>
        <dd>{text(current, 'Not recorded')}</dd>
      </div>
      <div>
        <dt>{proposedLabel}</dt>
        <dd>{text(proposed, 'Not recorded')}</dd>
      </div>
    </dl>
  );
}

function ActionButton({
  controller,
  action,
  fields,
  children,
  disabled = false,
  className = 'secondary',
  id,
  label,
}: {
  controller: ReviewController;
  action: string;
  fields?: Fields;
  children: ReactNode;
  disabled?: boolean;
  className?: string;
  id?: string;
  label?: string;
}) {
  return (
    <button
      type="button"
      id={id}
      className={className}
      disabled={disabled || controller.busy}
      aria-label={label}
      onClick={() => void controller.act(action, fields)}
    >
      {children}
    </button>
  );
}

function DecisionButton({
  controller,
  item,
  action,
  label,
  replace = false,
  stale = false,
}: {
  controller: ReviewController;
  item: JsonObject;
  action: string;
  label: string;
  replace?: boolean;
  stale?: boolean;
}) {
  return (
    <ActionButton
      controller={controller}
      action="decision"
      fields={{ item_id: text(item.id), decision: action, ...(replace ? { replace: 'yes' } : {}) }}
      disabled={action === 'accept' && (Boolean(item.stale) || stale)}
      id={`${text(item.id)}-${action}${replace ? '-replace' : ''}`}
      label={`${label}: ${text(item.field_label)}`}
    >
      {label}
    </ActionButton>
  );
}

function HandledRow({
  controller,
  item,
  fieldMap,
  draft,
  undo = false,
}: {
  controller: ReviewController;
  item: JsonObject;
  fieldMap: JsonObject;
  draft: JsonObject;
  undo?: boolean;
}) {
  const field = object(fieldMap[text(item.field)]),
    change = object(object(draft.changes)[text(item.field)]);
  return (
    <article className="review-handled-row" id={text(item.id)} tabIndex={-1}>
      <p>
        <strong>{text(item.field_label)}</strong> · {text(item.status_label)}
        {item.status === 'accepted' && (change.verified ? ' · Verified' : ' · Provisional')}
      </p>
      <div className="review-actions">
        <DecisionButton
          controller={controller}
          item={item}
          action={undo ? 'undo' : 'restore'}
          label={undo ? 'Undo' : 'Restore'}
        />
        {item.status === 'accepted' && (
          <a href={`#pending-${text(field.dom_id)}`}>Review accepted change</a>
        )}
      </div>
      {item.status === 'saved' && (
        <p className="hint">Restoring this item does not undo saved library information.</p>
      )}
      <Disclosure summary={`Decision details for ${text(item.field_label).toLowerCase()}`}>
        {item.kind === 'suggestion' && (
          <p>
            {item.status === 'saved' ? 'Saved' : 'Proposed'} value: {text(item.proposed_display)}
          </p>
        )}
        {item.status === 'saved' && item.edited ? (
          <p>{text(item.saved_evidence)}</p>
        ) : (
          strings(item.reasons).map((reason, i) => <p key={i}>{reason}</p>)
        )}
        {records(item.evidence_items).length > 0 && (
          <Disclosure summary="Sources from this item's earlier review">
            <p className="hint">
              Evidence from a previous review; recheck before relying on it. These sources describe
              the original suggestion or question.
            </p>
            <Evidence items={item.evidence_items} />
          </Disclosure>
        )}
      </Disclosure>
    </article>
  );
}

function FieldEditor({
  field,
  controller,
  data,
}: {
  field: JsonObject;
  controller: ReviewController;
  data: JsonObject;
}) {
  const key = `field:${text(field.key)}`,
    id = text(field.dom_id),
    kind = text(field.kind),
    fieldMap = object(data.field_map),
    target = object(data.target);
  const defaults: Fields = {
    field: text(field.key),
    value: text(field.edit_value),
    evidence: text(field.edit_evidence),
    verified: field.edit_verified ? 'yes' : '',
    ...(kind === 'names'
      ? { mode: text(field.edit_mode, 'names'), short_names: text(field.edit_shorts) }
      : {}),
    ...(field.proposal_prefill ? { proposal_item_id: text(field.proposal_prefill) } : {}),
  };
  const edit = controller.edits[key],
    values = edit?.fields ?? defaults;
  const change = (name: string, value: string) =>
    controller.change(key, 'draft', defaults, name, value, Boolean(field.proposal_prefill));
  const invalid = data.error_field === field.key;
  return (
    <article className="review-field" id={id} aria-labelledby={`${id}-heading`}>
      <h4 id={`${id}-heading`}>{text(field.question || field.label)}</h4>
      {text(field.purpose) && <p className="review-field-help">{text(field.purpose)}</p>}
      <dl className="review-value-list">
        <div>
          <dt>Current value</dt>
          <dd>{text(field.current_display, 'Not recorded')}</dd>
        </div>
        <div>
          <dt>Verification</dt>
          <dd>
            {humanize(text(field.status, 'unknown'))}
            {Boolean(field.inherited) && ' · inherited'}
          </dd>
        </div>
        <div>
          <dt>Recorded by</dt>
          <dd>{humanize(text(field.origin, 'Not recorded'))}</dd>
        </div>
      </dl>
      {Boolean(field.inherited) && (
        <p className="hint">
          Inherited from {text(field.inherited_from_label, 'the containing source')}.{' '}
          {text(field.inherited_url) && (
            <SafeLink href={field.inherited_url}>Review the inherited information</SafeLink>
          )}
        </p>
      )}
      {text(field.evidence) && (
        <Disclosure summary="Evidence for the current value">
          <p>{text(field.evidence)}</p>
        </Disclosure>
      )}
      {field.editable !== false ? (
        <Disclosure
          id={`editor-${id}`}
          className="review-editor"
          openWhen={Boolean(field.editor_open || field.unsaved)}
          summary={`Edit or verify ${text(field.label).toLowerCase()}${field.pending ? ' — draft saved' : ''}`}
        >
          <p className="review-field-help" id={`${id}-help`}>
            {text(field.help)}
          </p>
          <form
            className="editor-form"
            onSubmit={(event) => {
              event.preventDefault();
              void controller.save(key, {
                action: 'draft',
                fields: values,
                sequence: 0,
                proposal: Boolean(field.proposal_prefill),
              });
            }}
          >
            {Boolean(field.proposal_prefill) && (
              <p className="notice">
                This suggestion is shown as unsaved input. Editing it does not accept it; choose Add
                to draft when ready.
              </p>
            )}
            {kind === 'names' && (
              <>
                <label htmlFor={`${id}-mode`}>What is known about these names?</label>
                <select
                  id={`${id}-mode`}
                  name="mode"
                  value={text(values.mode)}
                  onChange={(event) => change('mode', event.target.value)}
                  aria-describedby={`${id}-names-help`}
                  aria-invalid={invalid || undefined}
                >
                  <option value="names">Use the names below</option>
                  <option value="unknown">Names are unknown</option>
                  <option value="absent">No named person in this role (explicit statement)</option>
                  {Boolean(field.allow_inherit) && (
                    <option value="inherit">Inherit the book’s translation credit</option>
                  )}
                </select>
                <p id={`${id}-names-help`} className="hint">
                  Choose “Use the names below” to apply entered names. Unknown does not mean
                  anonymous. Keep authors, editors, and translators in their own roles. Choosing “No
                  named person” requires source evidence before saving.
                </p>
              </>
            )}
            <label htmlFor={`${id}-value`}>
              {kind === 'names'
                ? 'Names as printed — one per line'
                : `Proposed ${text(field.label).toLowerCase()}`}
            </label>
            {kind === 'select' ? (
              <select
                id={`${id}-value`}
                name="value"
                value={text(values.value)}
                onChange={(event) => change('value', event.target.value)}
                aria-describedby={`${id}-help`}
                aria-invalid={invalid || undefined}
              >
                {records(field.options).map((option) => (
                  <option key={text(option.value)} value={text(option.value)}>
                    {text(option.label)}
                  </option>
                ))}
              </select>
            ) : (
              <textarea
                id={`${id}-value`}
                name="value"
                rows={kind === 'tags' || kind === 'names' ? 3 : 2}
                maxLength={6000}
                value={text(values.value)}
                onChange={(event) => change('value', event.target.value)}
                aria-describedby={`${id}-help`}
                aria-invalid={invalid || undefined}
              />
            )}
            {kind === 'names' && (
              <>
                <label htmlFor={`${id}-short`}>
                  Short or family names — corresponding lines (optional)
                </label>
                <textarea
                  id={`${id}-short`}
                  name="short_names"
                  rows={2}
                  maxLength={3000}
                  value={text(values.short_names)}
                  onChange={(event) => change('short_names', event.target.value)}
                />
              </>
            )}
            {kind === 'tags' && (
              <p className="hint">One value per line. This replaces this list only.</p>
            )}
            {text(field.example) && <p className="hint">For example: {text(field.example)}</p>}
            {field.key === 'text_type' && (
              <Disclosure summary="Help me choose a kind of writing">
                <p>
                  Choose the most useful specific description. Use ordinary prose when nothing more
                  specific fits. Use Mixed only when the text itself contains several kinds of
                  writing. Headings alone do not make it mixed.
                </p>
                <dl>
                  {records(field.options).map((option) => (
                    <div key={text(option.value)}>
                      <dt>{text(option.label)}</dt>
                      <dd>
                        {text(option.definition)}
                        {text(option.example) && (
                          <p className="hint">For example: {text(option.example)}</p>
                        )}
                      </dd>
                    </div>
                  ))}
                </dl>
              </Disclosure>
            )}
            <label htmlFor={`${id}-evidence`}>Source evidence or reason for this change</label>
            <textarea
              id={`${id}-evidence`}
              name="evidence"
              rows={2}
              maxLength={4000}
              value={text(values.evidence)}
              onChange={(event) => change('evidence', event.target.value)}
              aria-invalid={invalid || undefined}
            />
            <p className="hint">
              Name the source and location, or explain your classification. You can finish this
              later in your local draft; evidence is required when applying a correction.
            </p>
            <label className="checkbox-label" htmlFor={`${id}-verified`}>
              <input
                id={`${id}-verified`}
                name="verified"
                type="checkbox"
                checked={values.verified === 'yes'}
                onChange={(event) => change('verified', event.target.checked ? 'yes' : '')}
              />{' '}
              I verified this field against the evidence.
            </label>
            {Boolean(field.unsaved) && (
              <p className="notice">
                This field contains your unsaved input. Resolve the message above and save the draft
                again.
              </p>
            )}
            <button className="secondary" type="submit">
              {field.proposal_prefill
                ? 'Add to draft'
                : field.pending
                  ? 'Update draft'
                  : 'Add to draft'}
            </button>
            {Boolean(field.proposal_prefill) && (
              <button
                type="button"
                className="secondary"
                onClick={() => controller.cancel(key, text(data.guided_view_url))}
              >
                Cancel suggestion edit
              </button>
            )}
          </form>
          {strings(field.related_fields).length > 0 && (
            <p className="review-related">
              Related information:{' '}
              {strings(field.related_fields).map((related) => {
                const linked = object(fieldMap[related]);
                return (
                  <span key={related}>
                    <SafeLink href={linked.review_edit_url}>{text(linked.label)}</SafeLink>
                    {' · '}
                  </span>
                );
              })}
              Each field has its own scope and evidence; review related changes separately.
            </p>
          )}
          {Boolean(field.pending) &&
            ['title', 'bibliography.title'].includes(text(field.key)) &&
            (() => {
              const related = field.key === 'title' ? 'bibliography.title' : 'title';
              return fieldMap[related] ? (
                <ActionButton
                  controller={controller}
                  action="linked-title"
                  fields={{ source_field: text(field.key), field: related }}
                >
                  Also draft this value as {text(object(fieldMap[related]).label).toLowerCase()}
                </ActionButton>
              ) : null;
            })()}
        </Disclosure>
      ) : (
        <p className="hint">
          Edit this information on{' '}
          <Link to={`/review/${encodeURIComponent(text(target.work_id))}`}>
            the book’s review page
          </Link>
          .
        </p>
      )}
    </article>
  );
}

function PendingEvidence({ item, controller }: { item: JsonObject; controller: ReviewController }) {
  const field = object(item.field),
    change = object(item.change),
    key = `evidence:${text(field.key)}`,
    id = text(field.dom_id);
  const defaults = {
    count: '1',
    field_0: text(field.key),
    evidence_0: text(change.evidence),
    verified_0: change.verified ? 'yes' : '',
  };
  const values = controller.edits[key]?.fields ?? defaults;
  return (
    <form
      className="editor-form"
      onSubmit={(event) => {
        event.preventDefault();
        void controller.save(key, {
          action: 'draft-evidence',
          fields: values,
          sequence: 0,
          proposal: false,
        });
      }}
    >
      <label htmlFor={`evidence-${id}`}>Evidence for {text(field.label).toLowerCase()}</label>
      <textarea
        id={`evidence-${id}`}
        name="evidence_0"
        rows={2}
        maxLength={4000}
        value={text(values.evidence_0)}
        onChange={(event) =>
          controller.change(key, 'draft-evidence', defaults, 'evidence_0', event.target.value)
        }
      />
      <label className="checkbox-label" htmlFor={`verified-${id}`}>
        <input
          id={`verified-${id}`}
          type="checkbox"
          checked={values.verified_0 === 'yes'}
          onChange={(event) =>
            controller.change(
              key,
              'draft-evidence',
              defaults,
              'verified_0',
              event.target.checked ? 'yes' : '',
            )
          }
        />{' '}
        I verified this field against the evidence.
      </label>
      <button type="submit" className="secondary">
        Save evidence and verification
      </button>
    </form>
  );
}

function PendingChanges({ data, controller }: { data: JsonObject; controller: ReviewController }) {
  const pending = records(data.pending),
    draft = object(data.draft),
    fieldMap = object(data.field_map);
  const applyFields: Fields = { request_id: text(data.request_id), count: String(pending.length) };
  pending.forEach((item, i) => {
    applyFields[`field_${i}`] = text(object(item.field).key);
    applyFields[`selected_${i}`] = 'yes';
  });
  return (
    <section
      id="pending-review"
      className="review-pending"
      aria-labelledby="pending-heading"
      tabIndex={-1}
    >
      <Disclosure
        className="review-save-summary"
        summary={`Changes ready to save (${pending.length})`}
        openWhen={Boolean(data.summary_open)}
      >
        <h2 id="pending-heading" tabIndex={-1}>
          Review and save your changes
        </h2>
        {pending.length ? (
          <>
            <p className="hint">
              These choices are saved in your draft. Save changes will apply them to the library.
              Provisional means you have not personally verified the evidence.
            </p>
            {pending.map((item) => {
              const field = object(item.field),
                change = object(item.change);
              return (
                <article
                  className="review-accepted"
                  id={`pending-${text(field.dom_id)}`}
                  key={text(field.key)}
                >
                  <h3>
                    {text(field.label)}{' '}
                    <span className="review-state">
                      {change.verified ? 'Verified' : 'Provisional'}
                    </span>
                  </h3>
                  <ValuePair
                    current={field.current_display}
                    proposed={item.proposed_display}
                    proposedLabel="Accepted"
                  />
                  <div className="review-actions">
                    <SafeLink href={field.review_edit_url}>
                      Edit {text(field.label).toLowerCase()}
                    </SafeLink>
                    <ActionButton
                      controller={controller}
                      action="draft"
                      fields={{ field: text(field.key), operation: 'remove' }}
                      label={`Remove accepted change: ${text(field.label)}`}
                    >
                      Remove
                    </ActionButton>
                  </div>
                  <Disclosure
                    id={`verification-${text(field.dom_id)}`}
                    summary={`Evidence and verification for ${text(field.label).toLowerCase()}`}
                    openWhen={Boolean(data.error && !change.evidence)}
                  >
                    {Boolean(object(item.item).edited) && (
                      <p className="hint">
                        These source excerpts belong to the original suggestion. Verify your edited
                        value separately.
                      </p>
                    )}
                    <Evidence items={item.evidence_items} />
                    <PendingEvidence item={item} controller={controller} />
                  </Disclosure>
                </article>
              );
            })}
            <ActionButton
              controller={controller}
              action="apply"
              fields={applyFields}
              disabled={Boolean(draft.stale)}
              className=""
            >
              Save changes
            </ActionButton>
            {pending
              .filter((item) =>
                ['title', 'bibliography.title'].includes(text(object(item.field).key)),
              )
              .map((item) => {
                const field = object(item.field),
                  related = field.key === 'title' ? 'bibliography.title' : 'title';
                return fieldMap[related] && !object(draft.changes)[related] ? (
                  <Disclosure key={related} summary="Related title change">
                    <p>{text(object(fieldMap[related]).help)}</p>
                    <ActionButton
                      controller={controller}
                      action="linked-title"
                      fields={{ source_field: text(field.key), field: related }}
                    >
                      Also draft this value as {text(object(fieldMap[related]).label).toLowerCase()}
                    </ActionButton>
                  </Disclosure>
                ) : null;
              })}
            <div className="review-discard">
              <ActionButton controller={controller} action="discard">
                Discard all unsaved changes
              </ActionButton>
              <p className="hint">Review decisions and saved library corrections are retained.</p>
            </div>
          </>
        ) : (
          <p className="hint">
            Nothing to save right now. Keeping information as it is can be the right outcome;
            optional improvements can wait.
          </p>
        )}
      </Disclosure>
    </section>
  );
}

function IsbnComparison({ rec, target }: { rec: JsonObject; target: JsonObject }) {
  const comparison = object(rec.comparison);
  if (!Object.keys(comparison).length || target.scope !== 'work') return null;
  const relationship =
    (
      {
        same_publication: 'The evidence identifies the same publication.',
        related_format: 'These records appear to describe related formats of the same publication.',
        different_edition: 'The records describe a different or revised edition.',
      } as Record<string, string>
    )[text(comparison.relationship)] ||
    'The relationship between these records is not yet established.';
  return (
    <section className="guided-isbn" aria-labelledby="isbn-comparison-heading">
      <h3 id="isbn-comparison-heading">The two ISBN records</h3>
      {Boolean(target.copy_format || target.source_origin) && (
        <p className="hint">
          Your imported copy: {text(target.copy_format)}
          {text(target.source_origin) && ` · ${text(target.source_origin)}`}.
        </p>
      )}
      <p>{relationship}</p>
      <div className="isbn-records">
        {records(comparison.records).map((record, i) => (
          <article className="isbn-record" key={i}>
            <h4>
              {record.isbn === comparison.recorded_isbn ? 'Your library record' : 'Compared record'}
            </h4>
            <DefinitionList
              data={{
                isbn: text(record.isbn, 'Not established'),
                format: text(record.format, 'Not established'),
                title: text(record.title, 'Not established'),
                publisher: text(record.publisher, 'Not established'),
                year: text(record.year, 'Not established'),
                edition: text(record.edition, 'Not established'),
                origin: text(record.origin, 'Source not established'),
              }}
              labels={[
                ['isbn', 'ISBN'],
                ['format', 'Format'],
                ['title', 'Title'],
                ['publisher', 'Publisher'],
                ['year', 'Publication year'],
                ['edition', 'Edition statement'],
                ['origin', 'Where this came from'],
              ]}
            />
            {records(record.source_links).map((link, j) => (
              <p key={j}>
                <SafeLink href={link.href}>{text(link.label)}</SafeLink>
              </p>
            ))}
          </article>
        ))}
      </div>
      {strings(comparison.known_differences).length > 0 && (
        <>
          <p>
            <strong>Reported differences</strong>
          </p>
          <ul>
            {strings(comparison.known_differences).map((difference, i) => (
              <li key={i}>{difference}</li>
            ))}
          </ul>
        </>
      )}
      {strings(comparison.unknowns).length > 0 && (
        <>
          <p>
            <strong>What we have not established</strong>
          </p>
          <ul>
            {strings(comparison.unknowns).map((unknown, i) => (
              <li key={i}>{unknown}</li>
            ))}
          </ul>
        </>
      )}
      {text(comparison.copy_note) && <p className="hint">{text(comparison.copy_note)}</p>}
      <p className="hint">
        Different ISBNs can identify different formats. They do not, by themselves, show that the
        text changed. An accessible export is not necessarily the commercial e-book product.
      </p>
      <p className="hint">
        External details are reported summaries; inspect the linked records to verify them.
      </p>
    </section>
  );
}

function RecommendationChoices({
  rec,
  data,
  controller,
}: {
  rec: JsonObject;
  data: JsonObject;
  controller: ReviewController;
}) {
  const fieldMap = object(data.field_map),
    preview = object(data.guided_preview),
    changes = records(rec.change_items);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void controller.act(
      'recommendation',
      formFields(event.currentTarget, (event.nativeEvent as SubmitEvent).submitter),
    );
  }
  return (
    <form onSubmit={submit} key={`${text(rec.id)}:${JSON.stringify(rec.selected_item_ids)}`}>
      <input type="hidden" name="recommendation_id" value={text(rec.id)} />
      <input type="hidden" name="decision" value="use" />
      <input type="hidden" name="selection_present" value="yes" />
      <input type="hidden" name="item_count" value={changes.length} />
      <Disclosure
        className="guided-change-details"
        summary="Preview and adjust individual changes"
        openWhen={Boolean(rec.has_conflict || rec.preview_open)}
      >
        {Boolean(rec.has_conflict) && (
          <p className="review-warning">
            You already have a different draft for part of this recommendation. Keep that work by
            leaving its replacement unchecked, or edit the existing draft below.
          </p>
        )}
        {changes.map((item, i) => (
          <fieldset className="guided-field-choice" key={text(item.id)}>
            <legend>{text(item.field_label)}</legend>
            <input type="hidden" name={`item_${i}`} value={text(item.id)} />
            <label className="checkbox-label" htmlFor={`choice-${text(item.id)}`}>
              <input
                id={`choice-${text(item.id)}`}
                type="checkbox"
                name={`selected_${i}`}
                value="yes"
                defaultChecked={strings(rec.selected_item_ids).includes(text(item.id))}
              />{' '}
              Include this change
            </label>
            <ValuePair
              current={item.current_display}
              proposed={item.proposed_display}
              proposedLabel="Recommended"
            />
            <p className="hint">
              {text(
                object(fieldMap[text(item.field)]).effect ||
                  object(fieldMap[text(item.field)]).help,
              )}
            </p>
          </fieldset>
        ))}
        <button
          type="submit"
          className="secondary"
          name="preview"
          value="yes"
          disabled={controller.busy}
        >
          Preview selected changes
        </button>
        {Boolean(rec.has_conflict) && (
          <label className="checkbox-label">
            <input type="checkbox" name="replace" value="yes" /> Replace my existing draft for any
            conflicting changes I have included.
          </label>
        )}
        {Object.keys(preview).length > 0 && (
          <div id="guided-preview" className="guided-preview" tabIndex={-1}>
            <h3>How this will look</h3>
            {Boolean(preview.display) && (
              <DefinitionList
                data={object(object(preview.display).after)}
                labels={[
                  ['title', 'Displayed title'],
                  ['credit', 'Displayed credit'],
                ]}
              />
            )}
            {Boolean(preview.citation) && (
              <>
                <h4>Citation draft</h4>
                <p className="citation-preview">
                  {text(
                    object(preview.citation).after,
                    'A complete citation preview is not available yet.',
                  )}
                </p>
                {strings(object(preview.citation).warnings).map((warning, i) => (
                  <p className="hint" key={i}>
                    {warning}
                  </p>
                ))}
              </>
            )}
            {strings(preview.limitations).map((limitation, i) => (
              <p className="hint" key={i}>
                {limitation}
              </p>
            ))}
          </div>
        )}
      </Disclosure>
      <button
        type="submit"
        id={`${text(rec.id)}-use`}
        disabled={controller.busy || Boolean(rec.stale)}
      >
        {text(rec.action_label, 'Use this recommendation')}
      </button>
      <p className="hint">
        Adds the selected changes to your draft and continues. One final Save applies them.
      </p>
    </form>
  );
}

function GuidedReview({ data, controller }: { data: JsonObject; controller: ReviewController }) {
  const rec = object(data.current_recommendation),
    target = object(data.target),
    draft = object(data.draft),
    fieldMap = object(data.field_map),
    undo = object(data.undo_recommendation);
  const recButton = (item: JsonObject, action: string, label: string) => (
    <ActionButton
      controller={controller}
      action="recommendation"
      fields={{ recommendation_id: text(item.id), decision: action }}
      disabled={Boolean(item.stale) && ['keep', 'use'].includes(action)}
      label={`${label}: ${text(item.question)}`}
    >
      {label}
    </ActionButton>
  );
  return (
    <div id="guided-review" className="guided-review">
      {Boolean(undo.id) && (
        <div className="guided-undo">
          <span>Your previous choice is saved in this review.</span>
          {recButton(undo, 'undo', 'Undo previous choice')}
        </div>
      )}
      {rec.id ? (
        <>
          <article className="guided-card">
            <p className="eyebrow">
              {rec.priority === 'optional'
                ? 'Optional improvement'
                : 'Book and citation essentials'}{' '}
              · Step {number(data.guided_position)} of {records(data.guidance).length}
            </p>
            <h2 id="guided-heading" tabIndex={-1}>
              {text(rec.question)}
            </h2>
            <p className="guided-recommendation">
              <strong>{text(rec.recommendation)}</strong>
            </p>
            {text(rec.reason_short) && (
              <p>
                <strong>Why:</strong> {text(rec.reason_short)}
              </p>
            )}
            <p className="guided-confidence">
              <strong>{text(rec.strength_label)}</strong>
              {text(rec.strength_reason_short) && ` · ${text(rec.strength_reason_short)}`}
            </p>
            <p className="hint">
              This describes the evidence supporting the recommendation. It does not mean you have
              personally verified it.
            </p>
            {text(rec.effect) && (
              <p>
                <strong>What this does:</strong> {text(rec.effect)}
              </p>
            )}
            {rec.priority === 'optional' && (
              <p className="hint">
                This is optional. You can keep reading and citing without completing this
                improvement.
              </p>
            )}
            {Boolean(rec.stale) && (
              <p className="review-warning">
                The source or recorded information has changed since this recommendation. Recheck it
                before making this choice.
              </p>
            )}
            {Boolean(rec.previous_decision) && (
              <p className="review-warning">
                New information affects your earlier choice. Please reconsider this recommendation.
              </p>
            )}
            <IsbnComparison rec={rec} target={target} />
            <Disclosure
              summary="Show me why"
              id={`why-${text(rec.id)}`}
              className="guided-explanation"
            >
              {text(rec.reason) !== text(rec.reason_short) && <p>{text(rec.reason)}</p>}
              {records(rec.field_education).map((field) => (
                <div className="guided-field-explanation" key={text(field.key)}>
                  <h3>{text(field.question || field.label)}</h3>
                  <p>{text(field.purpose || field.help)}</p>
                  {text(field.example) && (
                    <p className="hint">For example: {text(field.example)}</p>
                  )}
                </div>
              ))}
              {records(rec.change_items)
                .filter((item) => item.field === 'text_type')
                .map((item) =>
                  records(object(fieldMap.text_type).options)
                    .filter((option) => option.value === item.value)
                    .map((option) => (
                      <div key={text(option.value)}>
                        <p>
                          <strong>{text(option.label)}:</strong> {text(option.definition)}
                        </p>
                        <p className="hint">For example: {text(option.example)}</p>
                      </div>
                    )),
                )}
              {records(rec.evidence_items).length ? (
                <Evidence items={rec.evidence_items} />
              ) : records(rec.leads).length ? (
                <Evidence items={rec.leads} />
              ) : (
                <p>There is not enough source evidence for a stronger conclusion yet.</p>
              )}
            </Disclosure>
            {['pending', 'partial'].includes(text(rec.status)) ? (
              <>
                {records(rec.change_items).length ? (
                  <RecommendationChoices rec={rec} data={data} controller={controller} />
                ) : rec.has_queued_changes ? (
                  <p className="review-warning">
                    You have already drafted a change to this information.{' '}
                    <SafeLink href={data.summary_url}>Review that draft</SafeLink> before choosing
                    to keep the current value.
                  </p>
                ) : (
                  recButton(rec, text(rec.primary_action), text(rec.action_label))
                )}
                <div className="guided-secondary-actions">
                  {records(rec.field_education).length === 1
                    ? (() => {
                        const field = records(rec.field_education)[0],
                          item = records(rec.change_items)[0];
                        return (
                          <SafeLink
                            href={
                              item && !item.draft_conflict && !item.stale && !draft.stale
                                ? item.proposal_edit_url
                                : field.review_edit_url
                            }
                          >
                            Change this
                          </SafeLink>
                        );
                      })()
                    : records(rec.field_education).length > 0 && (
                        <Disclosure summary="Change this">
                          <ul>
                            {records(rec.field_education).map((field) => (
                              <li key={text(field.key)}>
                                <SafeLink href={field.review_edit_url}>
                                  Change {text(field.label).toLowerCase()}
                                </SafeLink>
                              </li>
                            ))}
                          </ul>
                        </Disclosure>
                      )}
                  {recButton(rec, 'later', 'Not now')}
                </div>
              </>
            ) : (
              <>
                <p className="notice">
                  {(
                    {
                      accepted: 'This recommendation is queued for saving.',
                      kept: 'You chose to keep the current information.',
                      later: 'You set this aside for later.',
                      saved: 'These changes have been saved.',
                      rejected: 'You declined this recommendation.',
                    } as Record<string, string>
                  )[text(rec.status)] || 'You have already considered this recommendation.'}
                </p>
                {recButton(rec, 'restore', 'Reconsider this choice')}
              </>
            )}
          </article>
          <nav className="guided-navigation" aria-label="Recommendation steps">
            {Boolean(data.guided_previous) && (
              <SafeLink href={object(data.guided_previous).url}>Back</SafeLink>
            )}
            {Boolean(data.guided_next) && object(data.guided_next).priority === rec.priority && (
              <SafeLink href={object(data.guided_next).url}>Next without deciding</SafeLink>
            )}
            <SafeLink href={data.summary_url}>Review and finish</SafeLink>
          </nav>
        </>
      ) : (
        <div className="guided-finished">
          <h2 id="guided-heading" tabIndex={-1}>
            {records(data.pending).length
              ? 'Your choices are ready to review'
              : data.has_remaining_recommendations || !draft.suggestion_status
                ? 'No changes queued'
                : 'Nothing needs changing right now'}
          </h2>
          <p>
            {records(data.pending).length
              ? 'Review the queued changes below, then save when you are ready.'
              : 'You can keep the information you have. Optional improvements and any questions left for later remain available in the overview.'}
          </p>
          {records(data.optional_guidance).filter((item) => item.status === 'pending').length >
            0 && (
            <p>
              <SafeLink
                href={
                  records(data.optional_guidance).find((item) => item.status === 'pending')?.url
                }
              >
                Explore optional improvements (
                {records(data.optional_guidance).filter((item) => item.status === 'pending').length}
                )
              </SafeLink>
              <span className="hint">
                {' '}
                — such as choosing a helpful description for this material.
              </span>
            </p>
          )}
          {!records(data.guidance).length && !draft.suggestion_status && (
            <p>
              Ask AI for a review above, or open the full information below to make a manual edit.
            </p>
          )}
        </div>
      )}
      <Disclosure
        id="review-overview"
        className="guided-overview"
        summary={`Review overview${records(data.guidance).length ? ` (${records(data.guidance).length} recommendations)` : ''}`}
      >
        {[
          ['Book and citation essentials', 'important_guidance'],
          ['Optional improvements', 'optional_guidance'],
        ].map(([title, key]) => (
          <section key={key}>
            <h3>{title}</h3>
            {records(data[key]).length ? (
              <ol>
                {records(data[key]).map((item) => (
                  <li key={text(item.id)}>
                    <SafeLink
                      href={item.url}
                      aria-current={item.id === rec.id ? 'step' : undefined}
                    >
                      {text(item.question)}
                    </SafeLink>{' '}
                    <span className="hint">
                      {(
                        {
                          pending: 'To consider',
                          partial: 'Partly considered',
                          accepted: 'Ready to save',
                          kept: 'Kept as it is',
                          later: 'For later',
                          saved: 'Saved',
                          rejected: 'Declined',
                        } as Record<string, string>
                      )[text(item.status)] || humanize(text(item.status))}
                    </span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="hint">No recommendations in this section.</p>
            )}
          </section>
        ))}
      </Disclosure>
    </div>
  );
}

function IndividualFindings({
  data,
  controller,
}: {
  data: JsonObject;
  controller: ReviewController;
}) {
  const fieldMap = object(data.field_map),
    draft = object(data.draft);
  return (
    <Disclosure
      id="individual-review-controls"
      className="review-advanced"
      summary="Individual field controls and earlier findings"
      openWhen={Boolean(data.action_item_id || data.investigate_id)}
    >
      <p className="hint">
        {number(data.outstanding_count)} outstanding field decisions · {number(data.deferred_count)}{' '}
        deferred. Use these controls to adjust individual parts of a recommendation.
      </p>
      {strings(draft.suggestion_warnings).map((warning, i) => (
        <p className="notice" key={i}>
          {warning}
        </p>
      ))}
      {records(data.action_groups).map((group) => (
        <section
          className="review-action-group"
          key={text(group.id)}
          aria-labelledby={`${text(group.id)}-heading`}
        >
          <h3 id={`${text(group.id)}-heading`}>{text(group.label)}</h3>
          {strings(group.warnings).map((warning, i) => (
            <p className="review-warning" key={i}>
              {warning}
            </p>
          ))}
          {records(group.items).map((item) =>
            item.status !== 'pending' ? (
              <HandledRow
                controller={controller}
                item={item}
                fieldMap={fieldMap}
                draft={draft}
                undo
                key={text(item.id)}
              />
            ) : (
              <article className="review-item" id={text(item.id)} key={text(item.id)} tabIndex={-1}>
                {records(group.items).length > 1 && <h4>{text(item.field_label)}</h4>}
                {Boolean(item.reopened) && (
                  <>
                    <p className="review-warning">
                      New information—please reconsider your previous decision.
                    </p>
                    <Disclosure summary="Previous decision">
                      <p>
                        {humanize(text(object(item.previous_decision).decision))}
                        {text(object(item.previous_decision).decided_at) &&
                          ` · ${text(object(item.previous_decision).decided_at)}`}
                      </p>
                    </Disclosure>
                  </>
                )}
                {item.kind === 'suggestion' ? (
                  <>
                    <ValuePair current={item.current_display} proposed={item.proposed_display} />
                    <p className="hint">Provisional until you verify the evidence.</p>
                  </>
                ) : (
                  <p>
                    Unresolved: {text(item.field_label).toLowerCase()}. Current information:{' '}
                    <strong>{text(item.current_display)}</strong>.
                  </p>
                )}
                <div className="review-actions">
                  {item.kind === 'suggestion' ? (
                    <>
                      {item.draft_conflict ? (
                        <a href={`#pending-${text(item.field_dom_id)}`}>
                          Review your existing draft
                        </a>
                      ) : (
                        <DecisionButton
                          controller={controller}
                          item={item}
                          action="accept"
                          label="Accept"
                          stale={Boolean(draft.stale)}
                        />
                      )}
                      <DecisionButton
                        controller={controller}
                        item={item}
                        action="reject"
                        label="Reject"
                      />
                      <SafeLink
                        href={
                          !item.draft_conflict && !item.stale && !draft.stale
                            ? item.proposal_edit_url
                            : object(fieldMap[text(item.field)]).review_edit_url
                        }
                      >
                        {!item.draft_conflict && !item.stale && !draft.stale
                          ? 'Edit suggestion for'
                          : 'Edit'}{' '}
                        {text(item.field_label).toLowerCase()}
                      </SafeLink>
                    </>
                  ) : (
                    <>
                      <SafeLink href={group.investigate_url}>
                        Investigate {text(item.field_label).toLowerCase()}
                      </SafeLink>
                      {object(draft.changes)[text(item.field)] ? (
                        <a href={`#pending-${text(item.field_dom_id)}`}>
                          Review queued change before keeping current information
                        </a>
                      ) : (
                        <DecisionButton
                          controller={controller}
                          item={item}
                          action="keep"
                          label="Keep current information"
                        />
                      )}
                      <DecisionButton
                        controller={controller}
                        item={item}
                        action="later"
                        label="Later"
                      />
                    </>
                  )}
                </div>
                {Boolean(item.draft_conflict) && item.kind === 'suggestion' && (
                  <Disclosure summary="Replace your existing draft with this suggestion">
                    <p>
                      Your manual draft differs from this suggestion. Replacing it queues the
                      suggestion as provisional.
                    </p>
                    <DecisionButton
                      controller={controller}
                      item={item}
                      action="accept"
                      label="Replace with this suggestion"
                      replace
                      stale={Boolean(draft.stale)}
                    />
                  </Disclosure>
                )}
              </article>
            ),
          )}
          <Disclosure
            id={`${text(group.id)}-details`}
            className="review-investigation"
            openWhen={data.investigate_id === group.id}
            summary={
              records(group.items)[0]?.kind === 'question'
                ? 'Investigate: evidence and next steps'
                : 'Why this change? Evidence and next steps'
            }
          >
            {strings(group.reasons).map((reason, i) => (
              <p key={i}>{reason}</p>
            ))}
            <Evidence items={group.leads} />
            {records(group.evidence_items).length > 0 && (
              <Disclosure summary="Supporting excerpts and source summaries">
                <Evidence items={group.evidence_items} />
              </Disclosure>
            )}
            <p className="hint">
              Inspect the source, then edit the relevant field or keep its current information.
              Investigating does not request another AI review.
            </p>
            <div className="review-actions">
              {records(group.items).map((item) => (
                <SafeLink
                  key={text(item.id)}
                  href={object(fieldMap[text(item.field)]).review_edit_url}
                >
                  Edit {text(item.field_label).toLowerCase()}
                </SafeLink>
              ))}
            </div>
          </Disclosure>
        </section>
      ))}
      {!records(data.action_groups).length && (
        <p className="hint">
          {records(data.pending).length
            ? 'Your accepted changes are ready for final review below.'
            : records(data.items).length
              ? 'No items need a decision now. Deferred and reviewed items remain available below.'
              : draft.suggestion_status
                ? 'No supported changes were proposed. You can still edit or verify information manually.'
                : 'Request an AI review or view and edit information manually.'}
        </p>
      )}
    </Disclosure>
  );
}

export function ReviewPage() {
  const query = usePage();
  if (!query.data) return <PageLoading query={query} />;
  return <ReviewSession key={text(object(query.data.data.target).id)} initialPage={query.data} />;
}

function ReviewSession({ initialPage }: { initialPage: UiPage }) {
  const [page, setPage] = useState(initialPage);
  const pageRef = useRef(initialPage);
  const [edits, setEdits] = useState<Record<string, DraftEdit>>({});
  const editsRef = useRef<Record<string, DraftEdit>>({});
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const queue = useRef<Promise<void>>(Promise.resolve());
  const sequence = useRef(0),
    savingRef = useRef(0),
    actingRef = useRef(false),
    blockedWork = useRef(false);
  const normalizedDestination = useRef('');
  const mounted = useRef(true);
  const [saving, setSaving] = useState(0),
    [acting, setActing] = useState(false),
    [status, setStatus] = useState(''),
    [error, setError] = useState('');
  const location = useLocation(),
    locationRef = useRef(location);
  locationRef.current = location;
  const client = useQueryClient(),
    navigate = useNavigate();
  const mutation = useMutation({
    mutationFn: ({ path, fields }: { path: string; fields: Fields }) => apiAction(path, fields),
    retry: false,
  });
  const send = mutation.mutateAsync;
  const data = page.data,
    target = object(data.target),
    draft = object(data.draft),
    review = object(data.review),
    navigation = object(data.navigation),
    fieldMap = object(data.field_map);

  const applyPage = useCallback(
    (next: UiPage) => {
      if (
        number(object(next.data.draft).version) < number(object(pageRef.current.data.draft).version)
      )
        return;
      pageRef.current = next;
      setPage(next);
      const current = locationRef.current;
      client.setQueryData(pageKey(current.pathname + current.search), next);
    },
    [client],
  );
  useEffect(() => {
    if (initialPage !== pageRef.current) applyPage(initialPage);
  }, [initialPage, applyPage]);

  const putEdits = useCallback((value: Record<string, DraftEdit>) => {
    editsRef.current = value;
    setEdits(value);
  }, []);
  const tokens = useCallback((): Fields => {
    const current = pageRef.current.data,
      nav = object(current.navigation);
    return {
      revision: text(object(current.review).revision),
      version: text(object(current.draft).version),
      section_offset: text(nav.section_offset, '0'),
      passage: text(nav.passage),
      step: text(current.guided_step),
    };
  }, []);

  const save = useCallback(
    (key: string, defaults?: DraftEdit): Promise<void> => {
      clearTimeout(timers.current.get(key));
      timers.current.delete(key);
      if (defaults && !editsRef.current[key])
        putEdits({ ...editsRef.current, [key]: { ...defaults, sequence: ++sequence.current } });
      queue.current = queue.current.then(async () => {
        const captured = editsRef.current[key];
        if (!captured) return;
        savingRef.current++;
        setSaving(savingRef.current);
        const current = pageRef.current.data;
        try {
          const result = await send({
            path: `/review/${encodeURIComponent(text(object(current.target).id))}/${captured.action}`,
            fields: { ...captured.fields, ...tokens() },
          });
          if ('redirect' in result)
            throw new Error(
              'The draft could not be confirmed. Refresh this review before trying again.',
            );
          applyPage(result);
          setError('');
          const latest = editsRef.current[key];
          if (latest?.sequence === captured.sequence) {
            const remaining = { ...editsRef.current };
            delete remaining[key];
            putEdits(remaining);
          } else if (latest && captured.proposal) {
            const fields = { ...latest.fields };
            delete fields.proposal_item_id;
            putEdits({ ...editsRef.current, [key]: { ...latest, fields, proposal: false } });
          }
          if (captured.proposal) {
            // An accepted proposal must not be re-opened as an unaccepted prefill on reload.
            // This only changes the address; a newer edit remains in the same review session.
            const url = text(result.data.review_url);
            if (url) {
              const parsed = new URL(url, window.location.origin),
                address = parsed.pathname + parsed.search;
              client.setQueryData(pageKey(address), result);
              normalizedDestination.current = address;
              void Promise.resolve(navigate(url, { replace: true })).finally(() => {
                normalizedDestination.current = '';
              });
            }
          }
          setStatus(
            text(result.data.message) ||
              'Draft saved locally. Choose Save changes when you are ready to apply it.',
          );
          if (editsRef.current[key] && !editsRef.current[key].proposal)
            timers.current.set(
              key,
              setTimeout(() => {
                void save(key);
              }, 1200),
            );
        } catch (caught) {
          if (caught instanceof ApiError && caught.page) applyPage(caught.page);
          setError(
            caught instanceof Error
              ? caught.message
              : 'The draft could not be saved. Your input is still here.',
          );
          setStatus(
            'Draft not saved. Your input has been kept; review the message and save again.',
          );
        } finally {
          savingRef.current--;
          setSaving(savingRef.current);
        }
      });
      return queue.current;
    },
    [applyPage, client, navigate, putEdits, send, tokens],
  );

  const change = useCallback<ChangeEditor>(
    (key, action, defaults, name, value, proposal = false) => {
      const previous = editsRef.current[key];
      const fields = { ...(previous?.fields ?? defaults), [name]: value };
      if (['value', 'short_names', 'mode'].includes(name) && action === 'draft')
        fields.verified = '';
      if (['value', 'short_names'].includes(name) && 'mode' in fields) fields.mode = 'names';
      const edited = {
        action,
        fields,
        sequence: ++sequence.current,
        proposal: previous?.proposal ?? proposal,
      };
      putEdits({ ...editsRef.current, [key]: edited });
      clearTimeout(timers.current.get(key));
      if (edited.proposal)
        setStatus('Suggestion edited as unsaved input. Choose Add to draft when ready.');
      else {
        setStatus('Unsaved field changes. A local draft will be saved shortly.');
        timers.current.set(
          key,
          setTimeout(() => {
            void save(key);
          }, 1200),
        );
      }
    },
    [putEdits, save],
  );

  const flush = useCallback(async () => {
    if (Object.values(editsRef.current).some((edit) => edit.proposal)) {
      setStatus(
        'Choose Add to draft or Cancel suggestion edit before continuing. The suggestion has not been accepted.',
      );
      return false;
    }
    Object.keys(editsRef.current).forEach((key) => {
      void save(key);
    });
    await queue.current;
    if (Object.keys(editsRef.current).length) {
      setStatus('Save the open field before continuing. Your input has been kept.');
      return false;
    }
    return true;
  }, [save]);

  const act = useCallback(
    async (action: string, fields: Fields = {}) => {
      if (actingRef.current) return;
      actingRef.current = true;
      setActing(true);
      const owner = locationRef.current;
      const ownedAddress = owner.pathname + owner.search;
      try {
        if (!(await flush())) return;
        if (!mounted.current || locationRef.current.key !== owner.key) return;
        setError('');
        const current = pageRef.current.data;
        const startFocus = document.activeElement;
        // Saving a dirty field above can add a new pending correction. The final
        // apply must use the resulting draft, rather than the earlier button render.
        if (action === 'apply') {
          const pending = records(current.pending);
          fields = { request_id: text(current.request_id), count: String(pending.length) };
          pending.forEach((item, index) => {
            fields[`field_${index}`] = text(object(item.field).key);
            fields[`selected_${index}`] = 'yes';
          });
        }
        setStatus(
          action === 'suggest'
            ? 'AI is reviewing this item. Manual drafts remain available.'
            : 'Saving your choice…',
        );
        const result = await send({
          path: `/review/${encodeURIComponent(text(object(current.target).id))}/${action}`,
          fields: { ...fields, ...tokens() },
        });
        if (!mounted.current || locationRef.current.key !== owner.key) {
          if (!('redirect' in result)) client.setQueryData(pageKey(ownedAddress), result);
          return;
        }
        if ('redirect' in result) {
          await navigate(result.redirect);
          return;
        }
        applyPage(result);
        setStatus('');
        if (action === 'recommendation') {
          const url = text(result.data.guided_view_url);
          if (url) {
            const parsed = new URL(url, window.location.origin);
            client.setQueryData(pageKey(parsed.pathname + parsed.search), result);
            await navigate(url, { replace: true });
          }
        }
        requestAnimationFrame(() => {
          if (!mounted.current || (action === 'suggest' && document.activeElement !== startFocus))
            return;
          const focusId =
            fields.preview === 'yes'
              ? 'guided-preview'
              : action === 'recommendation'
                ? result.data.current_recommendation
                  ? 'guided-heading'
                  : 'pending-heading'
                : fields.item_id
                  ? `${text(fields.item_id)}-undo`
                  : 'review-feedback';
          document.getElementById(focusId)?.focus({ preventScroll: action !== 'recommendation' });
        });
      } catch (caught) {
        if (!mounted.current || locationRef.current.key !== owner.key) {
          if (caught instanceof ApiError && caught.page)
            client.setQueryData(pageKey(ownedAddress), caught.page);
          return;
        }
        if (caught instanceof ApiError && caught.page) applyPage(caught.page);
        setError(
          caught instanceof Error
            ? caught.message
            : 'The action could not finish. Your drafts are kept.',
        );
        setStatus('');
        requestAnimationFrame(() => document.getElementById('review-feedback')?.focus());
      } finally {
        actingRef.current = false;
        setActing(false);
      }
    },
    [applyPage, client, flush, navigate, send, tokens],
  );

  const hasUnsaved = Object.keys(edits).length > 0 || saving > 0;
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      hasUnsaved &&
      normalizedDestination.current !== nextLocation.pathname + nextLocation.search &&
      currentLocation.pathname + currentLocation.search !==
        nextLocation.pathname + nextLocation.search,
  );
  useEffect(() => {
    mounted.current = true;
    if (blocker.state === 'blocked' && !blockedWork.current) {
      blockedWork.current = true;
      void flush()
        .then((ok) => {
          if (ok) blocker.proceed();
          else blocker.reset();
        })
        .finally(() => {
          blockedWork.current = false;
        });
    }
  }, [blocker, flush]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (Object.keys(editsRef.current).length || savingRef.current) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', beforeUnload);
    const activeTimers = timers.current;
    return () => {
      mounted.current = false;
      window.removeEventListener('beforeunload', beforeUnload);
      activeTimers.forEach(clearTimeout);
    };
  }, []);
  const cancel = (key: string, url: string) => {
    clearTimeout(timers.current.get(key));
    timers.current.delete(key);
    const remaining = { ...editsRef.current };
    delete remaining[key];
    putEdits(remaining);
    void navigate(url);
  };
  const controller: ReviewController = { edits, change, save, cancel, act, busy: acting };
  const refresh = async () => {
    if (!(await flush())) return;
    try {
      const current = locationRef.current;
      applyPage(await apiGet<UiPage>(current.pathname + current.search));
      setStatus('Review progress refreshed.');
      setError('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The review could not be refreshed.');
    }
  };

  return (
    <div id="review-page">
      <p className="breadcrumb">
        <Link
          to={`/books/${encodeURIComponent(text(target.work_id))}?section_offset=${text(navigation.section_offset, '0')}`}
        >
          {text(target.work_title)}
        </Link>
        {text(navigation.passage) && (
          <>
            {' '}
            ·{' '}
            <Link to={`/cite/${encodeURIComponent(text(navigation.passage))}`}>
              Back to citation
            </Link>
          </>
        )}
      </p>
      <header className="review-heading">
        <h1>
          {target.scope === 'work'
            ? 'Review book details'
            : target.scope === 'section'
              ? 'Review this section'
              : 'Review this excerpt'}
        </h1>
        <p className="lede">{text(target.title)}</p>
      </header>
      <section className="review-scope" aria-label="Correction scope">
        <p>
          <strong>
            {target.scope === 'work'
              ? 'Changes to this book'
              : target.scope === 'section'
                ? 'Changes to this section'
                : 'Changes to this excerpt'}
          </strong>
          {text(target.location_label) && ` · ${text(target.location_label)}`}
        </p>
        {text(target.read_url) && (
          <p>
            <SafeLink href={target.read_url}>Read {text(target.title)} in context</SafeLink>
          </p>
        )}
        {target.scope !== 'work' && (
          <p className="hint">
            ISBN, edition, or publisher questions?{' '}
            <Link to={`/review/${encodeURIComponent(text(target.work_id))}`}>
              Review book details
            </Link>
            .
          </p>
        )}
        <Disclosure summary="What text does this review cover?">
          <p>
            This is an optional review. Opening it does not mean something is wrong. Changes apply
            to this{' '}
            {target.scope === 'work'
              ? 'book'
              : target.scope === 'section'
                ? 'entire indexed section'
                : 'passage'}
            .
          </p>
          {text(target.location) && <p className="source-location">{text(target.location)}</p>}
          {text(target.preview) && (
            <blockquote className="review-preview">{text(target.preview)}</blockquote>
          )}
          {text(target.narrower_url) && (
            <p>
              <SafeLink href={target.narrower_url}>Review the opening passage only</SafeLink>
            </p>
          )}
        </Disclosure>
        {Boolean(review.boundary_risk) && (
          <p className="review-warning">
            This target may contain several contributions. Check its full extent before assigning
            credits.{' '}
            {text(target.narrower_url) && (
              <SafeLink href={target.narrower_url}>Review a narrower passage</SafeLink>
            )}
          </p>
        )}
        {review.source_current === false && (
          <p className="review-warning">
            A source has changed or is missing. Synchronize the library before continuing.
          </p>
        )}
      </section>
      <div id="review-feedback" tabIndex={-1}>
        <Message error>{error || text(data.error)}</Message>
        {strings(data.saved_fields).length > 0 && (
          <p>
            Saved fields:{' '}
            {strings(data.saved_fields)
              .map((key) => text(object(fieldMap[key]).label, key))
              .join(', ')}
            .
          </p>
        )}
      </div>
      <p
        id="review-live-status"
        className={status ? 'hint' : text(data.message) ? 'notice' : 'hint'}
        role="status"
        aria-live="polite"
      >
        {status || (!error && !data.error ? text(data.message) : '')}
      </p>
      {Boolean(draft.stale) && (
        <aside className="notice">
          <h2>This draft needs another look</h2>
          <p>
            Source or recorded information changed. Your draft is kept and cannot overwrite newer
            information.
          </p>
          <ActionButton controller={controller} action="rebase">
            Recheck draft against current information
          </ActionButton>
        </aside>
      )}
      <nav className="review-jump" aria-label="Review sections">
        <a href="#review-overview">Review overview</a>
        <SafeLink href={data.summary_url}>
          {records(data.pending).length} changes ready to save
        </SafeLink>
        <a href="#current-information">All information</a>
      </nav>
      <section id="ai-review" aria-labelledby="ai-heading">
        <h2 id="ai-heading" className="visually-hidden">
          Guided review
        </h2>
        <Disclosure
          className="review-ai-help"
          openWhen={!records(data.guidance).length}
          summary="AI help for this review"
        >
          <ActionButton
            controller={controller}
            action="suggest"
            fields={{ generation_request_id: text(data.request_id) }}
            disabled={Boolean(data.busy || draft.stale)}
          >
            {data.busy ? 'AI review is running…' : 'Review with AI'}
          </ActionButton>
          <p className="hint">
            AI can inspect the source and recommend what to keep or change. A request temporarily
            reserves $0.75 from the shared monthly allowance; simply opening this page costs
            nothing.
          </p>
          <Disclosure summary="AI review limits and consulted sources">
            <p>
              Uses the configured monthly library allowance. Known costs replace the temporary
              reserve; interrupted requests may retain an uncertain reserve. Opening or
              investigating this page never starts paid work.
            </p>
            {Boolean(draft.suggestion_cost) && (
              <p>
                This review{' '}
                {object(draft.suggestion_cost).uncertain
                  ? 'has a cost or retained reservation of'
                  : 'cost'}{' '}
                {reviewCost(object(draft.suggestion_cost).charged_or_reserved)}.
              </p>
            )}
            {records(object(draft.external_report).sources).length > 0 && (
              <Disclosure summary="All external sources checked">
                <p>
                  These sources may be inconclusive or describe another edition; inclusion does not
                  establish relevance to every question.
                </p>
                <ul>
                  {records(object(draft.external_report).sources).map((source, i) => (
                    <li key={i}>
                      <SafeLink href={source.url}>{text(source.title || source.url)}</SafeLink>
                    </li>
                  ))}
                </ul>
              </Disclosure>
            )}
          </Disclosure>
          {Boolean(data.busy) && (
            <p className="hint">
              The requested review is running. Refresh to check its saved progress; refreshing never
              starts another review.
            </p>
          )}
          <button
            type="button"
            className="secondary"
            disabled={acting}
            onClick={() => void refresh()}
          >
            Refresh review progress
          </button>
        </Disclosure>
        <div id="review-suggestions" tabIndex={-1}>
          <GuidedReview data={data} controller={controller} />
          <IndividualFindings data={data} controller={controller} />
        </div>
      </section>
      <PendingChanges data={data} controller={controller} />
      <div id="review-history">
        <Disclosure
          id="deferred-review"
          className="review-history"
          summary={`Deferred questions (${number(data.deferred_count)})`}
        >
          <p>These questions remain outstanding. Restore one when you are ready to investigate.</p>
          {records(data.deferred).map((item) => (
            <HandledRow
              key={text(item.id)}
              controller={controller}
              item={item}
              fieldMap={fieldMap}
              draft={draft}
            />
          ))}
        </Disclosure>
        <Disclosure
          id="handled-review"
          className="review-history"
          summary={`Reviewed items (${records(data.handled).length})`}
        >
          {records(data.handled).map((item) => (
            <HandledRow
              key={text(item.id)}
              controller={controller}
              item={item}
              fieldMap={fieldMap}
              draft={draft}
            />
          ))}
          {!records(data.handled).length && <p>No reviewed items yet.</p>}
        </Disclosure>
      </div>
      <Disclosure
        id="current-information"
        className="review-all-information"
        openWhen={Boolean(data.edit_field)}
        summary="View and edit all information"
      >
        <section aria-labelledby="current-heading">
          <h2 id="current-heading">Current information</h2>
          <p>
            Open a field to edit or verify it. Drafts affect the library only after{' '}
            <strong>Save changes</strong>.
          </p>
          {Object.entries(object(data.groups)).map(([group, fields], i) => (
            <section className="review-group" key={group} aria-labelledby={`review-group-${i}`}>
              <h3 id={`review-group-${i}`}>{group}</h3>
              {records(fields).map((field) => (
                <FieldEditor
                  key={text(field.key)}
                  field={field}
                  controller={controller}
                  data={data}
                />
              ))}
            </section>
          ))}
        </section>
      </Disclosure>
    </div>
  );
}
