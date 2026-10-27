"""Check local documentation links and the literal README/Compose install contract."""
from pathlib import Path
import json
import tomllib
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.venv', 'node_modules', '.project-local', '.data', 'test-results', 'dist'}
errors = []
for file in ROOT.rglob('*.md'):
    if EXCLUDED.intersection(file.relative_to(ROOT).parts) or file.name == 'AGENTS.override.md':
        continue
    text = re.sub(r'```.*?```', '', file.read_text(), flags=re.S)
    for target in re.findall(r'!?\[[^]\n]*\]\(([^\s)]+)\)', text):
        if re.match(r'^[\w+.-]+:', target) or target.startswith('#'):
            continue
        destination = (file.parent / unquote(target.split('#')[0])).resolve()
        if not destination.exists():
            errors.append(f'{file.relative_to(ROOT)}: missing local link {target}')
readme = (ROOT / 'README.md').read_text()
compose_example = re.search(r'```yaml\n(.*?)```', readme, re.S)
if not compose_example or compose_example[1].strip() != (ROOT / 'docker-compose.yml').read_text().strip():
    errors.append('README quick-start Compose must exactly match docker-compose.yml')
for file in ['AGENTS.override.md', '.project-local/CONTEXT.md', '.env', '.env.production',
             'frontend/.env.local', 'private.pem', 'config/secret.key']:
    if subprocess.run(['git', 'check-ignore', '-q', file], cwd=ROOT).returncode:
        errors.append(f'Private path must be ignored: {file}')
version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
if not re.fullmatch(r'0\.0\.\d+', version):
    errors.append('Release numbering must follow the owner-approved 0.0.X sequence')
versions = {
    'backend': re.search(r'__version__ = "([^"\n]+)"', (ROOT / 'backend/sillage/__init__.py').read_text())[1],
    'Docker': re.search(r'^ARG VERSION=(.+)$', (ROOT / 'Dockerfile').read_text(), re.M)[1],
    'frontend': json.loads((ROOT / 'frontend/package.json').read_text())['version'],
    'npm lock': json.loads((ROOT / 'frontend/package-lock.json').read_text())['packages']['']['version'],
    'uv lock': next(p['version'] for p in tomllib.loads((ROOT / 'uv.lock').read_text())['package'] if p['name'] == 'sillage'),
}
for artifact, value in versions.items():
    if value != version:
        errors.append(f'{artifact} version must match pyproject.toml')
if errors:
    raise SystemExit('\n'.join(errors))
print('Documentation links, copy-ready Compose, release versions and private-path exclusions pass.')
