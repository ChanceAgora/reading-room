"""Compact, read-only intake views and protected workflow actions."""
from __future__ import annotations

from copy import deepcopy
from urllib.parse import quote, urlencode

from fastapi import HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .review_web import display_value

PAGE_SIZE = 25
STATUS_LABELS = {
    'not_requested': 'Not requested', 'disabled': 'Turned off',
    'queued': 'Waiting to start', 'pending': 'Waiting to start',
    'running': 'In progress', 'paused': 'Paused', 'complete': 'Finished',
    'needs_attention': 'Needs your attention', 'needs_review': 'Needs your decision',
    'needs_evidence': 'Needs more evidence', 'no_change': 'No change needed',
    'reviewed': 'Reviewed', 'applied': 'Automatic changes saved',
    'saved': 'Automatic changes saved', 'result_saved': 'Review saved; changes pending',
    'suggestions_saved': 'Suggestions ready', 'skipped': 'No readable content to review',
    'non_substantive': 'Heading or navigation only', 'failed': 'Could not finish',
    'stale': 'Source changed; recheck needed', 'budget_blocked': 'Paused at the monthly allowance',
    'ready': 'Ready', 'available': 'Ready', 'not_started': 'Waiting to start',
    'unsupported': 'Not supported', 'unavailable': 'Unavailable', 'undone': 'Undone',
    'superseded': 'Changed since this intake', 'active': 'Automatically saved',
    'generated': 'Review saved; changes pending', 'incomplete': 'Only part of the text inspected',
    'interrupted': 'Interrupted; needs your decision', 'retry_pending': 'Partial results saved; retry needed',
    'partial': 'Some text is available', 'pending_engine_review': 'Waiting for indexing setup',
}
FIELD_LABELS = {
    'title': 'Displayed title', 'author': 'Displayed book credit', 'attribution': 'Section credit',
    'text_type': 'Kind of writing', 'bibliography.title': 'Citation title',
    'bibliography.authors': 'Citation writers', 'bibliography.editors': 'Book editors',
    'bibliography.translators': 'Translators', 'bibliography.year': 'Publication year',
    'bibliography.publisher': 'Publisher', 'bibliography.edition': 'Edition statement',
    'bibliography.format': 'Copy format', 'bibliography.type': 'Citation format',
}


def _label(value):
    if isinstance(value, dict):
        value = value.get('status', value.get('state', 'pending'))
    if value is True:
        return 'Ready'
    if value is False or value is None:
        return 'Waiting to start'
    return STATUS_LABELS.get(str(value), str(value).replace('_', ' ').capitalize())


def _url(identity, **query):
    base = '/intake/' + quote(identity, safe='')
    query = {key: value for key, value in query.items() if value not in (None, '', 0)}
    return base + ('?' + urlencode(query) if query else '')


def _version(data):
    try:
        value = int(data.get('version', ''))
        if value < 0:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise ValueError('Reload this intake to use its current controls.') from None


