"""
SECS message router + publish/subscribe event bus.

Router pattern: (stream, function) → handler function.
No if-else chains — adding a new SxFy means one line in the handlers' register().

Pub/Sub: core layer never touches GUI directly; it publishes named events
         and the GUI subscribes to them. This prevents tight coupling.
"""
import logging
from typing import Callable, Dict, List, Optional, Tuple

from core.secs_codec import decode_item, SecsItem, B

logger = logging.getLogger(__name__)

HandlerFn = Callable[[dict, bytes, 'SecsRouter'], Optional[bytes]]


class SecsRouter:
    """
    Dispatches received SECS messages to handler functions.
    Also acts as the application event bus (subscribe / publish).
    """

    def __init__(self, gem_state, hsms_server, config: dict):
        self.gem_state   = gem_state
        self.hsms_server = hsms_server
        self.config      = config
        self._routes: Dict[Tuple[int, int], HandlerFn] = {}
        self._subscribers: Dict[str, List[Callable]] = {}

    # ── Route registration ─────────────────────────────────────────────────
    def register(self, stream: int, function: int, handler: HandlerFn):
        self._routes[(stream, function)] = handler
        logger.debug('Registered S%dF%d', stream, function)

    # ── Message dispatch ───────────────────────────────────────────────────
    def process_message(self, hdr: dict, body: bytes):
        """Called by HSMS layer or HOST panel when a message arrives."""
        s, f = hdr['stream'], hdr['function']
        handler = self._routes.get((s, f))

        self.publish('rx_message', {
            'stream': s, 'function': f, 'body': body,
            'sys_bytes': hdr['sys_bytes'], 'direction': hdr.get('direction', 'Host->EQ'),
            'description': hdr.get('description', f'S{s}F{f}'),
            'extra': hdr.get('extra'),
            'wbit': hdr.get('wbit', False),
        })

        if handler is None:
            logger.warning('No handler for S%dF%d — sending S9F5', s, f)
            self._send_s9f5(hdr['raw_header'])
            return

        try:
            reply_body = handler(hdr, body, self)
        except Exception:
            logger.exception('Handler error for S%dF%d', s, f)
            return

        if reply_body is not None and hdr.get('wbit', False):
            reply_s = s
            reply_f = f + 1
            sys_bytes = hdr['sys_bytes']
            # Send over TCP if a real session exists; always show in GUI
            self.hsms_server.send_message(reply_s, reply_f, False, reply_body, sys_bytes)
            self.publish('tx_message', {
                'stream': reply_s, 'function': reply_f,
                'body': reply_body, 'sys_bytes': sys_bytes,
                'direction': 'EQ->Host',
            })

    def send_unsolicited(self, stream: int, function: int, body: bytes,
                         tx_extra: Optional[dict] = None) -> Optional[int]:
        """Send EQ-initiated message (e.g. S6F11, S5F1) to Host."""
        sys_bytes = self.hsms_server.send_message(stream, function, True, body)
        msg = {
            'stream': stream, 'function': function,
            'body': body, 'sys_bytes': sys_bytes,
            'direction': 'EQ->Host',
        }
        if tx_extra:
            msg.update(tx_extra)
        self.publish('tx_message', msg)
        return sys_bytes

    # ── Error responses ────────────────────────────────────────────────────
    def _send_s9f5(self, raw_header: bytes):
        """S9F5 Unrecognized Function — echo the offending header."""
        item = B(*raw_header)
        self.hsms_server.send_message(9, 5, False, item.encode())

    # ── Pub / Sub ──────────────────────────────────────────────────────────
    def subscribe(self, event: str, callback: Callable):
        self._subscribers.setdefault(event, []).append(callback)

    def publish(self, event: str, data):
        for cb in self._subscribers.get(event, []):
            try:
                cb(data)
            except Exception:
                logger.exception('Subscriber error for event "%s"', event)

    # ── Utility ────────────────────────────────────────────────────────────
    def decode_body(self, body: bytes) -> Optional[SecsItem]:
        if not body:
            return None
        try:
            item, _ = decode_item(body)
            return item
        except Exception:
            return None
