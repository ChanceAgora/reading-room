"""Conservative imports from canonical structured lesson records only."""
from pathlib import Path
from .storage import read_json, stable


def import_usage(lib,path=None):
    if path is None:
        raise ValueError('Provide the directory containing your structured research-use records.')
    root=Path(path).expanduser().resolve()
    cat=lib._catalog(); files={f['path']:f['work_id'] for f in cat['files'].values()}
    for f in cat['files'].values():
        for p in f.get('previous_paths',[]): files[p]=f['work_id']
    events=[]
    def add(item,kind,evidence,project):
        source=item.get('local_source_file') or item.get('local_source_path')
        work=files.get(source)
        candidates=[]
        if not work:
            title=item.get('work') or item.get('title')
            if title: candidates=[w['id'] for w in cat['works'].values() if title.casefold() in w['title'].casefold()]
        events.append({'id':stable('import',evidence,kind,item.get('id'),source,item.get('exact_text','')),'kind':kind,'work_id':work,'candidate_work_ids':candidates,'match_status':'verified_path' if work else 'unresolved','project':project,'evidence':evidence,'source_record':item,'source_path':source,'origin':'structured_import'})
    for manifest in sorted(root.glob('*/art-manifest.json')):
        data=read_json(manifest,{}); status=read_json(manifest.parent/'status.json',{}); project=str(manifest.parent)
        selected=set(status.get('approved_quotation_ids',[])+status.get('approved_art_ids',[])); rec=set(data.get('recommended_quotation_ids',[])+data.get('recommended_art_ids',[]))
        for group in ('quotations','assets'):
            items=data.get(group,[])
            if isinstance(items,dict): items=[dict(v,id=k) for k,v in items.items() if isinstance(v,dict)]
            for item in items:
                if not isinstance(item,dict): continue
                evidence=str(manifest)+'#'+group+'/'+str(item.get('id','unknown'))
                add(item,'offered',evidence,project)
                if item.get('id') in rec: add(item,'recommended',evidence,project)
                if item.get('id') in selected: add(item,'selected',str(manifest.parent/'status.json')+'#'+str(item.get('id')),project)
                # Completed preparation alone does not establish teaching/publication use.
    for ledger in sorted(root.glob('*/_work/daily-inspiration/discovery-ledger.json')):
        data=read_json(ledger,{})
        for i,item in enumerate(data.get('installments',[])):
            if not isinstance(item,dict): continue
            # Preserve ledger evidence without guessing nested source identity or selection.
            add(item,'offered',str(ledger)+'#installments/'+str(i),str(ledger.parents[2]))
    imported=0
    for event in events:
        if not lib.record_usage(event).get('duplicate'): imported+=1
    return {'imported':imported,'records_seen':len(events),'unresolved_matches':sum(e['match_status']=='unresolved' for e in events),'policy':'offered/recommended/selected only when explicit; no automatic used events; unresolved matches retained'}
