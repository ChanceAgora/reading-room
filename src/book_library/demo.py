"""A disposable, invented book for the public quickstart; never uses personal data."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape
from zipfile import ZipFile

from .service import Library


class DemoLibrary(Library):
    def search(self, query, **kwargs):
        return super().search(query, **{**kwargs, 'engine': 'exact'})

    def sync(self, *args, **kwargs):
        return super().sync(*args, **{**kwargs, 'semantic': False})


def create_demo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'Example Author - The River and the Thread' / 'The River and the Thread.docx'
    path.parent.mkdir()
    paragraphs = [('Heading1', 'The River and the Thread'), ('', 'Example Author'),
        ('', 'An original fictional demonstration book. Reading Room Examples, 2026.'),
        ('Heading1', 'A gathering'), ('', 'Copper birds gather beside the river. A thread connects their stories.'),
        ('', 'The river carries yesterday’s rain.\nThe path makes room for another traveler.'),
        ('Heading1', 'The shared table'), ('', 'Silver bells mark the morning. Neighbors bring bread and stories to a shared table.'),
        ('', 'Careful readers distinguish a quotation from an interpretation. This invented book is safe to use in demonstrations.')]
    elements = []
    for style, text in paragraphs:
        properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
        runs = '<w:br/>'.join(f'<w:t xml:space="preserve">{escape(line)}</w:t>' for line in text.split('\n'))
        elements.append(f'<w:p>{properties}<w:r>{runs}</w:r></w:p>')
    namespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    with ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('word/document.xml', f'<w:document xmlns:w="{namespace}"><w:body>{"".join(elements)}</w:body></w:document>')
        archive.writestr('word/styles.xml', f'<w:styles xmlns:w="{namespace}"><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style></w:styles>')
    lib = DemoLibrary(root)
    from .onboarding import initialize
    initialize(lib, timezone='UTC')
    from .intake_registration import register_intake
    register_intake(lib, path.parent, {'provider': 'local', 'title': 'The River and the Thread', 'authors': ['Example Author']})
    lib.sync(semantic=False)
    return lib


def create_demo_app(lib):
    from .web import create_app
    from fastapi.responses import JSONResponse
    app = create_app(lib, enable_intake_worker=False)
    # All POST/PATCH/PUT/DELETE operations are blocked in the disposable public
    # demo, including review actions. Browsing and exact GET search remain useful
    # even if the invoking shell has real provider credentials.
    @app.middleware('http')
    async def demo_read_only(request, call_next):
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            # The normal search UI uses POST even for unconfigured exact search.
            if request.method == 'POST' and request.url.path in {'/search', '/api/ui/search'}:
                return await call_next(request)
            return JSONResponse({'error': 'This disposable demo is read-only. Start your own library to save changes or enable AI.'}, status_code=403)
        return await call_next(request)
    return app


def serve(port=18768):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Choose a port from 1 to 65535.')
    from .onboarding import port_in_use
    if port_in_use('127.0.0.1', port):
        raise ValueError('The demo port is already in use; choose another with --port.')
    import uvicorn
    with TemporaryDirectory(prefix='reading-room-demo-') as folder:
        lib = create_demo(Path(folder))
        lib._local_base_url = f'http://127.0.0.1:{port}'
        print(f'Synthetic demo: {lib._local_base_url}\nSearch for copper birds. No personal books or paid providers are used.\nPress Control-C to stop; the temporary library is then removed.', flush=True)
        uvicorn.run(create_demo_app(lib), host='127.0.0.1', port=port)
