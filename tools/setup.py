"""Fetch checksum-locked upstream sources and optionally a local Windows toolchain."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache/downloads'
LOCK = json.loads((ROOT / 'vendor-lock.json').read_text())


def fetch(entry):
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / entry['filename']
    if not target.exists():
        request = urllib.request.Request(entry['url'], headers={'User-Agent': 'Link65-firmware-source-setup'})
        temporary = target.with_suffix(target.suffix + '.partial')
        with urllib.request.urlopen(request, timeout=180) as response, temporary.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        temporary.replace(target)
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != entry['sha256']:
        raise RuntimeError(f"Checksum mismatch: {entry['filename']}")
    return target


def extract_source(entry):
    archive_path = fetch(entry)
    target = ROOT / 'qmk' if entry['name'] == 'qmk' else ROOT / 'qmk/lib' / entry['name']
    marker = target / '.link65-pinned-source'
    if marker.is_file():
        if marker.read_text() != entry['sha256']:
            raise RuntimeError(f'Source pin changed; use a fresh qmk directory: {target}')
        return
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path) as archive:
        for member in archive:
            rel = PurePosixPath(*PurePosixPath(member.name).parts[1:])
            if not rel.parts:
                continue
            if entry['name'] == 'qmk':
                if rel.parts[0] == 'keyboards' and not str(rel).startswith('keyboards/owlab/link65'):
                    continue
                if rel.parts[0] in {'docs', 'users', 'tests'}:
                    continue
            dest = target.joinpath(*rel.parts)
            if not dest.resolve().is_relative_to(target.resolve()):
                raise RuntimeError(f'Unsafe archive path: {member.name}')
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.extractfile(member).read())
    marker.write_text(entry['sha256'])


def apply_overlays():
    for source in sorted((ROOT / 'overlays').rglob('*')):
        if source.is_file():
            target = ROOT / 'qmk' / source.relative_to(ROOT / 'overlays')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def prepare_sources():
    # Download independent archives together, then extract the parent before libraries.
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(fetch, LOCK['sources']))
    for entry in LOCK['sources']:
        extract_source(entry)
    apply_overlays()


def prepare_toolchain():
    installer, unpacker = [fetch(entry) for entry in LOCK['windowsToolchain']]
    destination = ROOT / '.cache/innounp'
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(unpacker) as archive:
        for name in archive.namelist():
            if not (destination / name).resolve().is_relative_to(destination.resolve()):
                raise RuntimeError('Unsafe tool archive path')
        archive.extractall(destination)
    runtime = ROOT / '.cache/toolchain'
    if not (runtime / '{app}/usr/bin/bash.exe').is_file():
        runtime.mkdir(parents=True, exist_ok=True)
        with (ROOT / '.cache/toolchain-extraction.log').open('w', encoding='utf-8') as log:
            subprocess.run([str(destination / 'innounp.exe'), '-x', '-b', '-y', '-q', f'-d{runtime}', str(installer)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources-only', action='store_true')
    args = parser.parse_args()
    prepare_sources()
    if not args.sources_only:
        prepare_toolchain()
    print(json.dumps({'sourcesReady': True, 'qmkRevision': LOCK['qmkRevision'],
                      'windowsToolchainPrepared': not args.sources_only, 'deviceAccessed': False}))


if __name__ == '__main__':
    main()
