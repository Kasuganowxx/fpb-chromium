"""Bring a build/src restored from another run's artifact up to date with this commit.

build.py skips patching when build/src already exists, so changes to patches/fingerprint/ since the
resumed run are applied here: reverse the old patch, apply the new one on a scratch copy, and only
overwrite files whose content actually changed (unchanged files keep their mtime, so ninja rebuilds
only what depends on the changed files). Any other change to build inputs cannot be resumed.
Usage: python .github/scripts/resume_sync.py <run_id>   (env GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_SHA)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'build' / 'src'
PATCH_BIN = SRC / 'third_party' / 'git' / 'usr' / 'bin' / 'patch.exe'
FP_DIR = 'patches/fingerprint/'
# Paths that do not affect build/src.
IGNORED = re.compile(r'^(\.github/|README\.md$|LICENSE$|\.gitignore$|devutils/)')


def api(path, raw=False):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
        headers={'Authorization': f"Bearer {os.environ['GITHUB_TOKEN']}",
                 'Accept': 'application/vnd.github.raw' if raw else 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return data if raw else json.loads(data)


def patch_targets(text):
    return set(re.findall(r'^\+\+\+ b/(\S+)', text, re.M)) | set(re.findall(r'^--- a/(\S+)', text, re.M))


def run_patch(tree, patch_file, reverse):
    cmd = [str(PATCH_BIN), '-p1', '--ignore-whitespace', '-i', str(patch_file), '-d', str(tree),
           '--no-backup-if-mismatch', '--batch', '--remove-empty-files']
    if reverse:
        cmd.append('--reverse')
    subprocess.run(cmd, check=True)


def main():
    run_id = sys.argv[1]
    head = os.environ['GITHUB_SHA']
    old = api(f'actions/runs/{run_id}')['head_sha']
    print(f'resume: run {run_id} built {old}, this run builds {head}')
    if old == head:
        return
    changed = [f['filename'] for f in api(f'compare/{old}...{head}')['files']]
    bad = [f for f in changed if not f.startswith(FP_DIR) and not IGNORED.match(f)]
    if bad:
        sys.exit(f'resume: cannot resume run {run_id}: build inputs other than {FP_DIR} changed since {old}: '
                 f'{bad}. Start from scratch (leave resume_run_id empty).')
    fp_changed = sorted(f for f in changed if f.startswith(FP_DIR))
    if not fp_changed:
        return
    series = (ROOT / 'patches' / 'series').read_text(encoding='utf-8').split()
    fp = [s for s in series if s.startswith('fingerprint/')]
    if len(fp) != 1 or series[-1] != fp[0]:
        sys.exit('resume: patches/series must list exactly one fingerprint/ patch, and it must be last.')
    name = 'patches/' + fp[0]
    if any(f != name for f in fp_changed):
        sys.exit(f'resume: only {name} (last in patches/series) may change between resumed runs; changed: {fp_changed}.')

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        old_patch, new_patch, tree = tmp / 'old.patch', tmp / 'new.patch', tmp / 'tree'
        old_patch.write_bytes(api(f'contents/{name}?ref={old}', raw=True))
        shutil.copyfile(ROOT / name, new_patch)
        files = patch_targets(old_patch.read_text(encoding='utf-8')) | patch_targets(new_patch.read_text(encoding='utf-8'))
        for f in files:
            if (SRC / f).exists():
                (tree / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(SRC / f, tree / f)
        run_patch(tree, old_patch, reverse=True)
        run_patch(tree, new_patch, reverse=False)
        for f in sorted(files):
            a, b = SRC / f, tree / f
            if b.exists():
                if not a.exists() or a.read_bytes() != b.read_bytes():
                    a.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(b, a)
                    print(f'resume: updated {f}')
            elif a.exists():
                a.unlink()
                print(f'resume: removed {f}')


if __name__ == '__main__':
    main()
