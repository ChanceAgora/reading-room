"""Complete-unit reading and explicit, source-anchored selection actions."""
from __future__ import annotations

import json
from urllib.parse import quote, urlencode

from fastapi import HTTPException, Query, Request
from fastapi.responses import RedirectResponse


def register_unit_routes(app, library, page, form, call, identifier, reading_tables):
    def clean(value, maximum=4000):
        if len(value) > maximum:
            raise HTTPException(400, f"Please keep this field to {maximum:,} characters or fewer.")
        return value.strip()

    async def get_reading(unit_id, anchor=None, cursor=0, selection_id=None, match=None):
        selection = await call('selection', identifier(selection_id)) if selection_id else None
        anchor_offset = None
        if selection:
            if selection.get('unit_id') != unit_id:
                raise HTTPException(400, 'This selection belongs to a different reading unit.')
            if selection.get('available') is False:
                raise HTTPException(409, selection.get('error') or 'This saved selection no longer matches the current source. Review its saved quotation before continuing.')
            if not anchor and selection.get('source_ranges'):
                anchor = selection['source_ranges'][0]['block_id']
                anchor_offset = selection['source_ranges'][0]['start']
        options = {'match': match} if match else {}
        if anchor_offset is not None:
            options['anchor_offset'] = anchor_offset
        reading = reading_tables(await call('read_unit', identifier(unit_id), anchor=identifier(anchor) if anchor else None, cursor=cursor, **options))
        reading['selection'] = selection
        return reading

    @app.get('/units/{unit_id}')
    async def unit_page(request: Request, unit_id: str, anchor: str = Query('', max_length=160), cursor: int = Query(0, ge=0), selection: str = Query('', max_length=160), match: str = Query('', max_length=160), start: int = Query(0, ge=0), end: int | None = Query(None, ge=0), saved: bool = False):
        match_range = {'passage_id': identifier(match), 'start': start, 'end': end} if match else None
        reading = await get_reading(unit_id, anchor or None, cursor, selection or None, match_range)
        return page(request, 'unit.html', title=reading['unit']['title'], nav='books', reading=reading, saved=saved)

    @app.get('/api/contents/{work_id}')
    async def api_contents(work_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        return await call('contents', identifier(work_id), offset=offset, limit=limit)

    @app.get('/api/units/{unit_id}')
    async def api_unit(unit_id: str, anchor: str = Query('', max_length=160), cursor: int = Query(0, ge=0), match: str = Query('', max_length=160), start: int = Query(0, ge=0), end: int | None = Query(None, ge=0)):
        match_range = {'passage_id': identifier(match), 'start': start, 'end': end} if match else None
        return await call('read_unit', identifier(unit_id), anchor=identifier(anchor) if anchor else None, cursor=cursor, **({'match': match_range} if match_range else {}))

    async def make_selection(request):
        data = await form(request)
        action = data.get('action', 'cite')
        if action not in ('cite', 'record'):
            raise HTTPException(400, 'Choose citation or research use for this selection.')
        try:
            ranges = json.loads(data.get('source_ranges', ''))
        except (ValueError, TypeError):
            raise HTTPException(400, 'Highlight source text in the reader, then choose an action.') from None
        result = await call('create_selection', identifier(data.get('unit_id', '')), ranges)
        return result, action

    @app.post('/selections')
    async def create_selection(request: Request):
        result, action = await make_selection(request)
        return RedirectResponse('/selections/' + quote(result['id'], safe='') + '?' + urlencode({'action': action}), status_code=303)

    @app.post('/api/selections')
    async def api_create_selection(request: Request):
        result, action = await make_selection(request)
        return {**result, 'preview_url': '/selections/' + quote(result['id'], safe='') + '?' + urlencode({'action': action})}

    @app.get('/api/selections/{selection_id}')
    async def api_selection(selection_id: str):
        return await call('selection', identifier(selection_id))

    @app.get('/selections/{selection_id}')
    async def selection_page(request: Request, selection_id: str, action: str = 'cite', saved: bool = False):
        if action not in ('cite', 'record'):
            raise HTTPException(400, 'Choose citation or research use for this selection.')
        selection = await call('selection', identifier(selection_id))
        return page(request, 'selection.html', title='Review selected text', nav='books', selection=selection, action=action, saved=saved)

    async def citation_page(request, scope, target_id, locator=None):
        citation = await call('cite_unit' if scope == 'unit' else 'cite_selection', identifier(target_id), locator=locator)
        if scope == 'selection':
            selection = await call('selection', target_id)
            title = selection.get('title') or 'Selected source text'
            back = '/units/' + quote(selection['unit_id'], safe='') + '?' + urlencode({'selection': target_id})
        else:
            unit = (await call('read_unit', target_id, max_chars=500))['unit']
            title, back = unit['title'], '/units/' + quote(target_id, safe='')
        return page(request, 'unit_citation.html', title='Cite selected text' if scope == 'selection' else 'Cite this reading unit', nav='books', citation=citation, scope=scope, target_id=target_id, target_title=title, back_url=back, locator=locator or {})

    @app.get('/cite/unit/{unit_id}')
    async def cite_unit(request: Request, unit_id: str):
        return await citation_page(request, 'unit', unit_id)

    @app.get('/cite/selection/{selection_id}')
    async def cite_selection(request: Request, selection_id: str):
        return await citation_page(request, 'selection', selection_id)

    @app.get('/api/cite/unit/{unit_id}')
    async def api_cite_unit(unit_id: str):
        return await call('cite_unit', identifier(unit_id))

    @app.get('/api/cite/selection/{selection_id}')
    async def api_cite_selection(selection_id: str):
        return await call('cite_selection', identifier(selection_id))

    @app.post('/cite/{scope}/{target_id}/preview')
    async def preview_citation(request: Request, scope: str, target_id: str):
        if scope not in ('unit', 'selection'):
            raise HTTPException(404, 'Unknown citation scope.')
        data = await form(request)
        value = clean(data.get('locator_value', ''), 300)
        locator = {'type': data.get('locator_type', 'section'), 'value': value, 'verified': data.get('locator_verified') == 'yes', 'evidence': clean(data.get('locator_evidence', ''))} if value else None
        return await citation_page(request, scope, target_id, locator)

    @app.post('/usage/target')
    async def target_usage(request: Request):
        data = await form(request)
        scope, target = data.get('scope'), identifier(data.get('target_id', ''))
        if scope not in ('unit', 'selection'):
            raise HTTPException(400, 'Choose the whole reading unit or a source selection.')
        purpose, kind = data.get('purpose', 'research'), data.get('kind', 'inspected')
        if purpose not in ('research', 'class-prep', 'substack', 'efm') or kind not in ('inspected', 'offered', 'recommended', 'selected', 'used'):
            raise HTTPException(400, 'Choose a valid research purpose and activity.')
        notes = clean(data.get('notes', ''))
        event = {'purpose': purpose, 'kind': kind, 'destination': clean(data.get('destination', ''), 1000), 'notes': notes, 'evidence': notes or f'User explicitly recorded this {scope} as {kind} in the Reading Room.'}
        await call('record_target_usage', scope, target, event)
        destination = '/units/' if scope == 'unit' else '/selections/'
        suffix = '?saved=true#research-record' if scope == 'unit' else '?action=record&saved=true#research-record'
        return RedirectResponse(destination + quote(target, safe='') + suffix, status_code=303)
