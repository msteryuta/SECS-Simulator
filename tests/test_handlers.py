"""
Unit tests for S1 / S2 / S6 handlers.
Tests focus on correct SECS-II reply structure and state transitions,
NOT on threading behaviour (that is covered by integration tests).
"""
import pytest
from unittest.mock import MagicMock, patch

from core.gem_state  import GemState, ControlState, ProcessState
from core.secs_codec import L, A, B, U4, decode_item, Fmt
import handlers.s1_handler as s1
import handlers.s2_handler as s2
import handlers.s6_handler as s6


# ── Fixtures ───────────────────────────────────────────────────────────────────
@pytest.fixture
def router_at(request):
    """Return a mock router with gem_state in the requested control state."""
    ctrl_state = getattr(request, 'param', ControlState.HOST_OFFLINE)
    state  = GemState()
    state.force_control(ctrl_state)
    r = MagicMock()
    r.gem_state = state
    r.config = {
        'MODEL': 'TFC-66', 'SOFTREV': '6.3.10',
        'CurrentONLACK': 0,
        'CEID': {
            '150': {'name': 'ProcessStart', 'rptid': 150, 'vids': [555, 960]},
            '140': {'name': 'AutorunStart',  'rptid': 140, 'vids': []},
        },
        'RCMD': {
            'START': {
                'desc': 'Start', 'triggers_events': [140, 150],
                'params': {
                    'CARRIERID-L': {'format': 'ASCII', 'max_len': 16, 'required': False},
                },
            },
            'STOP':  {'desc': 'Stop', 'triggers_events': [], 'params': {}},
            'PPSELECT': {
                'desc': 'Recipe', 'triggers_events': [152],
                'params': {'PPID': {'format': 'ASCII', 'max_len': 64, 'required': True}},
            },
            'GOLOCAL':  {'desc': 'Go Local',  'triggers_events': [], 'params': {}},
            'GOREMOTE': {'desc': 'Go Remote', 'triggers_events': [], 'params': {}},
        },
    }
    return r, state


def _hdr(s, f, wbit=True, sys_bytes=1):
    return {'stream': s, 'function': f, 'wbit': wbit,
            'sys_bytes': sys_bytes, 'raw_header': b'\x00' * 10}


def _s2f41_body(rcmd, params=None):
    pairs = [L(A(k), A(v)) for k, v in (params or [])]
    return L(A(rcmd), L(*pairs)).encode()


# ── S1 handlers ────────────────────────────────────────────────────────────────
class TestS1F1:
    def test_returns_list_of_two(self, router_at):
        r, _ = router_at
        body = s1.handle_s1f1(_hdr(1, 1), b'', r)
        item, _ = decode_item(body)
        assert item.fmt == Fmt.LIST
        assert len(item.value) == 2

    def test_mdln_ascii(self, router_at):
        r, _ = router_at
        body = s1.handle_s1f1(_hdr(1, 1), b'', r)
        item, _ = decode_item(body)
        assert item.value[0].fmt == Fmt.ASCII

    def test_softrev_ascii(self, router_at):
        r, _ = router_at
        body = s1.handle_s1f1(_hdr(1, 1), b'', r)
        item, _ = decode_item(body)
        assert item.value[1].fmt == Fmt.ASCII


class TestS1F13:
    def test_transitions_to_host_offline(self, router_at):
        r, state = router_at
        state.force_control(ControlState.EQUIPMENT_OFFLINE)
        s1.handle_s1f13(_hdr(1, 13), b'', r)
        assert state.control == ControlState.HOST_OFFLINE

    def test_commack_is_zero(self, router_at):
        r, state = router_at
        state.force_control(ControlState.EQUIPMENT_OFFLINE)
        body = s1.handle_s1f13(_hdr(1, 13), b'', r)
        item, _ = decode_item(body)
        assert item.value[0].value[0] == 0   # COMMACK = Accepted

    def test_reply_is_l2(self, router_at):
        r, state = router_at
        body = s1.handle_s1f13(_hdr(1, 13), b'', r)
        item, _ = decode_item(body)
        assert item.fmt == Fmt.LIST
        assert len(item.value) == 2


class TestS1F15:
    def test_transitions_to_host_offline(self, router_at):
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        s1.handle_s1f15(_hdr(1, 15), b'', r)
        assert state.control == ControlState.HOST_OFFLINE

    def test_oflack_zero(self, router_at):
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        body = s1.handle_s1f15(_hdr(1, 15), b'', r)
        item, _ = decode_item(body)
        assert item.value[0] == 0


