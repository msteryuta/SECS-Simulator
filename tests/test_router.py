"""Unit tests for core/router.py — message routing and pub/sub."""
import pytest
from unittest.mock import MagicMock, call
from core.router import SecsRouter
from core.gem_state import GemState


@pytest.fixture
def deps():
    state  = GemState()
    hsms   = MagicMock()
    config = {'DEVICE_ID': 1, 'MODEL': 'TEST', 'CEID': {}}
    router = SecsRouter(state, hsms, config)
    return router, state, hsms


def _hdr(stream, function, wbit=True, sys_bytes=1, direction='Host->EQ'):
    return {
        'stream': stream, 'function': function,
        'wbit': wbit, 'sys_bytes': sys_bytes,
        'raw_header': b'\x00' * 10,
        'direction': direction, 'description': f'S{stream}F{function}',
    }


# ── Route registration ─────────────────────────────────────────────────────────
class TestRouteRegistration:
    def test_handler_is_called(self, deps):
        router, _, _ = deps
        called = []
        router.register(1, 1, lambda h, b, r: (called.append(True), None)[1])
        router.process_message(_hdr(1, 1, wbit=False), b'')
        assert called

    def test_second_register_overwrites(self, deps):
        router, _, _ = deps
        log = []
        router.register(1, 1, lambda h, b, r: (log.append('A'), None)[1])
        router.register(1, 1, lambda h, b, r: (log.append('B'), None)[1])
        router.process_message(_hdr(1, 1, wbit=False), b'')
        assert log == ['B']

    def test_unknown_message_sends_s9f5(self, deps):
        router, _, hsms = deps
        router.process_message(_hdr(99, 99, wbit=False), b'')
        # S9F5 sent via hsms.send_message
        hsms.send_message.assert_called_once()
        args = hsms.send_message.call_args[0]
        assert args[0] == 9
        assert args[1] == 5


# ── Reply logic ────────────────────────────────────────────────────────────────
class TestReplyLogic:
    def test_reply_sent_when_wbit_true(self, deps):
        router, _, hsms = deps
        router.register(1, 13, lambda h, b, r: b'\x00')
        router.process_message(_hdr(1, 13, wbit=True, sys_bytes=42), b'')
        hsms.send_message.assert_called_once()
        a = hsms.send_message.call_args[0]
        assert a[0] == 1   # reply stream
        assert a[1] == 14  # reply function (13 + 1)
        assert a[4] == 42  # same sys_bytes

    def test_no_reply_when_wbit_false(self, deps):
        router, _, hsms = deps
        router.register(1, 1, lambda h, b, r: b'\x00')
        router.process_message(_hdr(1, 1, wbit=False), b'')
        hsms.send_message.assert_not_called()

    def test_no_reply_when_handler_returns_none(self, deps):
        router, _, hsms = deps
        router.register(1, 1, lambda h, b, r: None)
        router.process_message(_hdr(1, 1, wbit=True), b'')
        hsms.send_message.assert_not_called()


# ── Pub / Sub ──────────────────────────────────────────────────────────────────
class TestPubSub:
    def test_subscribe_and_receive(self, deps):
        router, _, _ = deps
        received = []
        router.subscribe('evt', lambda d: received.append(d))
        router.publish('evt', {'x': 1})
        assert received == [{'x': 1}]

    def test_multiple_subscribers(self, deps):
        router, _, _ = deps
        a, b = [], []
        router.subscribe('e', lambda d: a.append(d))
        router.subscribe('e', lambda d: b.append(d))
        router.publish('e', 42)
        assert a == [42]
        assert b == [42]

    def test_no_subscribers_no_error(self, deps):
        router, _, _ = deps
        router.publish('no_subscribers', None)   # should not raise

    def test_subscriber_exception_does_not_crash(self, deps):
        router, _, _ = deps
        def bad(_): raise RuntimeError('boom')
        ok = []
        router.subscribe('e', bad)
        router.subscribe('e', lambda _: ok.append(True))
        router.publish('e', None)
        assert ok   # second subscriber still runs

    def test_rx_message_published_on_dispatch(self, deps):
        router, _, _ = deps
        events = []
        router.subscribe('rx_message', events.append)
        router.register(1, 1, lambda h, b, r: None)
        router.process_message(_hdr(1, 1, wbit=False), b'')
        assert any(e.get('stream') == 1 for e in events)

    def test_rx_message_includes_hdr_extra(self, deps):
        router, _, _ = deps
        events = []
        router.subscribe('rx_message', events.append)
        router.register(2, 41, lambda h, b, r: None)
        h = _hdr(2, 41, wbit=False)
        h['extra'] = {'rcmd': 'START', 'params': {}}
        router.process_message(h, b'')
        rx = [e for e in events if e.get('stream') == 2]
        assert rx and rx[0].get('extra') == {'rcmd': 'START', 'params': {}}

    def test_tx_message_published_on_reply(self, deps):
        router, _, hsms = deps
        hsms.send_message.return_value = 1
        events = []
        router.subscribe('tx_message', events.append)
        router.register(1, 13, lambda h, b, r: b'\x00')
        router.process_message(_hdr(1, 13, wbit=True), b'')
        assert any(e.get('stream') == 1 and e.get('function') == 14 for e in events)


# ── send_unsolicited ───────────────────────────────────────────────────────────
class TestSendUnsolicited:
    def test_calls_hsms_send(self, deps):
        router, _, hsms = deps
        hsms.send_message.return_value = 99
        router.send_unsolicited(6, 11, b'\x00')
        hsms.send_message.assert_called_once_with(6, 11, True, b'\x00')

    def test_publishes_tx_message(self, deps):
        router, _, hsms = deps
        hsms.send_message.return_value = 5
        events = []
        router.subscribe('tx_message', events.append)
        router.send_unsolicited(6, 11, b'\x00')
        assert events[0]['stream']   == 6
        assert events[0]['function'] == 11

    def test_tx_extra_merged_into_tx_message(self, deps):
        router, _, hsms = deps
        hsms.send_message.return_value = 1
        events = []
        router.subscribe('tx_message', events.append)
        router.send_unsolicited(5, 1, b'x', tx_extra={'alid': 1001, 'action': 'SET'})
        assert events[0]['alid'] == 1001
        assert events[0]['action'] == 'SET'
