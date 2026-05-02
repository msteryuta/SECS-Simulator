"""
Stream 5 (Exception Handling / Alarm) handlers.

S5F1  Alarm Report Send          — EQ → Host  (unsolicited, reply needed)
S5F2  Alarm Report Acknowledge   — Host → EQ  (reply to S5F1)
S5F3  Enable/Disable Alarm Send  — Host → EQ  → S5F4
"""
import logging
from typing import Optional

from core.gem_state import ProcessState
from core.secs_codec import L, A, B, U2

logger = logging.getLogger(__name__)

# Track which ALIDs are currently in alarm
_active_alarms: set = set()
# Store process state snapshot before alarm (to restore on clear)
_pre_alarm_process: Optional[ProcessState] = None


def send_s5f1(router, alid: int, alarm_set: bool = True) -> Optional[int]:
    """
    Send S5F1 Alarm Report from EQ to Host.

    alarm_set=True  → alarm SET   (ALCD bit7=1, Process State → ALARM)
    alarm_set=False → alarm CLEAR (ALCD bit7=0, Process State restored)
    """
    global _pre_alarm_process

    alid_cfg = router.config.get('ALID', {}).get(str(alid), {})
    category = alid_cfg.get('category', 0)
    text     = alid_cfg.get('text', f'ALARM_{alid}')

    state = router.gem_state

    if alarm_set:
        # Save current process state before going into ALARM
        if alid not in _active_alarms:
            _pre_alarm_process = state.process
            _active_alarms.add(alid)
        state.transition_process(ProcessState.ALARM)
        router.publish('process_state_changed', state.process)
        alcd = 0x80 | (category & 0x7F)
    else:
        # Clear this alarm
        _active_alarms.discard(alid)
        if not _active_alarms:
            # No more active alarms — restore previous process state
            target = _pre_alarm_process if _pre_alarm_process is not None else ProcessState.IDLE
            state.transition_process(target)
            router.publish('process_state_changed', state.process)
            _pre_alarm_process = None
        alcd = category & 0x7F

    # S5F1 body: L[ALCD, ALID, ALTX]
    body = L(B(alcd), U2(alid), A(text[:120])).encode()
    action = 'SET' if alarm_set else 'CLEARED'
    al_name = alid_cfg.get('name', f'ALID_{alid}')
    sys_bytes = router.send_unsolicited(5, 1, body, tx_extra={
        'alid': alid,
        'action': action,
        'text': text,
    })

    router.publish('alarm_event', {
        'alid': alid,
        'name': al_name,
        'text': text,
        'action': action,
        'stream': 5, 'function': 1,
        'body': body,
        'sys_bytes': sys_bytes,
        'direction': 'EQ->Host',
    })
    logger.info('S5F1 sent  ALID=%d  %s  %s', alid, action, text)
    return sys_bytes


def handle_s5f2(hdr: dict, body: bytes, router) -> None:
    """S5F2 Alarm Report Acknowledge from Host — no reply needed."""
    return None


def handle_s5f3(hdr: dict, body: bytes, router) -> bytes:
    """S5F3 Enable/Disable Alarm → S5F4 (ACKC5=0 Accepted)."""
    return B(0).encode()


# ── Registration ───────────────────────────────────────────────────────────────
def register(router):
    router.register(5, 2, handle_s5f2)
    router.register(5, 3, handle_s5f3)