class TestS1F17:
    def test_online_accepted(self, router_at):
        r, state = router_at    # starts at HOST_OFFLINE
        body = s1.handle_s1f17(_hdr(1, 17), b'', r)
        item, _ = decode_item(body)
        assert item.value[0] == 0   # ON-LINE Accepted

    def test_transitions_to_online_remote(self, router_at):
        r, state = router_at
        s1.handle_s1f17(_hdr(1, 17), b'', r)
        assert state.control == ControlState.ONLINE_REMOTE

    def test_already_online_returns_2(self, router_at):
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        body = s1.handle_s1f17(_hdr(1, 17), b'', r)
        item, _ = decode_item(body)
        assert item.value[0] == 2   # Already ONLINE


# ── S2 handlers ────────────────────────────────────────────────────────────────
class TestS2F41ParseBody:
    def test_simple_rcmd(self):
        body = _s2f41_body('START')
        rcmd, params = s2._parse_s2f41(body)
        assert rcmd == 'START'
        assert params == {}

    def test_with_params(self):
        body = _s2f41_body('START', [('CARRIERID-L', 'F001'), ('CARRIERID-R', 'F002')])
        rcmd, params = s2._parse_s2f41(body)
        assert rcmd == 'START'
        assert params['CARRIERID-L'] == 'F001'
        assert params['CARRIERID-R'] == 'F002'

    def test_empty_body(self):
        rcmd, params = s2._parse_s2f41(b'')
        assert rcmd == ''


class TestS2F41Handle:
    def test_unknown_cmd_returns_hcack1(self, router_at):
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        body = s2.handle_s2f41(_hdr(2, 41), _s2f41_body('BADCMD'), r)
        item, _ = decode_item(body)
        assert item.value[0].value[0] == s2.HCACK_NO_CMD

    def test_missing_required_param_returns_hcack3(self, router_at):
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        body = s2.handle_s2f41(_hdr(2, 41), _s2f41_body('PPSELECT'), r)
        item, _ = decode_item(body)
        assert item.value[0].value[0] == s2.HCACK_BAD_PARAM

    def test_stop_no_triggers_returns_hcack0(self, router_at):
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        body = s2.handle_s2f41(_hdr(2, 41), _s2f41_body('STOP'), r)
        item, _ = decode_item(body)
        assert item.value[0].value[0] == s2.HCACK_OK

    def test_start_with_triggers_returns_hcack0(self, router_at):
        """Real machines return HCACK=0 for all valid commands (including async START)."""
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        state.set_sv(960, 2)   # not ServoOff
        with patch('handlers.s2_handler.threading.Thread') as mock_t:
            mock_t.return_value.start = MagicMock()
            body = s2.handle_s2f41(_hdr(2, 41), _s2f41_body('START'), r)
        item, _ = decode_item(body)
        assert item.value[0].value[0] == s2.HCACK_OK

    def test_golocal_transitions_state(self, router_at):
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        r.config['RCMD']['GOLOCAL']['triggers_events'] = []
        s2.handle_s2f41(_hdr(2, 41), _s2f41_body('GOLOCAL'), r)
        assert state.control == ControlState.ONLINE_LOCAL

    def test_ppselect_updates_ppid(self, router_at):
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        r.config['RCMD']['PPSELECT']['triggers_events'] = []
        s2.handle_s2f41(_hdr(2, 41),
                         _s2f41_body('PPSELECT', [('PPID', 'RecipeX')]), r)
        assert state.ppid == 'RecipeX'

    def test_start_servo_off_returns_hcack65(self, router_at):
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        state.set_sv(960, 9)   # ServoOff
        body = s2.handle_s2f41(_hdr(2, 41), _s2f41_body('START'), r)
        item, _ = decode_item(body)
        assert item.value[0].value[0] == s2.HCACK_SERVO_OFF

    def test_reply_is_l2(self, router_at):
        r, state = router_at
        state.force_control(ControlState.ONLINE_REMOTE)
        body = s2.handle_s2f41(_hdr(2, 41), _s2f41_body('STOP'), r)
        item, _ = decode_item(body)
        assert item.fmt == Fmt.LIST
        assert len(item.value) == 2


