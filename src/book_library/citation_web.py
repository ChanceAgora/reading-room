"""Accessible citation views; the renderer and durable metadata live in shared services."""
from __future__ import annotations
from urllib.parse import quote
from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from .citations import _display as contributor_name

TEXT_FIELDS={'title':'Title','short_title':'Short title (optional)','publisher':'Publisher','year':'Publication year of this edition','edition':'Edition statement (optional)','volume':'Volume number (optional)','volume_title':'Volume title (optional)','url':'Stable source URL (optional)','doi':'DOI (optional)','format':'Format (for example, EPUB)'}
SCRIPTURE_FIELDS={'bible_translation':'Bible translation — full name (Scripture only)', 'bible_translation_short':'Bible translation — abbreviation (optional)'}
TEXT_FIELDS.update(SCRIPTURE_FIELDS)
CONTRIBUTION_FIELDS=('title','short_title',*SCRIPTURE_FIELDS)


def register_citation_routes(app, library, page, form, call, identifier):
    def supplied_locator(data):
        value=data.get('locator_value','').strip()
        if not value:return None
        return {'type':data.get('locator_type','section'),'value':value,
                'verified':data.get('locator_verified')=='yes','evidence':data.get('locator_evidence','').strip()}

    async def render_citation(request,passage_id,locator=None,saved=False,segment=None):
        result=await call('cite',identifier(passage_id),locator=locator,segment_id=identifier(segment) if segment else None)
        reading=await call('read',passage_id,context=0)
        return page(request,'citation.html',title='Cite this passage',nav='books',citation=result,passage=reading['passage'],section=reading['section'],locator=locator or {},locator_type=(locator or {}).get('type',''),locator_value=(locator or {}).get('value',''),saved=saved,segment_id=segment or result.get('segment_id',''))

    @app.get('/cite/{passage_id}')
    async def citation_page(request:Request,passage_id:str,locator_type:str=Query('',max_length=20),locator_value:str=Query('',max_length=300),saved:bool=False,segment:str=Query('',max_length=160)):
        locator={'type':locator_type,'value':locator_value,'verified':False} if locator_value else None
        return await render_citation(request,passage_id,locator,saved,segment)

    @app.post('/cite/{passage_id}/preview')
    async def preview_citation(request:Request,passage_id:str):
        data=await form(request)
        return await render_citation(request,passage_id,supplied_locator(data),segment=data.get('segment'))

    @app.get('/api/cite/{passage_id}')
    async def api_citation(passage_id:str,segment:str=Query('',max_length=160)):
        return await call('cite',identifier(passage_id),segment_id=identifier(segment) if segment else None)

    async def citation_download(passage_id,format,locator=None,segment=None):
        result=await call('cite',identifier(passage_id),locator=locator,segment_id=identifier(segment) if segment else None)
        if format=='json':return JSONResponse(result,headers={'Content-Disposition':'attachment; filename="citation.json"'})
        if format not in ('txt','md'):raise HTTPException(400,'Choose a text, Markdown, or JSON export.')
        values=result.get('markdown',result) if format=='md' else result
        content='\n\n'.join(label+'\n'+values.get(key,result[key]) for label,key in [('Full note','full_note'),('Shortened note','short_note'),('Bibliography','bibliography')])
        if result.get('component_citations'):
            content='Choose the source component you used.\n\n'+'\n\n'.join(item['text_type'].replace('_',' ').capitalize()+': '+item['attribution']+'\n'+(item.get('markdown',item) if format=='md' else item)['full_note']+'\n'+item['links']['local_citation'] for item in result['component_citations'])
        if result.get('warnings'):content+='\n\nReview before citing:\n'+'\n'.join('- '+str(w) for w in result['warnings'])
        return Response(content+'\n',media_type='text/plain; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="citation.{format}"'})

    @app.get('/cite/{passage_id}/export')
    async def export_citation(passage_id:str,format:str='txt',locator_type:str=Query('',max_length=20),locator_value:str=Query('',max_length=300),segment:str=Query('',max_length=160)):
        locator={'type':locator_type,'value':locator_value,'verified':False} if locator_value else None
        return await citation_download(passage_id,format,locator,segment)

    @app.post('/cite/{passage_id}/export')
    async def export_verified_citation(request:Request,passage_id:str):
        data=await form(request)
        return await citation_download(passage_id,data.get('format','txt'),supplied_locator(data),data.get('segment'))

    @app.get('/bibliography/{target_id}')
    async def bibliography_page(request:Request,target_id:str,passage:str=Query('',max_length=160),saved:bool=False,unchanged:bool=False):
        target=await call('bibliography_record',identifier(target_id))
        container=await call('bibliography_record',target['work_id']) if target['is_section'] else target
        return page(request,'bibliography.html',title='Citation details',nav='books',target=target,fields={k:v for k,v in TEXT_FIELDS.items() if (target['is_section'] and k in CONTRIBUTION_FIELDS) or (not target['is_section'] and k not in SCRIPTURE_FIELDS)},roles=('authors','translators') if target['is_section'] else ('authors','editors','translators'),contributor_name=contributor_name,inherited_translators=container['record'].get('translators') or [],passage_id=identifier(passage) if passage else '',saved=saved,unchanged=unchanged)

    @app.post('/bibliography/{target_id}')
    async def save_bibliography(request:Request,target_id:str):
        data=await form(request); target=await call('bibliography_record',identifier(target_id))
        passage=identifier(data['passage_id']) if data.get('passage_id') else ''
        evidence=data.get('evidence','').strip()
        if not evidence or len(evidence)>4000:raise HTTPException(400,'Give the title-page or publication details you checked, with a source location.')
        patch={key:data.get(key,'').strip() for key in TEXT_FIELDS if (target['is_section'] and key in CONTRIBUTION_FIELDS) or (not target['is_section'] and key not in SCRIPTURE_FIELDS)}
        if any(len(value)>2000 for value in patch.values()):raise HTTPException(400,'Please shorten the citation field to 2,000 characters or fewer.')
        roles=('authors','translators') if target['is_section'] else ('authors','editors','translators')
        for role in roles:
            if role=='translators' and target['is_section'] and data.get('translators_override')!='yes':
                # Null clears an old section override and restores the container.
                patch[role]=None
                continue
            names=data.get(role,'').splitlines(); shorts=data.get(role+'_short','').splitlines(); people=[]
            if len(names)>50:raise HTTPException(400,'Use 50 or fewer names for each role.')
            existing=target['record'].get(role) or []; used=set()
            for i,name in enumerate(names):
                name=name.strip()
                if not name:continue
                short=shorts[i].strip() if i<len(shorts) else ''
                # Preserve structure, suffixes and name order when only a short
                # name changes or an existing contributor is moved in the list.
                matches=[j for j,old in enumerate(existing) if j not in used and contributor_name(old)==name]
                match=i if i in matches else matches[0] if len(matches)==1 else None
                if match is not None:
                    used.add(match); person=dict(existing[match])
                    if short!=person.get('short',''):
                        if short:person['short']=short
                        else:person.pop('short',None)
                else:
                    if len(name)>500:raise HTTPException(400,'Please shorten each new contributor name to 500 characters or fewer.')
                    person={'literal':name,**({'short':short} if short else {})}
                people.append(person)
            if role=='authors' and data.get('authors_absent')=='yes':
                if people:raise HTTPException(400,'Clear the author names or uncheck the verified absence of a named author.')
                patch[role]=[]
            else:
                # A blank author field is unknown, not proof of anonymity.
                explicit_empty=(role=='translators' and target['is_section']) or (role!='authors' and target['record'].get(role)==[])
                patch[role]=people if people or explicit_empty else None
        if target['is_section']:
            kind=data.get('type','chapter')
            if kind not in ('chapter','poem','entry','scripture'):raise HTTPException(400,'Choose the contribution type.')
            patch['type']=kind
            scope=data.get('scripture_scope','') or None
            if scope not in (None,'text_only','mixed'):raise HTTPException(400,'Choose the Scripture scope.')
            patch['scripture_scope']=scope
        previous=target['record']; verify_unchanged=data.get('verify_unchanged')=='yes'
        def changed(key,value):
            old=previous.get(key)
            # The browser renders integer years as text and null text fields as
            # blank. Those round trips are not edits or new verification.
            if key in TEXT_FIELDS:return value!=('' if old is None else str(old).strip())
            return value!=old
        def displayed_fact(key,value):
            # Verification of blank controls cannot invent facts. Explicit
            # author absence and a section translation override have controls
            # that distinguish known absence from unknown or inherited values.
            if value:return True
            if key=='authors':return value==[] and data.get('authors_absent')=='yes'
            if key=='translators':return value==[] and target['is_section'] and data.get('translators_override')=='yes'
            return False
        patch={key:value for key,value in patch.items() if changed(key,value) or verify_unchanged and displayed_fact(key,value)}
        if not patch:
            location='/bibliography/'+quote(target_id,safe='')+'?unchanged=true'
            if passage:location+='&passage='+quote(passage,safe='')
            return RedirectResponse(location,status_code=303)
        await call('annotate',target_id,{'field':'bibliography','value':patch,'origin':'user','status':'confirmed','evidence':evidence})
        if passage:return RedirectResponse('/cite/'+quote(identifier(passage),safe='')+'?saved=true',status_code=303)
        return RedirectResponse('/bibliography/'+quote(target_id,safe='')+'?saved=true',status_code=303)
