"""
SECS-II item encoding and decoding utilities.

Format byte layout: bits[7:2] = format code, bits[1:0] = number of length bytes.
For LIST items, length = number of elements.
For all other items, length = number of bytes.
"""
import struct
from typing import Any, List, Tuple, Optional


class Fmt:
    """SECS-II format codes (6-bit field, upper bits of format byte)."""
    LIST    = 0
    BINARY  = 8
    BOOLEAN = 9
    ASCII   = 16
    I8      = 24
    I1      = 25
    I2      = 26
    I4      = 28
    F8      = 32
    F4      = 36
    U8      = 40
    U1      = 41
    U2      = 42
    U4      = 44


_FMT_NAMES = {
    Fmt.LIST: 'L', Fmt.BINARY: 'B', Fmt.BOOLEAN: 'BOOLEAN',
    Fmt.ASCII: 'A', Fmt.I1: 'I1', Fmt.I2: 'I2', Fmt.I4: 'I4', Fmt.I8: 'I8',
    Fmt.U1: 'U1', Fmt.U2: 'U2', Fmt.U4: 'U4', Fmt.U8: 'U8',
    Fmt.F4: 'F4', Fmt.F8: 'F8',
}

# Byte size of each numeric format (data bytes, not header)
_FMT_BYTE_SIZE = {
    Fmt.U1: 1, Fmt.U2: 2, Fmt.U4: 4, Fmt.U8: 8,
    Fmt.I1: 1, Fmt.I2: 2, Fmt.I4: 4, Fmt.I8: 8,
    Fmt.F4: 4, Fmt.F8: 8,
}


def _num_len_bytes(n: int) -> int:
    """Number of length-encoding bytes needed for a value n (1, 2, or 3)."""
    if n < 256:
        return 1
    if n < 65536:
        return 2
    return 3


def _item_total_bytes(item: 'SecsItem') -> int:
    """Total encoded byte size of item: 1 (fmt) + m (len-field) + data."""
    if item.fmt == Fmt.LIST:
        n = len(item.value)
        m = _num_len_bytes(n)
        return 1 + m + sum(_item_total_bytes(c) for c in item.value)
    if item.fmt == Fmt.ASCII:
        n = len(str(item.value).encode('ascii', errors='replace'))
        return 1 + _num_len_bytes(n) + n
    if item.fmt == Fmt.BINARY:
        raw = item.value if isinstance(item.value, (bytes, bytearray)) else bytes([item.value])
        n = len(raw)
        return 1 + _num_len_bytes(n) + n
    if item.fmt == Fmt.BOOLEAN:
        return 3  # 1 fmt + 1 len + 1 data
    if item.fmt in _FMT_BYTE_SIZE:
        n = _FMT_BYTE_SIZE[item.fmt]
        return 1 + _num_len_bytes(n) + n
    return 0


class SecsItem:
    """Represents a single SECS-II data item (can be a nested list)."""

    def __init__(self, fmt: int, value: Any):
        self.fmt = fmt
        self.value = value

    def __repr__(self) -> str:
        name = _FMT_NAMES.get(self.fmt, f'?{self.fmt}')
        if self.fmt == Fmt.LIST:
            return f'L[{len(self.value)}]'
        return f'{name}({self.value!r})'

    def to_sml(self, indent: int = 0) -> str:
        """Return SEMI E5 SML with [data_count/length_bytes] annotation.

        Format: <TYPE[n/m]value>
          n = data length (element count for L, byte count for others)
          m = number of bytes used to encode n in the SECS-II wire format
        """
        pad = '  ' * indent
        name = _FMT_NAMES.get(self.fmt, f'?{self.fmt}')

        if self.fmt == Fmt.LIST:
            n = len(self.value)
            m = _num_len_bytes(n)
            if n == 0:
                return f'{pad}<L[{n}/{m}]>'
            inner = '\n'.join(c.to_sml(indent + 1) for c in self.value)
            return f'{pad}<L[{n}/{m}]\n{inner}\n{pad}>'

        if self.fmt == Fmt.ASCII:
            enc = str(self.value).encode('ascii', errors='replace')
            n = len(enc)
            m = _num_len_bytes(n)
            v = self.value if n <= 64 else self.value[:64] + '…'
            return f'{pad}<A[{n}/{m}]{v}>'

        if self.fmt == Fmt.BINARY:
            raw = self.value if isinstance(self.value, (bytes, bytearray)) else bytes([self.value])
            n = len(raw)
            m = _num_len_bytes(n)
            hex_s = ' '.join(f'{b:02X}' for b in raw[:24])
            if n > 24:
                hex_s += ' ...'
            return f'{pad}<B[{n}/{m}]{hex_s}>'

        if self.fmt == Fmt.BOOLEAN:
            return f'{pad}<BOOLEAN[1/1]{"T" if self.value else "F"}>'

        if self.fmt in _FMT_BYTE_SIZE:
            n = _FMT_BYTE_SIZE[self.fmt]
            m = _num_len_bytes(n)
            return f'{pad}<{name}[{n}/{m}]{self.value}>'

        return f'{pad}<{name}[?]{self.value!r}>'

    def encode(self) -> bytes:
        """Encode item to SECS-II bytes."""
        body, length = self._encode_body()
        return _make_format_header(self.fmt, length) + body

    def _encode_body(self) -> Tuple[bytes, int]:
        if self.fmt == Fmt.LIST:
            body = b''.join(item.encode() for item in self.value)
            return body, len(self.value)
        if self.fmt == Fmt.ASCII:
            body = str(self.value).encode('ascii', errors='replace')
            return body, len(body)
        if self.fmt == Fmt.BINARY:
            body = bytes(self.value) if isinstance(self.value, (list, bytearray, bytes)) else bytes([self.value])
            return body, len(body)
        if self.fmt == Fmt.BOOLEAN:
            body = bytes([1 if self.value else 0])
            return body, 1
        _int_formats = {
            Fmt.U1: ('>B', 1), Fmt.U2: ('>H', 2), Fmt.U4: ('>I', 4), Fmt.U8: ('>Q', 8),
            Fmt.I1: ('>b', 1), Fmt.I2: ('>h', 2), Fmt.I4: ('>i', 4), Fmt.I8: ('>q', 8),
        }
        if self.fmt in _int_formats:
            fmt_str, size = _int_formats[self.fmt]
            body = struct.pack(fmt_str, self.value)
            return body, size
        raise ValueError(f'Unsupported SECS-II format code: {self.fmt}')


