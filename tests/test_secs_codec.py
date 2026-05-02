"""Unit tests for core/secs_codec.py — SECS-II encoding and decoding."""
import pytest
from core.secs_codec import (
    SecsItem, Fmt,
    L, A, B, U1, U2, U4, I4, BOOLEAN,
    decode_item, _make_format_header,
)


# ── Encoding tests ─────────────────────────────────────────────────────────────

class TestAsciiEncoding:
    def test_format_byte(self):
        data = A('HI').encode()
        assert data[0] == (Fmt.ASCII << 2) | 1

    def test_length_byte(self):
        data = A('HELLO').encode()
        assert data[1] == 5

    def test_content(self):
        data = A('TFC').encode()
        assert data[2:] == b'TFC'

    def test_empty_string(self):
        data = A('').encode()
        assert data[1] == 0

    def test_roundtrip(self):
        original = 'TFC-6600-WB'
        item, offset = decode_item(A(original).encode())
        assert item.fmt == Fmt.ASCII
        assert item.value == original
        assert offset == len(A(original).encode())


class TestBinaryEncoding:
    def test_single_byte(self):
        data = B(0x00).encode()
        assert data[0] == (Fmt.BINARY << 2) | 1
        assert data[1] == 1
        assert data[2] == 0

    def test_hcack_value(self):
        data = B(4).encode()        # HCACK = 4 (will signal)
        item, _ = decode_item(data)
        assert item.fmt == Fmt.BINARY
        assert item.value[0] == 4

    def test_multiple_bytes(self):
        data = B(0x00, 0x01, 0x02).encode()
        assert data[1] == 3


class TestU4Encoding:
    def test_format_byte(self):
        data = U4(42).encode()
        assert data[0] == (Fmt.U4 << 2) | 1

    def test_four_bytes(self):
        data = U4(42).encode()
        assert data[1] == 4

    def test_value(self):
        data = U4(1234567).encode()
        item, _ = decode_item(data)
        assert item.value == 1234567

    def test_zero(self):
        item, _ = decode_item(U4(0).encode())
        assert item.value == 0

    def test_large_value(self):
        item, _ = decode_item(U4(0xFFFFFFFF).encode())
        assert item.value == 0xFFFFFFFF


class TestListEncoding:
    def test_format_byte(self):
        data = L(A('a'), U4(1)).encode()
        assert data[0] == (Fmt.LIST << 2) | 1

    def test_element_count(self):
        data = L(A('a'), U4(1), B(0)).encode()
        assert data[1] == 3

    def test_empty_list(self):
        data = L().encode()
        item, _ = decode_item(data)
        assert item.fmt == Fmt.LIST
        assert len(item.value) == 0

    def test_nested_list(self):
        original = L(A('RCMD'), L(A('PPID'), A('RecipeA')))
        item, _ = decode_item(original.encode())
        assert item.fmt == Fmt.LIST
        assert len(item.value) == 2
        inner = item.value[1]
        assert inner.fmt == Fmt.LIST
        assert inner.value[0].value == 'PPID'
        assert inner.value[1].value == 'RecipeA'


class TestBooleanEncoding:
    def test_true(self):
        item, _ = decode_item(BOOLEAN(True).encode())
        assert item.value is True

    def test_false(self):
        item, _ = decode_item(BOOLEAN(False).encode())
        assert item.value is False


# ── Decode tests ───────────────────────────────────────────────────────────────

class TestDecode:
    def test_offset_advances(self):
        data = A('AB').encode() + U4(99).encode()
        item1, off1 = decode_item(data, 0)
        item2, off2 = decode_item(data, off1)
        assert item1.value == 'AB'
        assert item2.value == 99

    def test_invalid_num_len_raises(self):
        bad = bytes([0b00000000])   # fmt=LIST, num_len=0  → invalid
        with pytest.raises(ValueError):
            decode_item(bad)

    def test_empty_data_raises(self):
        with pytest.raises(ValueError):
            decode_item(b'', offset=0)


# ── Real SECS message structures ───────────────────────────────────────────────

class TestMessageStructures:
    def test_s1f14_structure(self):
        """S1F14 Establish Comms Acknowledge."""
        reply = L(B(0), L(A('TFC-66'), A('6.3.10')))
        item, _ = decode_item(reply.encode())
        assert item.fmt == Fmt.LIST
        assert len(item.value) == 2
        assert item.value[0].value[0] == 0   # COMMACK = 0

    def test_s2f42_structure(self):
        """S2F42 Host Command Acknowledge."""
        reply = L(B(4), L())   # HCACK=4, no param errors
        item, _ = decode_item(reply.encode())
        assert item.fmt == Fmt.LIST
        assert item.value[0].value[0] == 4   # HCACK

    def test_s2f41_roundtrip(self):
        """S2F41 Host Command Send body."""
        params = [L(A('CARRIERID-L'), A('FOUP001')),
                  L(A('BOTTOMWAFERID-L'), A('W-0042'))]
        body = L(A('START'), L(*params))
        item, _ = decode_item(body.encode())
        assert item.value[0].value == 'START'
        pair0 = item.value[1].value[0]
        assert pair0.value[0].value == 'CARRIERID-L'
        assert pair0.value[1].value == 'FOUP001'

    def test_s6f11_structure(self):
        """S6F11 Event Report Send."""
        report = L(
            U4(1001),          # DATAID
            U4(150),           # CEID = ProcessStart
            L(L(U4(150), L(A('W-001')))),  # reports
        )
        item, _ = decode_item(report.encode())
        assert item.fmt == Fmt.LIST
        assert item.value[1].value == 150    # CEID

    def test_to_sml(self):
        s = L(B(0), L(A('TFC-66'), A('6.3.10'))).to_sml()
        # New SEMI E5 [n/m] format: L[2/1] instead of old L,2
        assert 'L[2/1]' in s
        assert 'TFC-66' in s

    def test_to_sml_byte_counts(self):
        """Verify [n/m] notation matches actual encoded byte sizes."""
        from core.secs_codec import _item_total_bytes, _num_len_bytes
        item = L(A('BOTTOMSTAGEGOREADY'), L())
        encoded = item.encode()
        s = item.to_sml()
        # Outer list: 2 elements → L[2/1]
        assert 'L[2/1]' in s
        # ASCII 18 chars → A[18/1]
        assert 'A[18/1]BOTTOMSTAGEGOREADY' in s
        # Empty list → L[0/1]
        assert 'L[0/1]' in s
        # Total encoded bytes must match _item_total_bytes
        assert _item_total_bytes(item) == len(encoded) == 24
