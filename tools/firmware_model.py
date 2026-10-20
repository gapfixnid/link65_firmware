"""Execute the built firmware's VIA dispatch in Unicorn; replace EEPROM I/O.

No physical USB/flash device is opened. This deliberately excludes the flash
journal and USB driver: protocol, keymap reset, macro and custom handlers execute
the actual linked Cortex-M3 instructions.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
import os

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
import unicorn.arm_const as arm

ROOT=Path(__file__).resolve().parents[1]
from elf32 import Elf32


class FirmwareModel:
    def __init__(self):
        self.elf=Elf32(ROOT/os.environ.get('LINK65_TEST_ELF','releases/v1.0.2-rc1/firmware.elf'))
        self.uc=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
        self.uc.mem_map(0x08000000,0x10000)
        self.uc.mem_map(0x20000000,0x5000)
        for typ,offset,address,physical,filesz,memsz,flags,align in self.elf.segments:
            if typ==1 and filesz:self.uc.mem_write(address,self.elf.data[offset:offset+filesz])
        # Only these peripheral pages are mapped, for the explicit reset test.
        self.uc.mem_map(0x40006000,0x1000)
        self.uc.mem_map(0xe000e000,0x1000)
        self.memory=bytearray(2048)
        self.replies=[]
        self.record=[]
        self.eeprom_calls=0
        self.allow_reset=False
        self.reset_requested=False
        self.stack=0x20004b00
        self.packet=self.stack+0x10
        self.sender=self.elf.symbols['host_raw_hid_send.constprop.0']&~1
        self.uc.hook_add(UC_HOOK_CODE,self.on_reply,begin=self.sender,end=self.sender)
        for name in ['eeprom_read_byte','eeprom_read_word','eeprom_read_block','eeprom_update_byte','eeprom_update_word','eeprom_write_block']:
            address=self.elf.symbols[name]&~1
            self.uc.hook_add(UC_HOOK_CODE,self.on_eeprom,user_data=name,begin=address,end=address)
        sleep=self.elf.symbols['chThdSleep']&~1
        self.uc.hook_add(UC_HOOK_CODE,self.skip_function,begin=sleep,end=sleep)
        self.uc.hook_add(UC_HOOK_MEM_WRITE,self.on_write)
        binary=(ROOT/os.environ.get('LINK65_TEST_BIN','releases/v1.0.2-rc1/firmware.bin')).read_bytes()
        # Compiler layout can change between releases. Locate the packet-byte
        # load inside the ELF's main function, then require a unique match.
        signature=bytes.fromhex('9df81030')  # ldrb.w r3, [sp, #0x10]
        main=self.elf.symbols['main']&~1
        body=self.elf.read_address(main,self.elf.symbol_sizes['main'])
        candidates=[main+i for i in range(len(body)-3) if body[i:i+4]==signature]
        assert len(candidates)==1, candidates
        self.dispatch=candidates[0]
        self.binary_sha256=hashlib.sha256(binary).hexdigest()

    def skip_function(self,uc,address,size,context):
        uc.reg_write(arm.UC_ARM_REG_PC,uc.reg_read(arm.UC_ARM_REG_LR))

    def on_reply(self,uc,address,size,context):
        self.replies.append(bytes(uc.mem_read(uc.reg_read(arm.UC_ARM_REG_R0),32)))
        if self.allow_reset:self.skip_function(uc,address,size,context)
        else:uc.emu_stop()

    def on_write(self,uc,access,address,size,value,context):
        if address==0xe000ed0c and value&4:
            self.reset_requested=True
            uc.emu_stop()

    def on_eeprom(self,uc,address,size,name):
        self.eeprom_calls+=1
        a,b,n=[uc.reg_read(reg) for reg in [arm.UC_ARM_REG_R0,arm.UC_ARM_REG_R1,arm.UC_ARM_REG_R2]]
        if name=='eeprom_read_block':
            assert b+n<=len(self.memory)
            uc.mem_write(a,bytes(self.memory[b:b+n]))
        elif name=='eeprom_write_block':
            assert b+n<=len(self.memory)
            self.memory[b:b+n]=uc.mem_read(a,n)
        elif name.startswith('eeprom_read'):
            count=1 if name.endswith('byte') else 2
            assert a+count<=len(self.memory)
            uc.reg_write(arm.UC_ARM_REG_R0,int.from_bytes(self.memory[a:a+count],'little'))
        else:
            count=1 if name.endswith('byte') else 2
            assert a+count<=len(self.memory)
            self.memory[a:a+count]=(b&((1<<(count*8))-1)).to_bytes(count,'little')
        self.skip_function(uc,address,size,name)

    def exchange(self,command,args=()):
        request=(bytes([command])+bytes(args)).ljust(32,b'\0')
        assert len(request)==32
        self.replies=[]
        for i in range(13):self.uc.reg_write(getattr(arm,f'UC_ARM_REG_R{i}'),0)
        self.uc.reg_write(arm.UC_ARM_REG_SP,self.stack)
        self.uc.reg_write(arm.UC_ARM_REG_R6,self.packet)
        self.uc.mem_write(self.packet,request)
        try:self.uc.emu_start(self.dispatch|1,0,count=100000)
        except Exception as exc:raise RuntimeError(f'VIA {command:02x} at PC={self.uc.reg_read(arm.UC_ARM_REG_PC):08x}: {exc}') from exc
        assert self.replies,(command,args,hex(self.uc.reg_read(arm.UC_ARM_REG_PC)))
        result=self.replies[0]
        self.record.append({'command':command,'args':list(args),'response':list(result)})
        return result

    def set_matrix(self,values):
        self.uc.mem_write(self.elf.symbols['matrix'],struct.pack('<5H',*values))


def main():
    model=FirmwareModel()
    checks={}
    for command,args in [(1,[]),(2,[6]),(2,[4]),(2,[0x7e]),(12,[]),(13,[]),(17,[])]:
        response=model.exchange(command,args)
        checks[f'{command:02x}:'+bytes(args).hex()]=response.hex(' ')
    print(json.dumps(checks,indent=2),flush=True)
    model.exchange(6)
    model.exchange(16)
    (ROOT/'.build').mkdir(exist_ok=True)
    (ROOT/'.build/compiled-initial-fixtures.json').write_text(json.dumps(model.record),encoding='utf-8')
    print(json.dumps({'reset_commands':'passed','eeprom_calls':model.eeprom_calls,'binary_sha256':model.binary_sha256}),flush=True)


if __name__=='__main__':main()
