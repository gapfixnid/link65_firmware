"""Compile the tracked overlays; never invoke a flashing target."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from setup import apply_overlays

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'qmk'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', type=Path, default=ROOT / '.cache/toolchain/{app}',
                        help='Extracted QMK MSYS application directory containing usr/bin/bash.exe')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--require-release-match', action='store_true')
    args = parser.parse_args()
    if not (SOURCE / '.link65-pinned-source').is_file():
        raise SystemExit('Prepare sources with python tools/setup.py first.')
    apply_overlays()
    destination = ROOT / '.build/current'
    destination.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(QMK_HOME=str(SOURCE), QMK_USERSPACE=str(ROOT / '.cache/no-userspace'))
    if os.name == 'nt':
        bash = args.toolchain.resolve() / 'usr/bin/bash.exe'
        if not bash.is_file():
            raise SystemExit('Prepare the Windows toolchain with python tools/setup.py.')
        env.update(MSYSTEM='MINGW64', CHERE_INVOKING='1')
        (args.toolchain / 'tmp').mkdir(exist_ok=True)
        command = [str(bash), '--noprofile', '--norc', '-c',
                   'PATH=/opt/qmk/bin:/mingw64/bin:/usr/bin make owlab/link65/hotswap:studio -j4 SKIP_VERSION=yes']
    else:
        command = ['make', 'owlab/link65/hotswap:studio', '-j4', 'SKIP_VERSION=yes']
    log_path = destination / 'build.log'
    with log_path.open('w', encoding='utf-8') as log:
        code = subprocess.run(command, cwd=SOURCE, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    if code:
        print(log_path.read_text(encoding='utf-8', errors='replace')[-8000:])
        raise SystemExit(code)
    for suffix in ['bin', 'elf', 'map']:
        shutil.copyfile(SOURCE / f'.build/owlab_link65_hotswap_studio.{suffix}', destination / f'firmware.{suffix}')
    digest = hashlib.sha256((destination / 'firmware.bin').read_bytes()).hexdigest()
    expected = json.loads((ROOT / 'releases/v1.0.2-rc1/manifest.json').read_text())['sha256']
    report = {'compiled': True, 'sha256': digest, 'matchesTrackedRelease': digest == expected, 'deviceAccessed': False}
    (destination / 'build-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    if args.require_release_match and digest != expected:
        raise SystemExit('Built bytes differ from the tracked release; inspect .build/current/build-result.json.')
    if args.verify:
        env.update(LINK65_TEST_ELF='.build/current/firmware.elf', LINK65_TEST_BIN='.build/current/firmware.bin')
        subprocess.run([sys.executable, str(ROOT / 'tools/verify_timer.py')], cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    main()
