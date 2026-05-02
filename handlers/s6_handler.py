"""
Stream 6 (Data Collection) handlers.

S6F11  Event Report Send  — EQ → Host  (unsolicited)
S6F12  Event Report Ack   — Host → EQ  (reply to S6F11)
"""
import logging
from typing import Optional

from core.secs_codec import L, A, B, U4

logger = logging.getLogger(__name__)

_dataid_counter = 1


def _next_dataid() -> int:
    global _dataid_counter
    val = _dataid_counter
    _dataid_counter = (_dataid_counter + 1) & 0xFFFFFFFF
    return val


def send_s6f11(router, ceid: int, vars: list = None) -> Optional[int]:
    """
    Send S6F11 Event Report from EQ to Host.

    Args:
        router: the SecsRouter instance
        ceid:   Collection Event ID
        vars:   Optional explicit list of SecsItem objects to use as report variables.
                When provided, the SVID lookup in config is skipped.
                When None, variables are built from the VIDs listed in config CEID def.

    S6F11 body structure:
        L[DATAID, CEID, L[ L[RPTID, L[V1..Vn]] ]]

    Returns the system-bytes of the sent frame, or None if not connected.
    """
    ceid_cfg = router.config.get('CEID', {}).get(str(ceid), {})
    name     = ceid_cfg.get('name', f'CEID_{ceid}')
    rptid    = ceid_cfg.get('rptid', ceid)
    sv_vids  = ceid_cfg.get('vids', [])

    state = router.gem_state

    if vars is not None:
        # Caller supplied explicit variable items (contextual, not SVID-based)
        vid_items = list(vars)
    else:
        # Build from SVID state lookup
        vid_items = []
        for vid in sv_vids:
            sv = state.get_sv(vid)
            if isinstance(sv, int):
                vid_items.append(U4(sv))
            elif isinstance(sv, str):
                vid_items.append(A(sv))
            else:
                vid_items.append(A(''))

    # Always include the report block (spec requires L[RPTID, L[vars]])
    report_block = L(U4(rptid), L(*vid_items))
    body = L(
        U4(_next_dataid()),
        U4(ceid),
        L(report_block),
    ).encode()

    sys_bytes = router.send_unsolicited(6, 11, body)

    # Notify GUI for sniffer + EQ panel event log
    router.publish('eq_event', {
        'ceid': ceid, 'ceid_name': name,
        'stream': 6, 'function': 11,
        'body': body, 'sys_bytes': sys_bytes,
        'direction': 'EQ->Host',
        'description': f'Event Report Send  CEID={ceid} ({name})',
    })

    logger.info('S6F11 sent  CEID=%d (%s)', ceid, name)
    return sys_bytes


def handle_s6f12(hdr: dict, body: bytes, router) -> None:
    """S6F12 Event Report Acknowledge from Host — no reply needed."""
    ackc6 = 0
    if body:
        try:
            from core.secs_codec import decode_item
            item, _ = decode_item(body)
            raw = item.value
            ackc6 = raw[0] if isinstance(raw, (bytes, bytearray)) else 0
        except Exception:
            pass
    logger.debug('S6F12 received  ACKC6=%d', ackc6)
    return None


# ── Registration ───────────────────────────────────────────────────────────────
def register(router):
    router.register(6, 12, handle_s6f12)
