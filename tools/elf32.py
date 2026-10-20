"""Minimal little-endian ELF reader for local firmware validation."""
from pathlib import Path
import struct


class Elf32:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        assert self.data[:6] == b'\x7fELF\x01\x01'
        h = struct.unpack_from('<16sHHIIIIIHHHHHH', self.data)
        self.entry = h[4]
        phoff, shoff, phentsize, phnum, shentsize, shnum, shstr = h[5], h[6], h[9], h[10], h[11], h[12], h[13]
        self.segments = [struct.unpack_from('<IIIIIIII', self.data, phoff + i * phentsize) for i in range(phnum)]
        sections = [struct.unpack_from('<IIIIIIIIII', self.data, shoff + i * shentsize) for i in range(shnum)]
        strings = sections[shstr]
        string_data = self.data[strings[4]:strings[4] + strings[5]]
        name = lambda data, offset: data[offset:].split(b'\0', 1)[0].decode()
        self.sections = {name(string_data, s[0]): s for s in sections}
        self.symbols, self.symbol_sizes = {}, {}
        for section in sections:
            if section[1] == 2:
                strings = sections[section[6]]
                values = self.data[strings[4]:strings[4] + strings[5]]
                for offset in range(section[4], section[4] + section[5], section[9]):
                    n, address, size, info, other, shindex = struct.unpack_from('<IIIBBH', self.data, offset)
                    if n:
                        label = name(values, n)
                        self.symbols[label], self.symbol_sizes[label] = address, size

    def sizes(self):
        return {key: self.sections.get(key, [0] * 10)[5] for key in ['.text', '.data', '.bss', '.ARM.exidx']}

    def read_address(self, address, size):
        for typ, offset, virtual, physical, filesz, memsz, flags, align in self.segments:
            if typ == 1 and virtual <= address and address + size <= virtual + filesz:
                start = offset + address - virtual
                return self.data[start:start + size]
        raise ValueError(f'Address outside file-backed segments: {address:08x}')
