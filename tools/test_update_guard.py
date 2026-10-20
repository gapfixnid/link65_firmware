"""Exercise the updater's device selection without opening USB hardware."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import update_firmware

ROOT=Path(__file__).resolve().parent
IMAGE=ROOT.parent/'releases/v1.0.2-rc1/firmware.bin'
TARGET='Found DFU: [1688:2220] ver=0200, devnum=9, cfg=1, intf=0, path="1-2", alt=0, name="Link65", serial=""\n'


class Guard(unittest.TestCase):
    def invoke(self,listing,flash=True,exitcode=0):
        with tempfile.TemporaryDirectory(prefix='link65-guard-') as folder:
            root=Path(folder);backup=root/'backup.json';log=root/'log.json'
            backup.write_text(json.dumps({'format':'link65-control-backup','device':{'vid':0x4f53,'pid':0x4c49}}))
            arguments=['update_firmware.py','--image',str(IMAGE),'--log',str(log),'--backup',str(backup)]+(['--flash'] if flash else [])
            results=[subprocess.CompletedProcess([],exitcode,listing,''),subprocess.CompletedProcess([],0,'Download done.','')]
            with patch.object(sys,'argv',arguments),patch.object(update_firmware.subprocess,'run',side_effect=results) as run,contextlib.redirect_stdout(io.StringIO()):
                code=update_firmware.main()
            return code,json.loads(log.read_text()),[call.args[0] for call in run.call_args_list]

    def test_no_write_without_explicit_flash(self):
        code,report,commands=self.invoke(TARGET,False)
        self.assertEqual(code,0);self.assertEqual(len(commands),1)
        self.assertEqual(report['outcome'],'inspection-only')

    def test_wrong_missing_and_multiple_devices_are_refused(self):
        for listing in ['',TARGET.replace('1688:2220','0483:df11'),TARGET+TARGET,TARGET.replace('alt=0','alt=1')]:
            with self.subTest(listing=listing):
                code,report,commands=self.invoke(listing)
                self.assertEqual(code,1);self.assertEqual(len(commands),1)
                self.assertTrue(report['outcome'].startswith('not-flashed'))

    def test_listing_error_is_refused_even_with_target_text(self):
        code,report,commands=self.invoke(TARGET,exitcode=74)
        self.assertEqual(code,1);self.assertEqual(len(commands),1)

    def test_valid_target_uses_only_fixed_application_address(self):
        code,report,commands=self.invoke(TARGET)
        self.assertEqual(code,0);self.assertEqual(len(commands),2)
        self.assertEqual(commands[1][1:7],['-a','0','-d','1688:2220,1688:2220','-s','0x08006000'])
        self.assertEqual(commands[1][7:],['-D',str(IMAGE.resolve())])


if __name__=='__main__':unittest.main()
