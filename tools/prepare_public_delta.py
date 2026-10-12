"""Apply an explicit text delta to the existing sanitized Git object area; never push."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / 'build/public-history-cleaning'
PUBLIC_GIT = AREA / 'repo.git'
# Stable public-history anchor verified from GitHub main; never use a private recovery commit here.
PUBLIC_SEED = '2f430c61a2eba4985698de2bc570166b5f0837e5'


def git(*args, public=False, env=None, data=None):
    command = ['git']
    if public:
        command.append('--git-dir=' + str(PUBLIC_GIT))
    return subprocess.check_output(command + list(args), cwd=ROOT, env=env, input=data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-base', required=True, help='Local half of the recorded baseline pair')
    parser.add_argument('--local-tip', default='HEAD', help='Committed local work; excludes dirty files')
    parser.add_argument('--public-base', required=True, help='Public half of the same baseline pair')
    parser.add_argument('paths', nargs='+', help='Explicit reviewed text paths; no glob or whole-tree export')
    args = parser.parse_args()
    paths = list(dict.fromkeys(args.paths))
    withheld = set(json.loads((AREA / 'withheld-current-paths-private.json').read_text(encoding='utf-8')))
    for name in paths:
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
                or name != path.as_posix() or name in withheld
                or path.parts[0] in {'.git', 'build', 'dist', 'data'}
                or name == 'app/config.json' or path.name.startswith('.env')
                or path.suffix.lower() not in {'.py', '.cs', '.csproj', '.props', '.js', '.ts',
                    '.tsx', '.html', '.css', '.md', '.json', '.toml', '.yml', '.yaml', '.txt',
                    '.ps1', '.bat', '.spec'}):
            raise ValueError('Not an approved public text path: ' + name)
    if git('config', '--get', 'remote.origin.pushurl').strip() != b'disabled://private-recovery-history':
        raise ValueError('Private-history push protection must remain enabled')
    local_base = git('rev-parse', args.local_base + '^{commit}').decode().strip()
    local_tip = git('rev-parse', args.local_tip + '^{commit}').decode().strip()
    public_base = git('rev-parse', args.public_base + '^{commit}', public=True).decode().strip()
    git('merge-base', '--is-ancestor', PUBLIC_SEED, public_base, public=True)
    stat = git('diff', '--numstat', local_base, local_tip, '--', *paths)
    if any(line.startswith(b'-\t') for line in stat.splitlines()):
        raise ValueError('Binary changes require separate privacy review')
    patch = git('diff', '--no-ext-diff', '--no-textconv', '--no-renames',
                local_base, local_tip, '--', *paths)
    patch.decode('utf-8')  # Refuse non-text encodings instead of copying opaque bytes.
    for line in (AREA / 'replace-identifiers-private.txt').read_bytes().splitlines():
        if not line:
            continue
        old, separator, new = line.partition(b'==>')
        if not separator or not old or old.startswith((b'regex:', b'glob:')):
            raise ValueError('Unsupported privacy replacement rule')
        if old.startswith(b'literal:'):
            old = old[len(b'literal:'):]
        patch = patch.replace(old, new)
    if (any(line == b'GIT binary patch' or line.startswith(b'Binary files ')
            for line in patch.splitlines()) or b'\x00' in patch):
        raise ValueError('Only reviewed text deltas can be exported')
    patch_path = AREA / 'next-public.patch'
    patch_path.write_bytes(patch)
    env = dict(os.environ, GIT_INDEX_FILE=str(AREA / 'next-public.index'))
    git('read-tree', public_base, public=True, env=env)
    if patch:
        # No --3way: a conflict stops here; no private blob/commit is imported.
        git('apply', '--cached', '--check', str(patch_path), public=True, env=env)
        git('apply', '--cached', str(patch_path), public=True, env=env)
    tree = git('write-tree', public=True, env=env).decode().strip()
    result = dict(localBase=local_base, localTip=local_tip, publicBase=public_base,
                  publicTree=tree, paths=paths)
    (AREA / 'next-public.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
