"""
Stream 9 (System Errors) — EQ-initiated error signals.

S9 messages are sent BY THE EQUIPMENT when it detects faults in HOST messages.
They are never sent by the HOST (one-directional).  The router already auto-sends
S9F5 for unrecognised (stream, function) pairs; this module exposes the full set
so that the GUI or other handlers can trigger any S9 error.

S9 message bodies all contain the offending 10-byte SECS-II header (MHEAD or SHEAD).

  S9F1   UDN  Unrecognized Device ID
  S9F3   USN  Unrecognized Stream Type
  S9F5   UFN  Unrecognized Function Type
  S9F7   IDN  Illegal Data
  S9F9   TTN  Transaction Timer Timeout
  S9F11  DLN  Data Too Long
"""
import logging
from core.secs_codec import B

logger = logging.getLogger(__name__)

_DUMMY_HEADER = b'\x00' * 10   # 10-byte placeholder when no real header available


def _send_s9(router, function: int, bad_header: bytes):
    """Send S9Fx with the offending 10-byte header as body."""
    header = bad_header if len(bad_header) == 10 else _DUMMY_HEADER
    body = B(*header).encode()
    router.send_unsolicited(9, function, body)
    logger.info('Sent S9F%d', function)


def send_s9f1(router, bad_header: bytes = _DUMMY_HEADER):
    """Unrecognized Device ID."""
    _send_s9(router, 1, bad_header)


def send_s9f3(router, bad_header: bytes = _DUMMY_HEADER):
    """Unrecognized Stream Type."""
    _send_s9(router, 3, bad_header)


def send_s9f5(router, bad_header: bytes = _DUMMY_HEADER):
    """Unrecognized Function Type."""
    _send_s9(router, 5, bad_header)


def send_s9f7(router, bad_header: bytes = _DUMMY_HEADER):
    """Illegal Data."""
    _send_s9(router, 7, bad_header)


def send_s9f9(router, bad_header: bytes = _DUMMY_HEADER):
    """Transaction Timer Timeout (uses SHEAD — stored header of timed-out transaction)."""
    _send_s9(router, 9, bad_header)


def send_s9f11(router, bad_header: bytes = _DUMMY_HEADER):
    """Data Too Long."""
    _send_s9(router, 11, bad_header)


# ── Registration ──────────────────────────────────────────────────────────────
def register(router):
    """S9 messages are EQ→Host only; no incoming handlers needed.
    The router's built-in _send_s9f5 already handles unrecognised S,F pairs."""
    pass
