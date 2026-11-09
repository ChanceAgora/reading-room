"""Check local Markdown links in the publishable documentation and skill bundle."""
from pathlib import Path
import re
import sys
from urllib.parse import unquote
from check_public_release import ROOT, candidates

errors = []
public = set(candidates())
for name in sorted(public):
    path = ROOT / name
    if path.suffix != '.md': continue
    content = re.sub(r'```.*?```', '', path.read_text(), flags=re.S)
    for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)', content):
        target = unquote(target.strip('<>').split('#')[0])
        if not target or '://' in target or target.startswith(('mailto:', 'codex:')): continue
        dest = (path.parent / target).resolve()
        if not dest.is_relative_to(ROOT) or not dest.exists():
            errors.append(f'{name}: broken/nonportable link {target}')
        elif dest.is_file() and dest.relative_to(ROOT).as_posix() not in public:
            errors.append(f'{name}: link points outside public release: {target}')
if errors:
    print('\n'.join(errors), file=sys.stderr); raise SystemExit(1)
print('Local documentation and skill links passed.')
