"""Offline regression of the two linked ARM images. No USB/HID imports.

Runs real timer conversion and post-GPIO debounce instructions. Key-action
tests run action_exec and capture reports at the host driver boundary; the
scheduler, EEPROM and USB hardware are deliberately outside the model.
"""
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import random
import struct
import sys
import zlib

import os
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.build/validation'
OUT.mkdir(parents=True, exist_ok=True)
FW = ROOT
from elf32 import Elf32
from input_scenarios import scenarios, PHYSICAL
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
import unicorn.arm_const as arm

MASK = 0xFFFFFFFF
STOP = 0x08005000
STACK = 0x20004000
ADJUST = (MASK // 100000) * 100000
ADJUST_MS = ADJUST // 100
OLD = ROOT / 'tests/fixtures/v1.0.1/firmware.elf'
NEW = ROOT / os.environ.get('LINK65_TEST_ELF', 'releases/v1.0.2-rc1/firmware.elf')
OLD_BIN = ROOT / 'tests/fixtures/v1.0.1/firmware.bin'
NEW_BIN = ROOT / os.environ.get('LINK65_TEST_BIN', 'releases/v1.0.2-rc1/firmware.bin')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instructions(elf, name):
    a = elf.symbols[name] & ~1
    return list(Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS).disasm(
        elf.read_address(a, elf.symbol_sizes[name]), a))


