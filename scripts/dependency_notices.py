"""Generate notices from installed locked runtime dependencies; no network or books."""
from __future__ import annotations
from importlib.metadata import distribution
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def license_files(folder):
    return sorted(p for p in folder.rglob('*') if p.is_file() and p.name.lower().startswith(('license', 'licence', 'copying', 'notice')) and 'node_modules' not in p.relative_to(folder).parts)


def notice_text(text):
    return '\n'.join(line.rstrip() for line in text.splitlines()).rstrip() + '\n'


def generate():
    python_rows, python_text = [], []
    for line in (ROOT / 'requirements.lock.txt').read_text().splitlines():
        match = re.match(r'^([A-Za-z0-9_.-]+)==([^ ;]+)', line)
        if not match: continue
        name, version = match.groups()
        dist = distribution(name)
        if dist.version != version:
            raise ValueError(f'{name}: install locked version {version} before generating release notices.')
        license_name = dist.metadata.get('License-Expression') or dist.metadata.get('License') or ''
        if not license_name or '\n' in license_name or len(license_name) > 120:
            license_name = ', '.join(c.split(' :: ')[-1] for c in dist.metadata.get_all('Classifier', []) if c.startswith('License ::')) or 'See installed license notices'
        python_rows.append(f'| {name} | {version} | {license_name.replace(chr(124), "/")} |')
        texts = []
        for file in dist.files or []:
            if any(part.endswith('.dist-info') for part in file.parts) and (file.name.lower().startswith(('license','licence','copying','notice')) or 'licenses' in file.parts):
                path = Path(dist.locate_file(file))
                if path.is_file(): texts.append(path.read_text(errors='replace'))
        if not texts:
            raw = dist.metadata.get('License')
            texts = [raw] if raw else ['Consult the installed distribution metadata for license terms.']
        python_text.append(f'\n===== {name} {version} =====\n' + '\n\n'.join(texts))
    node_rows, node_text = [], []
    packages = json.loads((ROOT / 'frontend/package-lock.json').read_text())['packages']
    for location, meta in sorted(packages.items()):
        if not location or meta.get('dev'): continue
        folder = ROOT / 'frontend' / location
        manifest = json.loads((folder / 'package.json').read_text()) if (folder / 'package.json').is_file() else {}
        name = manifest.get('name') or location.split('node_modules/')[-1]
        version = meta.get('version', '')
        if manifest.get('version') != version:
            raise ValueError(f'{name}: run npm ci before generating release notices.')
        license_name = meta.get('license') or manifest.get('license') or 'See package license'
        node_rows.append(f'| {name} | {version} | {license_name} |')
        texts = [p.read_text(errors='replace') for p in license_files(folder)] if folder.is_dir() else []
        if not texts: texts = [f'License declared by package: {license_name}. Consult the package distribution for its complete terms.']
        node_text.append(f'\n===== {name} {version} =====\n' + '\n\n'.join(texts))
    folder = ROOT / 'docs/licenses'; folder.mkdir(parents=True, exist_ok=True)
    (folder / 'python-runtime.txt').write_text(notice_text('Python runtime dependency notices\n' + '\n'.join(python_text)))
    (ROOT / 'frontend/public/third-party-notices.txt').write_text(notice_text('Browser runtime dependency notices\n' + '\n'.join(node_text)))
    (ROOT / 'NOTICE.md').write_text('''# Attribution and third-party notices

The Reading Room's original code, agent skills, documentation, SVG mark, and synthetic demonstration text are distributed under the MIT license. Copyright © 2026 Seth Wilson. The geometric SVG mark uses no external imagery; the UI uses system fonts.

Books, acquired source files, and personal research are not included and are not licensed by this project. Synthetic tests may use real publication or contributor names to exercise attribution conventions; their test prose is invented.

Dependencies retain their own licenses. This source release does not relicense them. The generated browser build includes [browser runtime notices](frontend/public/third-party-notices.txt). [Python runtime notices](docs/licenses/python-runtime.txt) accompany this inventory. Development tools are installed separately; their license metadata and notices are in their npm/Python distributions.

Regenerate this inventory after installing the locked dependencies with `.venv/bin/python scripts/dependency_notices.py`, before building the UI. The tables describe the locked release inputs, not every optional local-model dependency.

## Python runtime

| Dependency | Version | License |
| --- | --- | --- |
''' + '\n'.join(python_rows) + '\n\n## Browser runtime\n\n| Dependency | Version | License |\n| --- | --- | --- |\n' + '\n'.join(node_rows) + '\n')
    print(f'Generated notices for {len(python_rows)} Python and {len(node_rows)} browser packages.')

if __name__ == '__main__': generate()
