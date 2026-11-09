import contextlib,json,sqlite3
from types import SimpleNamespace
from book_library import pilot

class CharacterTokenizer:
    def __call__(self,text,add_special_tokens=True,return_offsets_mapping=False):
        out={'input_ids':list(text)+(list('xx') if add_special_tokens else [])}
        if return_offsets_mapping:out['offset_mapping']=[(i,i+1) for i in range(len(text))]
        return out
    def decode(self,tokens):return ''.join(tokens)


def test_shared_windows_fit_limit_and_preserve_source_characters(tmp_path,monkeypatch):
    path=tmp_path/'test.sqlite';db=sqlite3.connect(path)
    db.execute('CREATE TABLE passages(id,work_id,section_id,text,heading,boilerplate,ordinal)')
    text='Ọpọ́n-Ifá\n  poetry line two\n\n'+('Long source text with full context. '*50)
    works={str(i):{'id':str(i),'title':'A book '+str(i),'metadata':{'bookshare_id':bid}} for i,bid in enumerate(pilot.BOOKSHARE_IDS)}
    for wid in works:db.execute('INSERT INTO passages VALUES(?,?,?,?,?,?,?)',(f'p{wid}',wid,f's{wid}',text,'A source heading',0,0))
    db.commit();db.close()
    @contextlib.contextmanager
    def connection():
        x=sqlite3.connect(path);x.row_factory=sqlite3.Row
        try:yield x
        finally:x.close()
    lib=SimpleNamespace(_catalog=lambda:{'works':works},_db=connection)
    tokenizer=CharacterTokenizer();monkeypatch.setattr(pilot,'local_model',lambda:SimpleNamespace(tokenizer=tokenizer))
    found,windows=pilot.make_windows(lib)
    assert len(found)==12
    assert all(w['token_count']<=512 for w in windows)
    for w in windows:
        assert w['text'].split('\n',1)[1]==text[w['char_start']:w['char_end']]
    for wid in works:
        own=[w for w in windows if w['work_id']==wid]
        assert own[0]['char_start']==0 and own[-1]['char_end']==len(text)
        assert all(a['char_end']>=b['char_start'] for a,b in zip(own,own[1:]))
