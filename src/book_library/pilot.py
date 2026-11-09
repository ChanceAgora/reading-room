"""Freeze a source-grounded experiment before examining retrieval results."""
from __future__ import annotations
import hashlib,json,re,time,resource
from pathlib import Path
from .storage import read_json,atomic_json,digest,writer,now,stable
from .service import Library,terms
from .semantic import local_model,local_revision

BOOKSHARE_IDS=['1001568','1802682','1001424','4099028','977688','1346319','6573075','871887','1250207','7238532','4012699','1448028']


def sha_json(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def make_windows(lib):
    cat=lib._catalog(); works={w['id']:w for w in cat['works'].values() if str(w.get('metadata',{}).get('bookshare_id')) in BOOKSHARE_IDS}
    if len(works)!=12: raise ValueError('The twelve pilot works must be present.')
    m=local_model(); tokenizer=m.tokenizer; result=[]
    with lib._db() as db:
        for wid in works:
            for p in db.execute('SELECT * FROM passages WHERE work_id=? AND boilerplate=0 ORDER BY ordinal',(wid,)):
                # Header participates in the shared content input to both engines.
                header=works[wid]['title']+' · '+p['heading']
                if len(tokenizer('passage: '+header)['input_ids'])>96:
                    header=tokenizer.decode(tokenizer(header,add_special_tokens=False)['input_ids'][:90])
                text=p['text']; offsets=tokenizer(text,add_special_tokens=False,return_offsets_mapping=True)['offset_mapping']
                if not offsets: continue
                room=512-len(tokenizer('passage: '+header+'\n')['input_ids'])-12
                start=0
                while start<len(offsets):
                    end=min(start+room,len(offsets)); a=offsets[start][0]; b=offsets[end-1][1]
                    window=header+'\n'+text[a:b]
                    while len(tokenizer('passage: '+window)['input_ids'])>512:
                        end-=1; b=offsets[end-1][1]; window=header+'\n'+text[a:b]
                    result.append({'id':stable('window',p['id'],a,b),'work_id':wid,'passage_id':p['id'],'section_id':p['section_id'],'text':window,'token_count':len(tokenizer('passage: '+window)['input_ids']),'source_text_sha256':hashlib.sha256(text.encode()).hexdigest(),'char_start':a,'char_end':b})
                    if end==len(offsets): break
                    start=max(start+1,end-40)
    return works,result


def map_queries(lib,anchors):
    cat=lib._catalog();result=[]
    with lib._db() as db:
        for a in anchors:
            q={**a,'expected_passage_ids':[],'expected_section_ids':[],'work_id':None}
            if a['kind']=='no_support': result.append(q);continue
            works=[w for w in cat['works'].values() if str(w.get('metadata',{}).get('bookshare_id'))==str(a['bookshare_id'])]
            if len(works)!=1: raise ValueError('Unknown pilot anchor book: '+str(a))
            wid=works[0]['id'];q['work_id']=wid
            files=[f for f in cat['files'].values() if f['work_id']==wid and a.get('file_name_contains','') in Path(f['path']).name]
            if len(files)!=1: raise ValueError('Anchor needs an unambiguous file: '+a['id'])
            f=files[0];q['file_id']=f['id'];q['source_sha256']=f['sha256']
            ords=set(a.get('ordinals',[]))
            for lo,hi in a.get('ordinal_ranges',a.get('ranges',[])): ords.update(range(lo,hi+1))
            gold_blocks=[]
            for b in db.execute('SELECT * FROM blocks WHERE file_id=?',(f['id'],)):
                data=json.loads(b['data'])
                if data['ordinal'] in ords:
                    gold_blocks.append(b)
                    for p in db.execute('SELECT id,section_id FROM passages WHERE work_id=? AND first_ordinal<=? AND last_ordinal>=?',(wid,b['ordinal'],b['ordinal'])):
                        q['expected_passage_ids'].append(p['id']);q['expected_section_ids'].append(p['section_id'])
            q['expected_passage_ids']=list(dict.fromkeys(q['expected_passage_ids']));q['expected_section_ids']=list(dict.fromkeys(q['expected_section_ids']))
            if not q['expected_passage_ids']: raise ValueError('No gold source passages mapped for '+a['id'])
            caption_ordinals={n for image in a.get('expected_image_refs',[]) for n in image.get('caption_ordinals',[])}
            q['expected_caption_passage_ids']=[]
            for b in gold_blocks:
                if json.loads(b['data'])['ordinal'] in caption_ordinals:
                    q['expected_caption_passage_ids'].extend(r[0] for r in db.execute('SELECT id FROM passages WHERE work_id=? AND first_ordinal<=? AND last_ordinal>=?',(wid,b['ordinal'],b['ordinal'])))
            q['expected_caption_passage_ids']=list(dict.fromkeys(q['expected_caption_passage_ids']))
            q['source_evidence']=[{'locator':json.loads(b['data'])['locator'],'text':b['text'],'block_id':b['id']} for b in gold_blocks]
            result.append(q)
    return result


def freeze(lib,anchor_path):
    folder=lib.state/'pilot';existing=read_json(folder/'manifest.json')
    if existing and existing.get('frozen'): return existing
    anchors=read_json(anchor_path)
    if isinstance(anchors,dict):anchors=anchors['queries']
    if len(anchors)!=24: raise ValueError('Freeze exactly 24 grounded queries.')
    queries=map_queries(lib,anchors)
    if not {'direct','connection','no_support'}.issubset({q['kind'] for q in queries}): raise ValueError('The pilot needs direct, connection, and no-support cases.')
    if {str(q.get('bookshare_id')) for q in queries if q['kind']!='no_support'}!=set(BOOKSHARE_IDS): raise ValueError('Every pilot work needs a grounded query.')
    works,windows=make_windows(lib)
    cat=lib._catalog()
    manifest={'schema_version':1,'frozen':True,'created_at':now(),'generation':lib._active()['generation'],'work_ids':list(works),'bookshare_ids':BOOKSHARE_IDS,'titles':{k:v['title'] for k,v in works.items()},'source_hashes':{f['id']:f['sha256'] for f in cat['files'].values() if f['work_id'] in works},'tokenizer_revision':local_revision(),'query_count':24,'queries_sha256':sha_json(queries),'window_count':len(windows),'windows_sha256':sha_json(windows),'windowing':{'max_local_tokens':512,'overlap_tokens':40,'heading_budget_tokens':96,'prefix':'passage: ','query_prefix':'query: ','shared_inputs':'Identical title, heading, and text windows for both embedding engines; provider-specific query/passage prefixes only for E5.'},'judgment_policy':'Source-grounded known relevant anchors, fixed before retrieval evaluation. Not exhaustive relevance judgments; report known-anchor hit rate, not corpus-wide recall or precision. No-support cases are evaluated separately.'}
    with writer(lib.state):
        atomic_json(folder/'queries.json',queries);atomic_json(folder/'windows.json',windows);atomic_json(folder/'manifest.json',manifest)
        atomic_json(lib.state/'semantic.json',{'state':'pilot_frozen','coverage_books':12,'total_books':len(cat['works']),'engine':None,'full_build_approved':False})
    return manifest


def evaluate(lib):
    import numpy as np
    from usearch.index import Index
    from .semantic import semantic_search
    from .budget import Budget
    import sqlite3
    pilot=lib.state/'pilot';manifest=read_json(pilot/'manifest.json');queries=read_json(pilot/'queries.json');windows=read_json(pilot/'windows.json')
    if not manifest or not manifest['frozen']: raise ValueError('Freeze first.')
    if sha_json(queries)!=manifest['queries_sha256'] or sha_json(windows)!=manifest['windows_sha256']: raise ValueError('Frozen corpus or judgments changed.')
    exact=sqlite3.connect(':memory:');exact.execute('CREATE VIRTUAL TABLE baseline USING fts5(text,tokenize="unicode61 remove_diacritics 2")');exact.executemany('INSERT INTO baseline(rowid,text) VALUES(?,?)',[(i+1,w['text']) for i,w in enumerate(windows)])
    details=[];metrics={}
    for engine in ('exact','local','openai'):
        latencies=[];hits5=[];section5=[];rr=[];caption_hits=[];image_hits=[]
        for q in queries:
            start=time.perf_counter()
            if engine=='exact':
                ts=list(dict.fromkeys(terms(q['query'])))[:20];expr=' OR '.join('"'+t+'"' for t in ts)
                raw=[windows[r[0]-1] for r in exact.execute('SELECT rowid FROM baseline WHERE baseline MATCH ? ORDER BY rank LIMIT 100',(expr,))]
            else: raw=semantic_search(lib,q['query'],engine,limit=100,scope='pilot')
            unique=[];seen=set()
            for r in raw:
                if r['passage_id'] in seen: continue
                seen.add(r['passage_id']);unique.append(r)
                if len(unique)==10:break
            elapsed=(time.perf_counter()-start)*1000;latencies.append(elapsed)
            gold=set(q['expected_passage_ids']); ranking=[r['passage_id'] for r in unique]; ranks=[i+1 for i,pid in enumerate(ranking) if pid in gold]
            if q['kind']!='no_support': hits5.append(any(pid in gold for pid in ranking[:5]));rr.append(1/min(ranks) if ranks else 0)
            examples=[]
            for r in unique[:5]:
                with lib._db() as db:
                    row=db.execute('SELECT p.*,w.title FROM passages p JOIN works w ON w.id=p.work_id WHERE p.id=?',(r['passage_id'],)).fetchone()
                if row:examples.append({'passage_id':row['id'],'work_id':row['work_id'],'section_id':row['section_id'],'title':row['title'],'heading':row['heading'],'attribution':row['attribution'],'excerpt':row['text'][:850],'known_anchor':row['id'] in gold,'known_section':row['section_id'] in q['expected_section_ids']})
            if q['kind']!='no_support': section5.append(any(r['known_section'] for r in examples))
            caption_hit=None;image_hit=None
            if q.get('expected_image_refs'):
                expected_images={i['member'] for i in q['expected_image_refs']}
                caption_hit=any(r['passage_id'] in q.get('expected_caption_passage_ids',[]) for r in examples)
                image_hit=False
                for result in examples:
                    for block in lib.read(result['passage_id'],context=1)['blocks']:
                        if block.get('file_id')==q['file_id'] and expected_images.intersection(block.get('image_refs',[])): image_hit=True
                caption_hits.append(caption_hit);image_hits.append(image_hit)
            details.append({'engine':engine,'query_id':q['id'],'query':q['query'],'kind':q['kind'],'latency_ms':elapsed,'known_anchor_rank':min(ranks) if ranks else None,'results':examples,'caption_anchor_at_5':caption_hit,'expected_illustration_in_reading_context_at_5':image_hit})
        metrics[engine]={'known_anchor_hit_at_5':sum(hits5)/len(hits5),'known_section_hit_at_5':sum(section5)/len(section5),'mrr_at_10':sum(rr)/len(rr),'answerable_queries':len(hits5),'caption_queries':len(caption_hits),'caption_anchor_hit_at_5':sum(caption_hits)/len(caption_hits) if caption_hits else None,'illustration_reachable_at_5':sum(image_hits)/len(image_hits) if image_hits else None,'no_support_queries':sum(q['kind']=='no_support' for q in queries),'query_latency_ms_median':float(np.median(latencies)),'query_latency_ms_p95':float(np.percentile(latencies,95))}
    report={'frozen_manifest_sha256':sha_json(manifest),'generation':manifest['generation'],'metrics':metrics,'details':details,'budget':Budget(lib.state).report(),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'evaluated_at':now(),'limitations':manifest['judgment_policy']}
    atomic_json(pilot/'evaluation.json',report)
    atomic_json(lib.state/'semantic.json',{'state':'pilot_complete_awaiting_review','coverage_books':12,'total_books':len(lib._catalog()['works']),'engines':['local','openai'],'engine':None,'full_build_approved':False,'report':str(pilot/'evaluation.json')})
    return report
