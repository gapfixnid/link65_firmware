"""Targeted Link65 updater. Inspection is default; --flash is required to write.

No mass erase, bootloader erase, option-byte changes or protection removal.
Use only the expected bootloader VID/PID, alternate 0 and application origin.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
IMAGES={
    'c33fdae03fe7e41e358c69ca560c54299c52e1d5d9b4a0cd95017332ac148285':'Link65 Studio v1.0.2-rc1 (timer optimization)',
    'ca5a6834681fc149ca89903452a5935b1b39e2daa4de8f4ca94d9956528dd5a1':'Link65 Studio v1.0.1',
    '4c9a21d949e8120cda52e4ad8180b85ccc636d72ce16e7d76a9e9e686024b130':'Owlab official VIA V3 rollback',
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--dfu-util',type=Path,default=ROOT/'.cache/toolchain/{app}/opt/qmk/bin/dfu-util.exe')
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--log',type=Path,required=True)
    parser.add_argument('--flash',action='store_true')
    args=parser.parse_args()
    binary=args.image.read_bytes();digest=hashlib.sha256(binary).hexdigest()
    if digest not in IMAGES:raise SystemExit('Image hash is not a prepared Link65 firmware image')
    if len(binary)>0x9000:raise SystemExit('Image exceeds reserved application area')
    report={'at':datetime.now(timezone.utc).isoformat(),'image':str(args.image.resolve()),'sha256':digest,
        'name':IMAGES[digest],'flashRequested':args.flash,'address':'0x08006000','alternate':0,'device':'1688:2220'}
    env=os.environ.copy()
    runtime=ROOT/'.cache/toolchain/{app}'
    env['PATH']=os.pathsep.join([str(runtime/'mingw64/bin'),str(runtime/'usr/bin'),env.get('PATH','')])
    process=subprocess.run([str(args.dfu_util),'-l','-d','1688:2220,1688:2220'],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
    report['listingExitCode']=process.returncode;report['listing']=process.stdout+process.stderr
    matches=re.findall(r'Found DFU: \[1688:2220\].*',report['listing'],re.I)
    alternates=[x for x in matches if re.search(r'\balt=0\b',x)]
    report['matchingAlternate0']=len(alternates)
    if args.flash:
        if not args.backup or not args.backup.is_file():raise SystemExit('A saved current settings backup is required')
        backup=json.loads(args.backup.read_text(encoding='utf-8-sig'))
        if (backup.get('format'),backup.get('device',{}).get('vid'),backup.get('device',{}).get('pid'))!=('link65-control-backup',0x4f53,0x4c49):
            raise SystemExit('Backup does not identify Link65')
        if process.returncode or len(alternates)!=1:
            report['outcome']='not-flashed-no-unique-accessible-dfu-target'
        else:
            # Stay in DFU for exact readback; leave is a separate command after
            # verification. A USB disconnect during leave must not masquerade
            # as a failed firmware transfer.
            command=[str(args.dfu_util),'-a','0','-d','1688:2220,1688:2220','-s','0x08006000','-D',str(args.image.resolve())]
            result=subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
            report.update(downloadExitCode=result.returncode,download=result.stdout+result.stderr,
                outcome='download-completed-still-in-dfu' if result.returncode==0 else 'download-failed')
    else:report['outcome']='inspection-only'
    args.log.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return 0 if not args.flash or report['outcome']=='download-completed-still-in-dfu' else 1


if __name__=='__main__':sys.exit(main())
