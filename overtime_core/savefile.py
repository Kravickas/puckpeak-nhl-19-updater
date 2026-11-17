"""NHL 19 save folders (shadPS4 `savedata/CUSA11126/<slot>/`): EA's SaveLoad container in `INDEX` + `DATA`.

INDEX lists named files; each file is one or more extents of DATA:
  name (32 bytes, NUL padded), u64 extent count, u64 file size,
  then per extent: u64 start, u64 end (exclusive), 16 bytes the game leaves uninitialised.
Each file's bytes (extents joined) hold one record: u64 payload length, 8-byte stamp, payload.
Known files: `__SaveLoadFileInfo` (JSON), `__SaveloadVer` (8 bytes + "1.60"), `__SaveLoadMetaData`
("Placeholder") and the slot's own file, e.g. `Profile0`, whose payload is packed (see `unpack`).

Packed payload: u8 1, an LZ4 frame, u32 unpacked size.
"""
import struct

from . import lz4f

NAME_LEN = 32


class SaveFormatError(ValueError):
    pass


class SaveEntry:
    def __init__(self, name, stamp, payload):
        self.name, self.stamp, self.payload = name, stamp, payload

    def __repr__(self):
        return f"SaveEntry({self.name!r}, {len(self.payload)} bytes)"


def parse(index, data):
    """Return the entries (in INDEX order) of a save folder's INDEX and DATA bytes."""
    entries, pos = [], 0
    while pos < len(index):
        if len(index) - pos < NAME_LEN + 16:
            raise SaveFormatError(f"INDEX: truncated entry at {pos:#x}")
        name = index[pos:pos + NAME_LEN].split(b'\0', 1)[0].decode('ascii')
        next_, size = struct.unpack_from('<QQ', index, pos + NAME_LEN)
        pos += NAME_LEN + 16
        blob = bytearray()
        for _ in range(next_):
            start, end = struct.unpack_from('<QQ', index, pos)
            if not start <= end <= len(data):
                raise SaveFormatError(f"{name}: extent {start:#x}..{end:#x} outside DATA")
            blob += data[start:end]
            pos += 32
        if len(blob) != size:
            raise SaveFormatError(f"{name}: extents hold {len(blob)} bytes, INDEX says {size}")
        plen = struct.unpack_from('<Q', blob, 0)[0]
        if 16 + plen != size:
            raise SaveFormatError(f"{name}: record length {plen} does not match file size {size}")
        entries.append(SaveEntry(name, bytes(blob[8:16]), bytes(blob[16:])))
    return entries


def build(entries):
    """Return (index, data) bytes with every file stored as one extent, in order."""
    index, data = bytearray(), bytearray()
    for e in entries:
        name = e.name.encode('ascii')
        if len(name) >= NAME_LEN or len(e.stamp) != 8:
            raise ValueError(f"bad entry {e.name!r}")
        rec = struct.pack('<Q', len(e.payload)) + e.stamp + e.payload
        start = len(data)
        data += rec
        index += name.ljust(NAME_LEN, b'\0') + struct.pack('<QQ', 1, len(rec))
        index += struct.pack('<QQ', start, len(data)) + bytes(16)
    return bytes(index), bytes(data)


def is_packed(payload):
    return payload[:1] == b'\x01' and payload[1:5] == struct.pack('<I', lz4f.MAGIC)


def unpack(payload):
    if not is_packed(payload):
        raise SaveFormatError('payload is not packed')
    out, n = lz4f.decode(payload[1:])
    if len(payload) != 1 + n + 4:
        raise SaveFormatError(f"{len(payload) - 1 - n} bytes after the LZ4 frame, expected 4")
    if struct.unpack_from('<I', payload, 1 + n)[0] != len(out):
        raise SaveFormatError('unpacked size mismatch')
    return out


def pack(data):
    return b'\x01' + lz4f.encode(data) + struct.pack('<I', len(data))


def pack_game(data):
    """Pack the way the game's own saves are: compressed 64 KB LZ4 blocks (frame FLG 0x64, BD 0x40), then the size.
    `pack` writes stored blocks with a 4 MB block size (valid, but not what the game writes)."""
    return b'\x01' + lz4f.encode_compressed(data, block_max=64 << 10) + struct.pack('<I', len(data))


def read_folder(path):
    import os
    with open(os.path.join(path, 'INDEX'), 'rb') as fi, open(os.path.join(path, 'DATA'), 'rb') as fd:
        return parse(fi.read(), fd.read())