def reference_state(counter, state):
    offset, last, ms = state
    ticks = (counter - offset) & MASK
    if ticks < last:
        ticks = (ticks - ADJUST) & MASK
        offset = (offset + ADJUST) & MASK
        ms = (ms + ADJUST_MS) & MASK
    return ((ticks * 1000 + 99999) // 100000 + ms) & MASK, (offset, ticks, ms)


class Image:
    def __init__(self, path, nkro=True, mapping=None):
        self.elf = Elf32(path)
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.uc.mem_map(0x08000000, 0x10000)
        self.uc.mem_map(0x20000000, 0x5000)
        for typ, offset, virtual, physical, filesz, memsz, flags, align in self.elf.segments:
            if typ == 1 and filesz:
                self.uc.mem_write(virtual, self.elf.data[offset:offset + filesz])
        self.counter = self.elf.symbols['ch0'] + 0x1C
        self.count = 0
        self.reschedules = 0
        self.reports = []
        self.sleeps = 0
        self.leds = []
        self.last_tick = 0
        self.recent = deque(maxlen=20)
        self.uc.hook_add(UC_HOOK_CODE, self.on_code)
        self.boundaries = {self.elf.symbols['chSchRescheduleS'] & ~1: ('schedule', 0)}
        self.boundaries[self.elf.symbols['led_set'] & ~1] = ('led', 0)
        for name, length in [('send_keyboard', 8), ('send_nkro', 32), ('send_mouse', 6), ('send_extra', 3)]:
            if name in self.elf.symbols:
                self.boundaries[self.elf.symbols[name] & ~1] = (name, length)
        self.boundaries[self.elf.symbols['chThdSleep'] & ~1] = ('sleep', 0)
        for name in ['eeprom_read_byte', 'eeprom_read_word', 'eeprom_read_block']:
            self.boundaries[self.elf.symbols[name] & ~1] = (name, 0)
        self.memory = bytearray(2048)
        keymap = mapping or json.loads((FW / 'firmware/factory-keymap.json').read_text())
        # Current compiled VIA layout: 2048 - 1407 macro bytes - 600 keymap bytes.
        self.memory[41:641] = struct.pack('>300H', *[k for layer in keymap for k in layer])
        self.uc.mem_write(self.elf.symbols['driver'], struct.pack('<I', self.elf.symbols['chibios_driver']))
        self.uc.mem_write(self.elf.symbols['usb_device_state'] + 2, b'\x01')
        self.uc.mem_write(self.elf.symbols['keymap_config'], struct.pack('<H', 0x400 | (0x80 if nkro else 0)))
        ins = instructions(self.elf, 'matrix_scan.isra.0')
        at = next(i for i, x in enumerate(ins) if x.mnemonic == 'bl' and int(x.op_str[1:], 16) == (self.elf.symbols['memcmp'] & ~1))
        self.matrix_entry = ins[at - 3].address
        exits = [i.address for i in ins if i.mnemonic == 'add' and i.op_str == 'sp, #0x14']
        assert len(exits) == 1, exits
        self.matrix_stop = exits[0]
        self.uc.reg_write(arm.UC_ARM_REG_BASEPRI, 0x30)

    def on_code(self, uc, address, size, context):
        self.count += 1
        self.recent.append(address)
        if address not in self.boundaries:
            return
        name, length = self.boundaries[address]
        r0 = uc.reg_read(arm.UC_ARM_REG_R0)
        if name == 'schedule':
            self.reschedules += 1
        elif name == 'sleep':
            self.sleeps += 1
        elif name == 'led':
            self.leds.append(r0)
        elif name == 'eeprom_read_byte':
            assert r0 < len(self.memory)
            uc.reg_write(arm.UC_ARM_REG_R0, self.memory[r0])
        elif name == 'eeprom_read_word':
            assert r0 + 2 <= len(self.memory)
            uc.reg_write(arm.UC_ARM_REG_R0, int.from_bytes(self.memory[r0:r0 + 2], 'little'))
        elif name == 'eeprom_read_block':
            src, n = [uc.reg_read(r) for r in [arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2]]
            assert src + n <= len(self.memory)
            uc.mem_write(r0, bytes(self.memory[src:src + n]))
        else:
            self.reports.append((name, bytes(uc.mem_read(r0, length)).hex()))
        uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR))

    def put32(self, symbol, value):
        self.uc.mem_write(self.elf.symbols[symbol], struct.pack('<I', value & MASK))

    def get32(self, symbol):
        return struct.unpack('<I', self.uc.mem_read(self.elf.symbols[symbol], 4))[0]

    def state(self):
        return tuple(self.get32(n) for n in ['ticks_offset', 'last_ticks', 'ms_offset'])

    def seed(self, state):
        for name, value in zip(['ticks_offset', 'last_ticks', 'ms_offset'], state):
            self.put32(name, value)

    def set_counter(self, ticks):
        self.uc.mem_write(self.counter, struct.pack('<I', ticks & MASK))

    def invoke(self, address, args=(), stop=STOP, locked=True):
        for i in range(13):
            self.uc.reg_write(getattr(arm, f'UC_ARM_REG_R{i}'), 0xA0000000 + i if i >= 4 else 0)
        for i, value in enumerate(args):
            self.uc.reg_write(getattr(arm, f'UC_ARM_REG_R{i}'), value)
        self.uc.reg_write(arm.UC_ARM_REG_SP, STACK)
        self.uc.reg_write(arm.UC_ARM_REG_LR, STOP | 1)
        self.uc.reg_write(arm.UC_ARM_REG_BASEPRI, 0x30 if locked else 0)
        self.count = 0
        try:
            self.uc.emu_start(address | 1, stop, count=100000)
        except Exception as exc:
            raise RuntimeError(f'entry={address:08x} pc={self.uc.reg_read(arm.UC_ARM_REG_PC):08x} '
                               f'r0={self.uc.reg_read(arm.UC_ARM_REG_R0):08x} '
                               f'r1={self.uc.reg_read(arm.UC_ARM_REG_R1):08x} '
                               f'recent={[hex(x) for x in self.recent]}') from exc
        assert self.uc.reg_read(arm.UC_ARM_REG_PC) == stop, hex(self.uc.reg_read(arm.UC_ARM_REG_PC))
        if stop == STOP:
            assert self.uc.reg_read(arm.UC_ARM_REG_SP) == STACK
            for i in range(4, 12):
                assert self.uc.reg_read(getattr(arm, f'UC_ARM_REG_R{i}')) == 0xA0000000 + i
        assert self.uc.reg_read(arm.UC_ARM_REG_BASEPRI) == (0x30 if locked else 0)
        return self.uc.reg_read(arm.UC_ARM_REG_R0)

    def read_timer(self, ticks, locked=True):
        self.set_counter(ticks)
        return self.invoke(self.elf.symbols['timer_read32'], locked=locked)

    def action(self, ticks, index, down, kind=1):
        ms = self.read_timer(ticks) & 0xFFFF
        r0 = index % 15 | (index // 15 << 8) | (ms << 16)
        self.invoke(self.elf.symbols['action_exec'], (r0, kind | (int(down) << 8)))

    def step(self, ticks, raw, actions=False):
        before = bytes(self.uc.mem_read(self.elf.symbols['matrix'], 10))
        self.set_counter(ticks)
        packed = struct.pack('<5H', *raw)
        self.uc.mem_write(STACK + 4, packed)
        self.invoke(self.matrix_entry, stop=self.matrix_stop)
        assert bytes(self.uc.mem_read(STACK + 4, 10)) == packed
        after = bytes(self.uc.mem_read(self.elf.symbols['matrix'], 10))
        values = struct.unpack('<5H', after)
        if actions:
            if before != after:
                old = struct.unpack('<5H', before)
                for row in range(5):
                    for col in range(15):
                        if (old[row] ^ values[row]) & (1 << col):
                            self.action(ticks, row * 15 + col, bool(values[row] & (1 << col)))
            else:
                now = self.read_timer(ticks) & 0xFFFF
                if now != self.last_tick:
                    self.action(ticks, 0, False, kind=0)
                    self.last_tick = now
        return values


def timer_checks():
    old, new = Image(OLD), Image(NEW)
    rng = random.Random(651002)
    values = set(range(0, 1001)) | set(range(MASK - 1000, MASK + 1))
    values.update(rng.randrange(1 << 32) for _ in range(3000))
    checked = 0
    for counter in sorted(values):
        for m in [old, new]:
            m.seed((0, 0, 0))
        a, b = old.read_timer(counter), new.read_timer(counter)
        expected, state = reference_state(counter, (0, 0, 0))
        assert a == b == expected, counter
        assert old.state() == new.state() == state
        checked += 1
    independent = 0
    for i in range(4000):
        counter = rng.randrange(1 << 32)
        state = tuple(rng.randrange(1 << 32) for _ in range(3))
        for m in [old, new]:
            m.seed(state)
        a, b = old.read_timer(counter, locked=i % 2 == 0), new.read_timer(counter, locked=i % 2 == 0)
        expected, after = reference_state(counter, state)
        assert a == b == expected, (counter, state)
        assert old.state() == new.state() == after
        independent += 1
    sequences = [
        [0, 1, 99, 100, 101, 499, 500, 501, MASK - 1, MASK, 0, 1, 100, 101],
        [(0xFFFF0000 + i) & MASK for i in [0, 1, 99, 100, 65500, 65535, 65536, 65537, 65636]],
        [MASK - 20, MASK - 1, 0, 1, MASK - 10, MASK, 0, 1],
    ]
    sequences += [[(start + j * delta) & MASK for j in range(100)] for start, delta in
                  [(0, 97), (MASK - 5000, 101), (0xFFFFFF00, 100000000), (123456789, 4000000000)]]
    chain = 0
    for seq in sequences:
        state = (0, 0, 0xFFFFFFF0)
        old.seed(state); new.seed(state)
        for counter in seq:
            expected, state = reference_state(counter, state)
            assert old.read_timer(counter) == new.read_timer(counter) == expected
            assert old.state() == new.state() == state
            chain += 1
    samples = []
    for counter in [0, 1, 99, 100, 101, 1000, 100000, 0x7FFFFFFF, MASK]:
        row = {'counter': counter}
        for label, m in [('v101', old), ('candidate', new)]:
            m.seed((0, 0, 0)); row[label + 'Return'] = m.read_timer(counter)
            row[label + 'CodeHookVisits'] = m.count
        samples.append(row)
    return {'isolatedValues': checked, 'arbitraryStatesAndLockModes': independent,
            'sequentialWrapCalls': chain, 'totalPairedCalls': checked + independent + chain,
            'schedulerBoundaryStubCalls': [old.reschedules, new.reschedules], 'samples': samples,
            'fullDomainProof': 'For uint32 t=100q+r, 0<=r<100: ceil((1000t)/100000)=q+[r!=0]. Both expressions fit before adding the same uint32 ms offset. No rounding or wrap state changes.'}


def run_pair(events, interval=1000, phase=0, duration=110000, start_ticks=0,
             stalls=(), actions=False, nkro=True, mapping=None, ms_offset=0):
    pair = [Image(OLD, nkro, mapping), Image(NEW, nkro, mapping)]
    for m in pair:
        m.seed((start_ticks, 0, ms_offset))
    held, previous, position, result = set(), (0,) * 5, 0, []
    for at in range(phase, duration + 1, interval):
        if any(a <= at < b for a, b in stalls):
            continue
        while position < len(events) and events[position][0] <= at:
            _, key, down = events[position]
            (held.add if down else held.discard)(key)
            position += 1
        raw = [sum(1 << (key % 15) for key in held if key // 15 == row) for row in range(5)]
        ticks = (start_ticks + at // 10) & MASK
        a, b = [m.step(ticks, raw, actions) for m in pair]
        assert a == b, (at, a, b)
        assert pair[0].state() == pair[1].state(), at
        if actions:
            assert pair[0].reports == pair[1].reports, (at, pair[0].reports, pair[1].reports)
            assert pair[0].leds == pair[1].leds, at
            assert [bytes(m.uc.mem_read(m.elf.symbols['layer_state'], 1)) for m in pair][0] == bytes(pair[1].uc.mem_read(pair[1].elf.symbols['layer_state'], 1))
        if a != previous:
            for row in range(5):
                for col in range(15):
                    if (a[row] ^ previous[row]) & (1 << col):
                        result.append([at, row * 15 + col, int(bool(a[row] & (1 << col)))])
        previous = a
    return {'transitions': result, 'reports': pair[0].reports,
            'finalMatrix': list(previous), 'finalLayer': pair[0].uc.mem_read(pair[0].elf.symbols['layer_state'], 1)[0],
            'modeledSleeps': pair[0].sleeps}


def matrix_checks():
    cases = scenarios()
    fixed, examples = 0, {}
    for name, events in cases.items():
        for interval, phase in [(1000, 0), (1000, 10), (500, 0), (250, 0), (125, 60), (100, 90)]:
            result = run_pair(events, interval, phase)
            fixed += 1
            if interval == 1000 and phase == 0:
                examples[name] = result['transitions']
        print(json.dumps({'matrixCasePassed': name, 'pairedTraces': fixed}), flush=True)
    assert examples['clean'] == [[15000, 0, 1], [55000, 0, 0]], examples['clean']
    assert examples['one_ms_spike'] == []
    assert examples['four_ms_spike'] == []
    rng = random.Random(101002)
    random_count = 0
    for i in range(24):
        held, events = set(), []
        for at in sorted(rng.randrange(1000, 90000) for _ in range(100)):
            k = rng.choice(PHYSICAL); down = k not in held
            (held.add if down else held.discard)(k)
            events.append((at, k, int(down)))
        events += [(100000, k, 0) for k in sorted(held)]
        run_pair(events, interval=[1000, 250, 125][i % 3], duration=140000,
                 start_ticks=[0, MASK - 3000, 6553500, 0x7FFFFFFF][i % 4],
                 ms_offset=[0, 0xFFFFFFF0, 65520][i % 3],
                 stalls=[(30000, 90000)] if i % 4 == 0 else ())
        random_count += 1
    wrap_examples = []
    for offset in [65520, 0xFFFFFFF0]:
        result = run_pair([(14000, 31, 1), (50000, 31, 0)], ms_offset=offset)
        assert result['transitions'] == [[19000, 31, 1], [55000, 31, 0]]
        wrap_examples.append({'msOffset': offset, 'transitions': result['transitions']})
    return {'fixedPairedTraces': fixed, 'randomWrapStallPairedTraces': random_count,
            'explicitMsWrapPairedTraces': len(wrap_examples), 'explicitMsWrapExamples': wrap_examples,
            'examplesAtOneMsScan': examples,
            'realTimerConversionExecuted': True,
            'scope': 'Raw input supplied after GPIO collection; both images execute their linked timer and debounce code at identical controlled 100kHz ticks. CPU runtime is not modeled.'}


def action_checks():
    cases = {
        'A_press_release': [(10000, 31, 1), (50000, 31, 0)],
        'shift_A': [(10000, 45, 1), (20000, 31, 1), (50000, 31, 0), (60000, 45, 0)],
        'ctrl_C': [(10000, 60, 1), (20000, 48, 1), (50000, 48, 0), (60000, 60, 0)],
        'Fn_1': [(10000, 59, 1), (20000, 1, 1), (50000, 1, 0), (60000, 59, 0)],
        'Fn_release_before_other_key': [(10000, 59, 1), (20000, 1, 1), (50000, 59, 0), (60000, 1, 0)],
        'all_67_virtual_positions': [(10000, k, 1) for k in PHYSICAL] + [(60000, k, 0) for k in PHYSICAL],
        'ten_basic_keys': [(10000, k, 1) for k in range(15, 25)] + [(60000, k, 0) for k in range(15, 25)],
    }
    results = []
    for nkro in [False, True]:
        for start, ms_offset in [(0, 0), (MASK - 3000, 0), (0, 65520), (0, 0xFFFFFFF0)]:
            for name, events in cases.items():
                result = run_pair(events, duration=100000, start_ticks=start,
                                  ms_offset=ms_offset, actions=True, nkro=nkro)
                assert result['reports'], (name, nkro)
                assert result['finalMatrix'] == [0] * 5
                assert result['finalLayer'] == 0
                assert result['modeledSleeps'] == 0
                results.append({'scenario': name, 'nkro': nkro, 'startTicks': start, 'msOffset': ms_offset,
                                'reportCount': len(result['reports']), 'reports': result['reports']})
    a = next(x for x in results if x['scenario'] == 'A_press_release' and x['nkro'] and x['startTicks'] == 0)
    down, up = [bytes.fromhex(x[1]) for x in a['reports']]
    assert down[0] == 6 and down[2] & (1 << 4) and up[2:] == bytes(30)
    fn = next(x for x in results if x['scenario'] == 'Fn_1' and x['nkro'] and x['startTicks'] == 0)
    f1 = bytes.fromhex(fn['reports'][0][1])
    assert f1[2 + 0x3A // 8] & (1 << (0x3A % 8)), fn
    return {'pairedActionTraces': len(results), 'results': results,
            'scope': 'Linked timer, post-GPIO debounce, action_exec, layer and modifier processing. Identical row/column event order supplied by harness; EEPROM reads, LED output and host report sinks are modeled. USB transfer and OS interpretation are excluded.'}


def image_checks():
    release = json.loads((ROOT / 'releases/v1.0.2-rc1/manifest.json').read_text(encoding='utf-8'))
    for relative, expected in release['overlaysSha256'].items():
        assert digest(ROOT / relative) == expected, f'Release source hash differs: {relative}'
    old, new = Elf32(OLD), Elf32(NEW)
    binary = NEW_BIN.read_bytes(); payload = binary[:-16]
    assert digest(OLD_BIN) == 'ca5a6834681fc149ca89903452a5935b1b39e2daa4de8f4ca94d9956528dd5a1'
    release, pid, vid, dfu, signature, length, crc = struct.unpack('<4H3sBI', binary[-16:])
    assert (pid, vid, signature, length) == (0x2220, 0x1688, b'UFD', 16)
    assert zlib.crc32(binary[:-4]) ^ MASK == crc
    segments = []
    for typ, offset, virtual, physical, filesz, memsz, flags, align in new.segments:
        if typ != 1:
            continue
        if 0x08000000 <= physical < 0x09000000 and filesz:
            assert 0x08006000 <= physical and physical + filesz <= 0x0800F000
            assert payload[physical - 0x08006000:physical - 0x08006000 + filesz] == new.data[offset:offset + filesz]
            segments.append({'start': hex(physical), 'bytes': filesz})
        if 0x20000000 <= virtual < 0x30000000:
            assert virtual + memsz <= 0x20005000
    assert len(payload) == max(int(x['start'], 16) + x['bytes'] for x in segments) - 0x08006000
    sp, reset = struct.unpack('<II', payload[:8])
    assert sp == new.symbols['__main_stack_end__'] and sp % 8 == 0
    assert reset & 1 and 0x08006000 <= reset < 0x0800F000
    same = []
    for name in ['DeviceDescriptor', 'ConfigurationDescriptor', 'RawReport', 'keymaps']:
        assert old.read_address(old.symbols[name], old.symbol_sizes[name]) == new.read_address(new.symbols[name], new.symbol_sizes[name]), name
        same.append(name)
    main = instructions(new, 'main')
    assert any(x.mnemonic == 'movw' and x.op_str == 'r1, #0x2cf' for x in main)
    timer_old, timer_new = instructions(old, 'timer_read32'), instructions(new, 'timer_read32')
    old_call = old.symbols['__aeabi_uldivmod'] & ~1
    assert any(x.mnemonic == 'bl' and x.op_str == hex(old_call).replace('0x', '#0x') for x in timer_old)
    assert any(x.mnemonic == 'udiv' for x in timer_new)
    assert not any(x.mnemonic == 'bl' and int(x.op_str[1:], 16) == (new.symbols['__aeabi_uldivmod'] & ~1) for x in timer_new)
    for label, elf in [('v101', old), ('candidate', new)]:
        text = '\n'.join(f'{x.address:08x}: {x.mnemonic} {x.op_str}' for x in instructions(elf, 'timer_read32'))
        (OUT / f'{label}-timer-disassembly.txt').write_text(text + '\n', encoding='utf-8')
    return {'oldSha256': digest(OLD_BIN), 'candidateSha256': digest(NEW_BIN),
            'oldBytes': OLD_BIN.stat().st_size, 'candidateBytes': len(binary),
            'oldElfSections': old.sizes(), 'candidateElfSections': new.sizes(),
            'timerSymbolBytes': [old.symbol_sizes['timer_read32'], new.symbol_sizes['timer_read32']],
            'timer64BitDivideCallRemoved': True, 'timer32BitUdivPresent': True,
            'periodicTickHzUnchanged': 100000, 'identicalTables': same,
            'flashSegments': segments, 'bootloaderAndSettingsRangesExcluded': True,
            'dfuSuffixCrcValid': True}


def main():
    result = {'version': '1.0.2-rc1', 'baselineVersion': '1.0.1',
              'physicalDeviceAccessed': False, 'firmwareFlashed': False,
              'cpuWallTimeOrContactLatencyMeasured': False}
    result['image'] = image_checks()
    print(json.dumps({'imageChecksPassed': True}), flush=True)
    result['timer'] = timer_checks()
    print(json.dumps({'timerPairedCallsPassed': result['timer']['totalPairedCalls']}), flush=True)
    result['matrix'] = matrix_checks()
    print(json.dumps({'matrixChecksPassed': True}), flush=True)
    result['actions'] = action_checks()
    print(json.dumps({'pairedActionTracesPassed': result['actions']['pairedActionTraces']}), flush=True)
    result['passed'] = True
    path = OUT / 'Link65-v1.0.2-rc1-offline-validation.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'candidateSha256': result['image']['candidateSha256'],
                      'output': path.name}), flush=True)


if __name__ == '__main__':
    main()