def _make_format_header(fmt_code: int, length: int) -> bytes:
    """Build format byte + length bytes for a SECS-II item."""
    if length < 256:
        return bytes([(fmt_code << 2) | 1, length])
    if length < 65536:
        return bytes([(fmt_code << 2) | 2]) + struct.pack('>H', length)
    return bytes([(fmt_code << 2) | 3]) + length.to_bytes(3, 'big')


def decode_item(data: bytes, offset: int = 0) -> Tuple[SecsItem, int]:
    """Decode one SECS-II item from bytes. Returns (item, new_offset)."""
    if offset >= len(data):
        raise ValueError('No data at offset')

    fmt_byte = data[offset]
    fmt_code = (fmt_byte >> 2) & 0x3F
    num_len = fmt_byte & 0x03
    offset += 1

    if num_len == 0:
        raise ValueError('num_len_bytes == 0 is invalid')

    length = 0
    for _ in range(num_len):
        length = (length << 8) | data[offset]
        offset += 1

    if fmt_code == Fmt.LIST:
        items: List[SecsItem] = []
        for _ in range(length):
            item, offset = decode_item(data, offset)
            items.append(item)
        return SecsItem(Fmt.LIST, items), offset

    if fmt_code == Fmt.ASCII:
        value = data[offset:offset + length].decode('ascii', errors='replace')
        return SecsItem(Fmt.ASCII, value), offset + length

    if fmt_code == Fmt.BINARY:
        value = bytes(data[offset:offset + length])
        return SecsItem(Fmt.BINARY, value), offset + length

    if fmt_code == Fmt.BOOLEAN:
        value = bool(data[offset])
        return SecsItem(Fmt.BOOLEAN, value), offset + length

    _unpack_map = {
        Fmt.U1: ('>B', 1), Fmt.U2: ('>H', 2), Fmt.U4: ('>I', 4), Fmt.U8: ('>Q', 8),
        Fmt.I1: ('>b', 1), Fmt.I2: ('>h', 2), Fmt.I4: ('>i', 4), Fmt.I8: ('>q', 8),
    }
    if fmt_code in _unpack_map:
        fmt_str, size = _unpack_map[fmt_code]
        value = struct.unpack_from(fmt_str, data, offset)[0]
        return SecsItem(fmt_code, value), offset + length

    # Unknown format — return raw bytes
    return SecsItem(Fmt.BINARY, bytes(data[offset:offset + length])), offset + length


# ── Convenience constructors ───────────────────────────────────────────────────
def L(*items) -> SecsItem:   return SecsItem(Fmt.LIST,    list(items))
def A(s: str) -> SecsItem:   return SecsItem(Fmt.ASCII,   str(s))
def B(*vals)  -> SecsItem:   return SecsItem(Fmt.BINARY,  bytes(vals))
def U1(v: int) -> SecsItem:  return SecsItem(Fmt.U1,      int(v))
def U2(v: int) -> SecsItem:  return SecsItem(Fmt.U2,      int(v))
def U4(v: int) -> SecsItem:  return SecsItem(Fmt.U4,      int(v))
def I1(v: int) -> SecsItem:  return SecsItem(Fmt.I1,      int(v))
def I2(v: int) -> SecsItem:  return SecsItem(Fmt.I2,      int(v))
def I4(v: int) -> SecsItem:  return SecsItem(Fmt.I4,      int(v))
def BOOLEAN(v: bool) -> SecsItem: return SecsItem(Fmt.BOOLEAN, bool(v))