def _page(items, offset):
    total = len(items)
    offset = min(max(0, offset // PAGE_SIZE * PAGE_SIZE), max(0, (total - 1) // PAGE_SIZE * PAGE_SIZE))
    return {'items': items[offset:offset + PAGE_SIZE], 'offset': offset, 'total': total,
            'start': offset + 1 if total else 0, 'end': min(offset + PAGE_SIZE, total),
            'previous': offset - PAGE_SIZE if offset else None,
            'next': offset + PAGE_SIZE if offset + PAGE_SIZE < total else None}


def _summary(job):
    job = deepcopy(job)
    titles = job.get('work_titles') or []
    if isinstance(titles, dict):
        titles = list(titles.values())
    job['display_title'] = ' · '.join(str(value) for value in titles[:2]) or job.get('title') or 'Book intake'
    if len(titles) > 2:
        job['display_title'] += f' and {len(titles) - 2} more'
    job['url'] = _url(job['id'])
    job['status_label'] = _label(job.get('status', 'queued'))
    readiness = job.get('readiness') or {}
    job['text_label'] = _label(readiness.get('text'))
    job['semantic_label'] = _label(readiness.get('semantic'))
    job['review_label'] = _label(readiness.get('metadata_review', 'not_requested' if job.get('authorization', {}).get('review') in (None, False, 'not_requested') else 'pending'))
    return job


def _target(target):
    target = deepcopy(target)
    target['title'] = target.get('title') or ('Book details' if target.get('scope') == 'work' else 'Untitled section')
    target['status_label'] = _label(target.get('status', 'queued'))
    target['review_url'] = '/review/' + quote(target['id'], safe='')
    coverage = target.get('coverage') or {}
    supplied = coverage.get('target_blocks_supplied', coverage.get('supplied'))
    total = coverage.get('target_blocks_total', coverage.get('total'))
    target['coverage_text'] = f'{supplied} of {total} source blocks supplied.' if supplied is not None and total is not None else ''
    target['incomplete'] = target.get('status') != 'non_substantive' and bool(
        coverage.get('target_truncated') or coverage.get('complete') is False or
        supplied is not None and total is not None and supplied < total)
    return target


def _change(change):
    change = deepcopy(change)
    key = change.get('field', '')
    change['field_label'] = change.get('field_label') or FIELD_LABELS.get(key, key.replace('profile.', '').replace('bibliography.', '').replace('_', ' ').capitalize())
    before = change.get('before')
    if isinstance(before, dict) and 'value' in before:
        before = before['value']
    change['before_display'] = display_value(change.get('before_display', before))
    change['after_display'] = display_value(change.get('after', change.get('value')))
    change['event_id'] = change.get('event_id') or change.get('id')
    change['status_label'] = _label(change.get('status', 'active'))
    change['review_url'] = '/review/' + quote(change.get('target_id', ''), safe='')
    return change


def register_intake_routes(app, library, page, form, call, identifier):
    async def status(identity=None):
        from .intake import intake_status
        try:
            return await run_in_threadpool(intake_status, library, identity)
        except (KeyError, FileNotFoundError, ValueError):
            raise HTTPException(404, 'This intake could not be found.') from None

    @app.get('/intake')
    async def intake_list(request: Request, offset: int = Query(0, ge=0)):
        result = await status()
        rows = result.get('intakes', []) if isinstance(result, dict) else result
        listing = _page([_summary(row) for row in rows], offset)
        return page(request, 'intake_list.html', title='Book intake', nav='intake', listing=listing)

    async def render(request, identity, *, offset=0, changes_offset=0, work='', view='all', message='', error='', status_code=200, skipped=None):
        from .intake_curation import automatic_changes
        from .intake import TERMINAL
        if view not in {'all', 'attention'}:
            raise HTTPException(404, 'Choose all outcomes or questions needing attention.')
        job = _summary(await status(identity))
        catalog = await run_in_threadpool(library._catalog) if job.get('duplicate_candidates') else {'works': {}}
        candidates = [candidate for candidate in job.get('duplicate_candidates', []) if candidate in catalog['works']]
        duplicate_links = [{'title': catalog['works'][candidate].get('title') or 'Existing library record',
                            'url': '/books/' + quote(candidate, safe='')} for candidate in candidates[:10]]
        discrepancies = [str(item.get('reason') or item.get('message') or item.get('description') or display_value(item))
                         if isinstance(item, dict) else str(item) for item in job.get('discrepancies', [])[:20]]
        all_targets = [_target(target) for target in job.get('targets', [])]
        work_ids = job.get('work_ids') or list(dict.fromkeys(target.get('work_id') for target in all_targets if target.get('work_id')))
        if work and work not in work_ids:
            raise HTTPException(404, 'This book is not part of this intake.')
        targets = [target for target in all_targets if not work or target.get('work_id') == work]
        headings = [target for target in targets if target.get('scope') == 'section']
        needs_attention = {'needs_attention', 'needs_review', 'needs_evidence', 'incomplete', 'failed', 'stale', 'budget_blocked', 'interrupted', 'retry_pending'}
        counts = {'total': len(headings), 'reviewed': sum(target.get('status') in TERMINAL for target in headings),
                  'needs_attention': sum(target.get('status') in needs_attention for target in targets),
                  'incomplete': sum(target['incomplete'] for target in targets)}
        changes = [_change(change) for change in await run_in_threadpool(automatic_changes, library, identity)]
        if work:
            target_ids = {target['id'] for target in targets}
            changes = [change for change in changes if change.get('target_id') in target_ids]
        target_page = _page([target for target in targets if view == 'all' or target.get('status') in needs_attention], offset)
        change_page = _page(changes, changes_offset)
        for listing, key in ((target_page, 'offset'), (change_page, 'changes_offset')):
            for direction in ('previous', 'next'):
                listing[direction + '_url'] = _url(identity, work=work, view=view, **{key: listing[direction]}) if listing[direction] is not None else ''
        can_pause = job.get('status') in {'queued', 'running'}
        retry_semantic = job.get('status') == 'complete' and (job.get('readiness') or {}).get('semantic') == 'pending'
        can_resume = job.get('status') in {'paused', 'needs_attention'} or retry_semantic
        return page(request, 'intake_detail.html', status_code=status_code, title='Book intake', nav='intake',
                    job=job, counts=counts, target_page=target_page, change_page=change_page, work=work, view=view,
                    duplicate_links=duplicate_links, duplicate_count=len(candidates), discrepancies=discrepancies,
                    work_targets=[target for target in all_targets if target.get('scope') == 'work'],
                    can_pause=can_pause, can_resume=can_resume, retry_semantic=retry_semantic,
                    can_request_review=job.get('authorization', {}).get('review') != 'every_indexed_heading',
                    can_undo=any(change.get('undoable') for change in changes),
                    message=message, error=error, skipped=skipped or [],
                    attention_url=_url(identity, work=work, view='attention') + '#intake-targets',
                    all_outcomes_url=_url(identity, work=work) + '#intake-targets',
                    refresh_url=_url(identity, offset=target_page['offset'], changes_offset=change_page['offset'], work=work, view=view))

    @app.get('/intake/{intake_id}')
    async def intake_detail(request: Request, intake_id: str, offset: int = Query(0, ge=0),
                            changes_offset: int = Query(0, ge=0), work: str = '', view: str = 'all',
                            notice: str = '', undone: int = Query(0, ge=0), protected: int = Query(0, ge=0)):
        identifier(intake_id)
        messages = {
            'paused': 'Intake paused. An active request may finish; saved work is kept.',
            'resumed': 'Intake resumed. Only unfinished, authorized work will continue within the shared allowance.',
            'semantic_retry': 'Semantic indexing queued to retry. Completed heading reviews are kept.',
            'review_requested': 'Metadata review authorized for this intake. Saved results and source scope are preserved.',
            'undone': f'{undone} automatic change' + ('s' if undone != 1 else '') + ' undone. Later edits are preserved.',
        }
        skipped = ([{'reason': f'{protected} change' + ('s were' if protected != 1 else ' was') + ' kept because later edits are protected.'}]
                   if notice == 'undone' and protected else [])
        return await render(request, intake_id, offset=offset, changes_offset=changes_offset, work=work, view=view,
                            message=messages.get(notice, ''), skipped=skipped)

    @app.post('/intake/{intake_id}/{action}')
    async def intake_action(request: Request, intake_id: str, action: str):
        identifier(intake_id)
        if action not in {'pause', 'resume', 'undo', 'review'}:
            raise HTTPException(404, 'That intake action is not available.')
        data = await form(request)
        current = await status(intake_id)
        try:
            version = _version(data)
            notice, undone, protected = '', 0, 0
            if action == 'review':
                await run_in_threadpool(library.review_intake, intake_id, expected_version=version)
                notice = 'review_requested'
            elif action == 'undo':
                from .intake import undo_intake
                event = data.get('event_id') or None
                if event:
                    identifier(event)
                result = await run_in_threadpool(undo_intake, library, intake_id, event_id=event, expected_version=version)
                notice, undone, protected = 'undone', len(result.get('undone', [])), len(result.get('skipped', []))
            else:
                from .intake import pause_intake, resume_intake
                await run_in_threadpool(pause_intake if action == 'pause' else resume_intake, library, intake_id, expected_version=version)
                notice = ('paused' if action == 'pause' else 'semantic_retry' if current.get('status') == 'complete' and
                          (current.get('readiness') or {}).get('semantic') == 'pending' else 'resumed')
            return RedirectResponse(_url(intake_id, notice=notice, undone=undone, protected=protected) + '#intake-feedback', status_code=303)
        except ValueError as exc:
            return await render(request, intake_id, error=str(exc), status_code=409)
