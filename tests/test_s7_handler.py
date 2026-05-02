"""
Unit tests for S7 (Process Program Management) handlers.

All tests use tmp_path to avoid touching the real recipes/ directory.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.secs_codec import L, A, B, U4, decode_item, Fmt
import handlers.s7_handler as s7


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hdr(s, f, wbit=True, sys_bytes=1):
    return {'stream': s, 'function': f, 'wbit': wbit,
            'sys_bytes': sys_bytes, 'raw_header': b'\x00' * 10}


def _make_router():
    r = MagicMock()
    r.gem_state = MagicMock()
    r.gem_state.ppid = ''
    r.config = {'MODEL': 'TFC-66', 'SOFTREV': '6.3.10'}
    return r


def _seed_recipe(recipes_dir: Path, ppid: str, content: dict):
    d = recipes_dir / ppid
    d.mkdir(parents=True, exist_ok=True)
    (d / 'recipe.json').write_text(json.dumps(content), encoding='utf-8')


# ── S7F17 Delete ───────────────────────────────────────────────────────────────

class TestS7F17Delete:
    def test_delete_single_ppid_returns_ackc7_zero(self, tmp_path):
        _seed_recipe(tmp_path, 'RecipeA', {'ccode_list': []})
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            body = L(A('RecipeA')).encode()
            result = s7.handle_s7f17(_hdr(7, 17), body, _make_router())
        item, _ = decode_item(result)
        assert item.fmt == Fmt.BINARY
        assert item.value[0] == 0   # ACKC7 = OK

    def test_delete_single_ppid_removes_folder(self, tmp_path):
        _seed_recipe(tmp_path, 'RecipeA', {'ccode_list': []})
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            body = L(A('RecipeA')).encode()
            s7.handle_s7f17(_hdr(7, 17), body, _make_router())
        assert not (tmp_path / 'RecipeA').exists()

    def test_delete_nonexistent_ppid_returns_ackc7_4(self, tmp_path):
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            body = L(A('NoSuchRecipe')).encode()
            result = s7.handle_s7f17(_hdr(7, 17), body, _make_router())
        item, _ = decode_item(result)
        assert item.value[0] == 4   # ACKC7 = PPID not found

    def test_delete_all_on_empty_list(self, tmp_path):
        _seed_recipe(tmp_path, 'R1', {'ccode_list': []})
        _seed_recipe(tmp_path, 'R2', {'ccode_list': []})
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            body = L().encode()
            s7.handle_s7f17(_hdr(7, 17), body, _make_router())
        remaining = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert remaining == []

    def test_delete_multiple_ppids(self, tmp_path):
        for name in ('R1', 'R2', 'R3'):
            _seed_recipe(tmp_path, name, {'ccode_list': []})
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            body = L(A('R1'), A('R2')).encode()
            result = s7.handle_s7f17(_hdr(7, 17), body, _make_router())
        item, _ = decode_item(result)
        assert item.value[0] == 0
        assert not (tmp_path / 'R1').exists()
        assert not (tmp_path / 'R2').exists()
        assert (tmp_path / 'R3').exists()

    def test_partial_delete_returns_error_if_one_missing(self, tmp_path):
        _seed_recipe(tmp_path, 'Exists', {'ccode_list': []})
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            body = L(A('Exists'), A('Missing')).encode()
            result = s7.handle_s7f17(_hdr(7, 17), body, _make_router())
        item, _ = decode_item(result)
        # Existing one deleted, but ACKC7 = 4 because one was missing
        assert not (tmp_path / 'Exists').exists()
        assert item.value[0] == 4


# ── S7F19 List ────────────────────────────────────────────────────────────────

class TestS7F19List:
    def test_returns_list_item(self, tmp_path):
        _seed_recipe(tmp_path, 'RecipeA', {})
        r = _make_router()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f19(_hdr(7, 19), b'', r)
        item, _ = decode_item(result)
        assert item.fmt == Fmt.LIST

    def test_returns_all_ppids_on_disk(self, tmp_path):
        _seed_recipe(tmp_path, 'RecipeA', {})
        _seed_recipe(tmp_path, 'RecipeB', {})
        r = _make_router()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f19(_hdr(7, 19), b'', r)
        item, _ = decode_item(result)
        names = {e.value for e in item.value}
        assert 'RecipeA' in names
        assert 'RecipeB' in names

    def test_includes_current_ppid_if_not_on_disk(self, tmp_path):
        r = _make_router()
        r.gem_state.ppid = 'ActiveRecipe'
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f19(_hdr(7, 19), b'', r)
        item, _ = decode_item(result)
        names = [e.value for e in item.value]
        assert 'ActiveRecipe' in names

    def test_does_not_duplicate_current_ppid_if_on_disk(self, tmp_path):
        _seed_recipe(tmp_path, 'OnDisk', {})
        r = _make_router()
        r.gem_state.ppid = 'OnDisk'
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f19(_hdr(7, 19), b'', r)
        item, _ = decode_item(result)
        names = [e.value for e in item.value]
        assert names.count('OnDisk') == 1

    def test_empty_dir_returns_empty_list(self, tmp_path):
        r = _make_router()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f19(_hdr(7, 19), b'', r)
        item, _ = decode_item(result)
        assert len(item.value) == 0


# ── S7F25 Body Request ────────────────────────────────────────────────────────

class TestS7F25BodyRequest:
    def test_returns_l4_structure_for_existing_recipe(self, tmp_path):
        content = {'ccode_list': [{'ccode': 1, 'params': ['100', '200']}]}
        _seed_recipe(tmp_path, 'RecipeA', content)
        body = L(A('RecipeA')).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f25(_hdr(7, 25), body, _make_router())
        item, _ = decode_item(result)
        assert item.fmt == Fmt.LIST
        assert len(item.value) == 4   # PPID, MDLN, SOFTREV, ccode_list
        assert len(item.value[3].value) == len(s7.S7F26_CCODE_LIST)

    def test_ppid_in_reply_matches_request(self, tmp_path):
        _seed_recipe(tmp_path, 'RecipeA', {'ccode_list': []})
        body = L(A('RecipeA')).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f25(_hdr(7, 25), body, _make_router())
        item, _ = decode_item(result)
        assert item.value[0].value == 'RecipeA'
        assert len(item.value[3].value) == len(s7.S7F26_CCODE_LIST)

    def test_s7f26_ccode_list_matches_equipment_template(self):
        assert s7.S7F26_CCODE_LIST[0] == {'ccode': 1000, 'params': ['0.5']}
        assert s7.S7F26_CCODE_LIST[-1] == {'ccode': 1500, 'params': ['1']}
        assert len(s7.S7F26_CCODE_LIST) == 17

    def test_raw_hex_only_recipe_ignored_for_s7f26_ccodes(self, tmp_path):
        _seed_recipe(tmp_path, 'HexOnly', {'raw_hex': 'deadbeef'})
        body = L(A('HexOnly')).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f25(_hdr(7, 25), body, _make_router())
        item, _ = decode_item(result)
        assert item.value[0].value == 'HexOnly'
        assert len(item.value[3].value) == len(s7.S7F26_CCODE_LIST)

    def test_missing_recipe_uses_default_ccodes_and_request_ppid(self, tmp_path):
        """No recipe.json: S7F26 still returns L4 with PPID from request + default CCODEs."""
        body = L(A('NoRecipe')).encode()
        r = _make_router()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f25(_hdr(7, 25), body, r)
        item, _ = decode_item(result)
        assert item.fmt == Fmt.LIST
        assert len(item.value) == 4
        assert item.value[0].value == 'NoRecipe'
        assert item.value[1].value == 'TFC-66'   # MODEL[:6]
        assert item.value[2].value == '6.3.10'   # SOFTREV[:6]
        ccode_list = item.value[3]
        assert len(ccode_list.value) == len(s7.S7F26_CCODE_LIST)

    def test_empty_ppid_returns_empty_list(self, tmp_path):
        body = L(A('')).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f25(_hdr(7, 25), body, _make_router())
        item, _ = decode_item(result)
        assert item.fmt == Fmt.LIST
        assert len(item.value) == 0

    def test_parses_l_a_ppid_format_from_gui(self, tmp_path):
        """GUI sends S7F25 body as L(A(ppid)) — handler must unwrap the list."""
        content = {'ccode_list': [{'ccode': 2, 'params': ['3.5']}]}
        _seed_recipe(tmp_path, 'MyRecipe', content)
        body = L(A('MyRecipe')).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f25(_hdr(7, 25), body, _make_router())
        item, _ = decode_item(result)
        assert item.value[0].value == 'MyRecipe'
        first_step = item.value[3].value[0]
        assert first_step.value[0].fmt == Fmt.U4
        assert first_step.value[0].value == 1000   # not 2 from recipe.json

    def test_parses_bare_ascii_ppid_format(self, tmp_path):
        """Direct A(ppid) body format (non-GUI path)."""
        _seed_recipe(tmp_path, 'DirectPPID', {'ccode_list': []})
        body = A('DirectPPID').encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f25(_hdr(7, 25), body, _make_router())
        item, _ = decode_item(result)
        assert item.value[0].value == 'DirectPPID'

    def test_uploaded_recipe_ccode_list_not_used_for_s7f26(self, tmp_path):
        """S7F26 CCODE block is fixed in code; recipe.json ccode_list is not echoed."""
        content = {
            'ccode_list': [
                {'ccode': 1, 'params': ['a']},
                {'ccode': 2, 'params': ['b', 'c']},
                {'ccode': 3, 'params': []},
            ]
        }
        _seed_recipe(tmp_path, 'MultiStep', content)
        body = L(A('MultiStep')).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f25(_hdr(7, 25), body, _make_router())
        item, _ = decode_item(result)
        ccode_list_item = item.value[3]
        assert len(ccode_list_item.value) == len(s7.S7F26_CCODE_LIST)


# ── S7F3 Upload ───────────────────────────────────────────────────────────────

class TestS7F3Upload:
    def test_upload_json_body_returns_ackc7_zero(self, tmp_path):
        ppbody = json.dumps({'ccode_list': [{'ccode': 1, 'params': ['100']}]}).encode()
        body = L(A('NewRecipe'), B(*ppbody)).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f3(_hdr(7, 3), body, _make_router())
        item, _ = decode_item(result)
        assert item.fmt == Fmt.BINARY
        assert item.value[0] == 0   # ACKC7 = OK

    def test_upload_json_body_creates_recipe_json(self, tmp_path):
        ccode_list = [{'ccode': 1, 'params': ['100']}]
        ppbody = json.dumps({'ccode_list': ccode_list}).encode()
        body = L(A('NewRecipe'), B(*ppbody)).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            s7.handle_s7f3(_hdr(7, 3), body, _make_router())
        recipe_file = tmp_path / 'NewRecipe' / 'recipe.json'
        assert recipe_file.exists()
        saved = json.loads(recipe_file.read_text())
        assert saved['ccode_list'] == ccode_list

    def test_upload_binary_body_stores_raw_hex(self, tmp_path):
        binary_data = bytes([0x01, 0x02, 0x03, 0xFF])
        body = L(A('BinaryRecipe'), B(*binary_data)).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f3(_hdr(7, 3), body, _make_router())
        item, _ = decode_item(result)
        assert item.value[0] == 0
        recipe_file = tmp_path / 'BinaryRecipe' / 'recipe.json'
        saved = json.loads(recipe_file.read_text())
        assert 'raw_hex' in saved
        assert saved['raw_hex'] == binary_data.hex()

    def test_upload_overwrites_existing_recipe(self, tmp_path):
        _seed_recipe(tmp_path, 'OldRecipe', {'ccode_list': [{'ccode': 99, 'params': []}]})
        ccode_list = [{'ccode': 1, 'params': ['updated']}]
        ppbody = json.dumps({'ccode_list': ccode_list}).encode()
        body = L(A('OldRecipe'), B(*ppbody)).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            s7.handle_s7f3(_hdr(7, 3), body, _make_router())
        saved = json.loads((tmp_path / 'OldRecipe' / 'recipe.json').read_text())
        assert saved['ccode_list'][0]['ccode'] == 1

    def test_upload_creates_recipe_directory(self, tmp_path):
        ppbody = json.dumps({'ccode_list': []}).encode()
        body = L(A('FreshRecipe'), B(*ppbody)).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            s7.handle_s7f3(_hdr(7, 3), body, _make_router())
        assert (tmp_path / 'FreshRecipe').is_dir()

    def test_empty_body_returns_ackc7_nonzero(self, tmp_path):
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f3(_hdr(7, 3), b'', _make_router())
        item, _ = decode_item(result)
        assert item.value[0] != 0   # ACKC7 = error

    def test_empty_ppid_returns_ackc7_nonzero(self, tmp_path):
        ppbody = json.dumps({'ccode_list': []}).encode()
        body = L(A(''), B(*ppbody)).encode()
        with patch.object(s7, 'RECIPES_DIR', tmp_path):
            result = s7.handle_s7f3(_hdr(7, 3), body, _make_router())
        item, _ = decode_item(result)
        assert item.value[0] != 0
