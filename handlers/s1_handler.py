"""
Stream 1 (Equipment Status) handlers.

Supported:  S1F1/F2  Are You There / On Line Data
            S1F3/F4  Selected Equipment Status Request / Data
            S1F13/F14 Establish Communications
            S1F15/F16 Request OFF-LINE / Acknowledge
            S1F17/F18 Request ON-LINE / Acknowledge
"""
import logging
from typing import Optional

from core.secs_codec import L, A, B, U1, U2, U4, decode_item, Fmt
from core.gem_state import ControlState

logger = logging.getLogger(__name__)


def handle_s1f1(hdr: dict, body: bytes, router) -> bytes:
    """S1F1 Are You There → S1F2 On Line Data."""
    cfg = router.config
    reply = L(A(cfg.get('MODEL', 'UNKNOWN')[:6]),
               A(cfg.get('SOFTREV', '0.0.0')[:6]))
    return reply.encode()


def handle_s1f2(hdr: dict, body: bytes, router) -> None:
    """S1F2 On Line Data from Host — no reply required."""
    return None


def handle_s1f3(hdr: dict, body: bytes, router) -> bytes:
    """S1F3 Selected Equipment Status Request → S1F4.

    Responds with one SECS item per requested SVID, typed according to the
    'format' field in the SVID config definition:
      U1  → U1 item   (e.g. ControlStatus SVID 11)
      U2  → U2 item
      U4  → U4 item   (default for integer SVIDs)
      ASCII / A → A item
    """
    state    = router.gem_state
    svid_cfg = router.config.get('SVID', {})
    svids: list = []
    if body:
        try:
            item, _ = decode_item(body)
            if item.fmt == Fmt.LIST:
                svids = [int(sv.value) for sv in item.value]
        except Exception:
            pass

    if svids:
        values = [_sv_item_typed(state.get_sv(sid), svid_cfg.get(str(sid), {}))
                  for sid in svids]
    else:
        values = [_sv_item(v) for v in state.get_all_svids().values()]

    return L(*values).encode()


def handle_s1f13(hdr: dict, body: bytes, router) -> bytes:
    """S1F13 Establish Communications Request → S1F14."""
    state = router.gem_state
    cfg   = router.config

    # Transition: EQ_OFFLINE → ATTEMPT_ONLINE → HOST_OFFLINE
    if state.control == ControlState.EQUIPMENT_OFFLINE:
        state.transition_control(ControlState.ATTEMPT_ONLINE)
        state.transition_control(ControlState.HOST_OFFLINE)
        commack = B(0)   # 0 = Accepted
    elif state.is_online():
        commack = B(0)   # Already comms established, still accept
    else:
        commack = B(0)

    reply = L(commack, L(A(cfg.get('MODEL', 'UNKNOWN')[:6]),
                          A(cfg.get('SOFTREV', '0.0.0')[:6])))
    return reply.encode()


def handle_s1f15(hdr: dict, body: bytes, router) -> bytes:
    """S1F15 Request OFF-LINE → S1F16 (OFLACK)."""
    state = router.gem_state
    if state.is_online():
        state.transition_control(ControlState.HOST_OFFLINE)
        # CEID 3 (HostOffline) fired via gem_state callback → main_window
        oflack = 0   # OFF-LINE Acknowledge
    else:
        oflack = 0   # Already offline, still ack
    return B(oflack).encode()


def handle_s1f17(hdr: dict, body: bytes, router) -> bytes:
    """S1F17 Request ON-LINE → S1F18 (ONLACK)."""
    state  = router.gem_state
    onlack_cfg = router.config.get('CurrentONLACK', 0)

    if state.control in (ControlState.HOST_OFFLINE, ControlState.EQUIPMENT_OFFLINE):
        if state.control == ControlState.EQUIPMENT_OFFLINE:
            state.transition_control(ControlState.ATTEMPT_ONLINE)
            state.transition_control(ControlState.HOST_OFFLINE)
        ok = state.transition_control(ControlState.ONLINE_REMOTE)
        onlack = 0 if ok else 1      # 0=Accepted  1=Not Allowed
    elif state.is_online():
        onlack = 2                   # Already ONLINE
    else:
        onlack = onlack_cfg if onlack_cfg != 0 else 1

    return B(onlack).encode()


# ── Helpers ────────────────────────────────────────────────────────────────────
def _sv_item(value):
    """Convert a status-variable value to the appropriate SECS item (generic)."""
    if isinstance(value, int):
        return U4(value)
    if isinstance(value, str):
        return A(value)
    return A(str(value) if value is not None else '')


def _sv_item_typed(value, cfg: dict):
    """Convert a status-variable value using the SVID format from config."""
    fmt = cfg.get('format', 'U4') if cfg else 'U4'
    if value is None:
        return A('') if fmt in ('ASCII', 'A') else U4(0)
    if fmt == 'U1':
        return U1(int(value) if isinstance(value, (int, float)) else 0)
    if fmt == 'U2':
        return U2(int(value) if isinstance(value, (int, float)) else 0)
    if fmt in ('ASCII', 'A'):
        return A(str(value))
    # Default: U4
    return U4(int(value) if isinstance(value, (int, float)) else 0)


# ── Registration ───────────────────────────────────────────────────────────────
def register(router):
    router.register(1,  1, handle_s1f1)
    router.register(1,  2, handle_s1f2)
    router.register(1,  3, handle_s1f3)
    router.register(1, 13, handle_s1f13)
    router.register(1, 15, handle_s1f15)
    router.register(1, 17, handle_s1f17)
