"""Public local-only intake can request bounded paid review later, explicitly."""
from fastapi.testclient import TestClient
from book_library.service import Library
from book_library.web import create_app
from book_library.onboarding import initialize
from book_library import intake, public_config
from test_service import docx

ORIGIN='http://127.0.0.1:8765'


def test_later_review_requires_budget_and_protected_explicit_action(tmp_path):
    lib=Library(tmp_path/'books')
    initialize(lib,timezone='UTC')
    source=docx(lib.root/'Example'/'book.docx', [('Heading1','A meeting'), 'Copper birds gather by the river.'])
    job=lib.intake(source.parent,local_only=True)
    for _ in range(8):
        if not intake.run_next(lib):break
    with TestClient(create_app(lib),base_url=ORIGIN) as client:
        path='/api/ui/intake/'+job['id']
        data=client.get(path).json()['data']
        assert data['job']['review_label']=='Not requested'
        assert data['can_request_review']
        fields={'version':str(data['job']['version'])}
        csrf=client.get('/api/ui/bootstrap').json()['csrf']
        assert client.post(path+'/review',json={'fields':fields}).status_code==403
        headers={'Origin':ORIGIN,'X-CSRF-Token':csrf}
        rejected=client.post(path+'/review',json={'fields':fields},headers=headers)
        assert rejected.status_code==409
        assert 'Accept spending limits' in rejected.json()['data']['error']
        assert not lib.intake_status(job['id'])['authorization']['review']
        public_config.accept_budget(lib,approval_evidence='Synthetic user explicitly accepts limits')
        accepted=client.post(path+'/review',json={'fields':fields},headers=headers)
        assert accepted.status_code==200
        data=client.get(accepted.json()['redirect'].replace('/intake/','/api/ui/intake/',1)).json()['data']
        assert not data['can_request_review']
        assert data['job']['authorization']['review']=='every_indexed_heading'
        assert not (lib.state/'costs.jsonl').exists()