# ── S6 handlers ────────────────────────────────────────────────────────────────
class TestS6:
    def test_send_s6f11_calls_send_unsolicited(self, router_at):
        r, state = router_at
        r.send_unsolicited.return_value = 1
        s6.send_s6f11(r, 150)
        r.send_unsolicited.assert_called_once()
        args = r.send_unsolicited.call_args[0]
        assert args[0] == 6
        assert args[1] == 11

    def test_send_s6f11_publishes_eq_event(self, router_at):
        r, state = router_at
        r.send_unsolicited.return_value = 1
        s6.send_s6f11(r, 150)
        r.publish.assert_called()
        evt_call = [c for c in r.publish.call_args_list if c[0][0] == 'eq_event']
        assert evt_call
        data = evt_call[0][0][1]
        assert data['ceid'] == 150

    def test_handle_s6f12_returns_none(self, router_at):
        r, _ = router_at
        result = s6.handle_s6f12(_hdr(6, 12), B(0).encode(), r)
        assert result is None


# ── S2 BOTTOMMAPREAD / BOTTOMWAFERLOADCOMPLETE event sequence ─────────────────
class TestS2BottomMapSequence:
    @staticmethod
    def _router_mock():
        state = GemState()
        state.force_control(ControlState.ONLINE_REMOTE)
        m = MagicMock()
        m.gem_state = state
        m.send_unsolicited = MagicMock(return_value=1)
        m.publish = MagicMock()
        m.config = {
            'CEID': {
                '107': {'name': 'BottomWaferStart', 'rptid': 107,
                        'vids': [500, 551, 568, 567, 569]},
                '153': {'name': 'TopBinRequest', 'rptid': 153, 'vids': [500]},
            },
        }
        return m, state

    @patch('handlers.s2_handler.time.sleep', lambda _s: None)
    def test_bottommapread_sends_ceid153(self):
        r, state = self._router_mock()
        s2._simulate_bottommapread({'MAPFILENAME': 'map_a.xml'}, r, state)
        r.send_unsolicited.assert_called_once()
        body = r.send_unsolicited.call_args[0][2]
        item, _ = decode_item(body)
        assert item.value[1].value == 153

    @patch('handlers.s2_handler.time.sleep', lambda _s: None)
    def test_bottomwaferloadcomplete_sends_ceid107_not_259(self):
        r, state = self._router_mock()
        s2._simulate_bottomwaferloadcomplete(
            {'DEVICESIDE': '1', 'BOTTOMWAFERID': 'BW-01'}, r, state)
        r.send_unsolicited.assert_called_once()
        body = r.send_unsolicited.call_args[0][2]
        item, _ = decode_item(body)
        assert item.value[1].value == 107

    @patch('handlers.s2_handler.time.sleep', lambda _s: None)
    def test_start_sends_dual_side_sequence(self):
        """START fires: 259×2, 107×2, 150×2, 140×2 in that order (dual-side)."""
        r, state = self._router_mock()
        r.config['CEID'].update({
            '140': {'name': 'AutorunStart',           'rptid': 140, 'vids': []},
            '150': {'name': 'ProcessStart',           'rptid': 150, 'vids': []},
            '151': {'name': 'ProcessEnd',             'rptid': 151, 'vids': []},
            '141': {'name': 'AutorunEnd',             'rptid': 141, 'vids': []},
            '259': {'name': 'BgStgPresenceInformation','rptid': 259, 'vids': []},
        })
        s2._simulate_start({'BOTTOMWAFERID-L': 'WFR_L', 'BOTTOMWAFERID-R': 'WFR_R'}, r, state)
        ceids = []
        for call in r.send_unsolicited.call_args_list:
            body = call[0][2]
            item, _ = decode_item(body)
            ceids.append(item.value[1].value)
        # 259 should appear twice before 107
        assert ceids.count(259) == 2, f'Expected 2x CEID 259, got {ceids.count(259)}'
        assert ceids.count(107) == 2, f'Expected 2x CEID 107, got {ceids.count(107)}'
        assert ceids.count(150) == 2, f'Expected 2x CEID 150, got {ceids.count(150)}'
        assert ceids.count(140) == 2, f'Expected 2x CEID 140, got {ceids.count(140)}'
        # Order: all 259 before first 107
        first_107 = ceids.index(107)
        last_259  = len(ceids) - 1 - ceids[::-1].index(259)
        assert last_259 < first_107, f'CEID 259 must all precede CEID 107 (got {ceids})'
