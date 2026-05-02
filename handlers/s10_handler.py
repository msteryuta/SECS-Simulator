"""
Stream 10 (Terminal Services) handlers.

HOST → EQ terminal display messages:
  S10F3  Terminal Display Single (TID + TEXT)     → S10F4 ACKC10
  S10F5  Terminal Display Multi-Block (TID + L[n] TEXT) → S10F6 ACKC10

ACKC10 codes:
  0 = Accepted for display
  1 = Message not displayed
  2 = Terminal not available
"""
import logging
from core.secs_codec import B, decode_item, Fmt

logger = logging.getLogger(__name__)

_ACKC10_OK = 0


def _parse_tid_text(body: bytes):
    """Return (tid, text) from S10F3/F5 body.  Returns ('', '') on parse error."""
    if not body:
        return 0, ''
    try:
        item, _ = decode_item(body)
        if item.fmt != Fmt.LIST or len(item.value) < 2:
            return 0, str(item.value)
        tid_item  = item.value[0]
        text_item = item.value[1]
        tid  = tid_item.value[0] if isinstance(tid_item.value, (bytes, bytearray)) else 0
        if text_item.fmt == Fmt.ASCII:
            text = text_item.value
        elif text_item.fmt == Fmt.LIST:
            text = ' | '.join(
                t.value for t in text_item.value if t.fmt == Fmt.ASCII
            )
        else:
            text = str(text_item.value)
        return tid, text
    except Exception:
        return 0, ''


def handle_s10f3(hdr: dict, body: bytes, router) -> bytes:
    """Single-line terminal display.  Always accept (ACKC10=0)."""
    tid, text = _parse_tid_text(body)
    logger.info('S10F3 Terminal Display  TID=%d  TEXT=%r', tid, text)
    router.publish('terminal_display', {'tid': tid, 'text': text, 'multi': False})
    return B(_ACKC10_OK).encode()


def handle_s10f5(hdr: dict, body: bytes, router) -> bytes:
    """Multi-block terminal display.  Always accept (ACKC10=0)."""
    tid, text = _parse_tid_text(body)
    logger.info('S10F5 Terminal Display Multi  TID=%d  TEXT=%r', tid, text[:80])
    router.publish('terminal_display', {'tid': tid, 'text': text, 'multi': True})
    return B(_ACKC10_OK).encode()


# ── Registration ──────────────────────────────────────────────────────────────
def register(router):
    router.register(10, 3, handle_s10f3)
    router.register(10, 5, handle_s10f5)
