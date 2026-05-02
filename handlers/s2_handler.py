"""
Stream 2 (Equipment Control) handlers.

Key handlers:
  S2F41  Host Command Send    → S2F42 Acknowledge  (sync ack)
         Then fires CEIDs via background thread     (async execution)
  S2F13  Equipment Constant Request → S2F14
  S2F17  Date & Time Request  → S2F18
  S2F29  Constant Namelist    → S2F30
  S2F31  Date & Time Set      → S2F32
  S2F33  Define Report        → S2F34
  S2F35  Link Event Report    → S2F36
  S2F37  Enable/Disable Event → S2F38

HCACK codes:
  0  = Acknowledged, performed
  1  = Command does not exist
  2  = Cannot perform now
  3  = At least one parameter invalid
  4  = Acknowledged, completion signalled later by event
  5  = Already in desired condition
"""
import datetime
import threading
import time
import logging
from typing import Optional, List, Tuple

from core.secs_codec import L, A, B, U1, U4, decode_item, Fmt
from core.gem_state import ControlState, ProcessState

logger = logging.getLogger(__name__)

HCACK_OK          = 0
HCACK_NO_CMD      = 1
HCACK_CANNOT_NOW  = 2
HCACK_BAD_PARAM   = 3
HCACK_WILL_SIGNAL = 4
HCACK_ALREADY     = 5
HCACK_SERVO_OFF   = 65
HCACK_NOT_READY   = 72
HCACK_NO_MAP      = 71


# ── S2F41 body parser ──────────────────────────────────────────────────────────
def _parse_s2f41(body: bytes) -> Tuple[str, dict]:
    if not body:
        return '', {}
    try:
        item, _ = decode_item(body)
    except Exception:
        return '', {}
    if item.fmt != Fmt.LIST or len(item.value) < 1:
        return '', {}
    rcmd = item.value[0].value if item.value[0].fmt == Fmt.ASCII else ''
    params: dict = {}
    if len(item.value) >= 2 and item.value[1].fmt == Fmt.LIST:
        for pair in item.value[1].value:
            if pair.fmt == Fmt.LIST and len(pair.value) >= 2:
                name = pair.value[0].value if pair.value[0].fmt == Fmt.ASCII else ''
                params[name] = pair.value[1].value
    return rcmd, params


def _build_s2f42(hcack: int, errors: List[Tuple[str, int]]) -> bytes:
    err_items = [L(A(name), B(cpack)) for name, cpack in errors]
    return L(B(hcack), L(*err_items)).encode()


def _validate_params(params: dict, schema: dict) -> List[Tuple[str, int]]:
    errors = []
    for name, spec in schema.items():
        if spec.get('required') and name not in params:
            errors.append((name, 1))
    return errors


# ── Event firing helper ────────────────────────────────────────────────────────
def _fire(router, ceid: int, vars: list = None):
    """Send S6F11 for ceid.  vars is an optional list of SecsItem objects."""
    from handlers.s6_handler import send_s6f11
    send_s6f11(router, ceid, vars)


def _fire_after(router, ceid: int, delay: float, vars: list = None):
    time.sleep(delay)
    _fire(router, ceid, vars)


# ── Stage SVID helper ──────────────────────────────────────────────────────────
def _deviceside(params: dict) -> int:
    """Return 1 (Left) or 2 (Right) from DEVICESIDE param, default 1."""
    try:
        return int(str(params.get('DEVICESIDE', '1')).strip())
    except Exception:
        return 1


def _set_bg_stage(state, side: int, present: int):
    """Update BgStg SVIDs.  side=1→L, side=2→R."""
    if side == 2:
        state.set_sv(932, present)   # BgStgPresentStatus-R
    else:
        state.set_sv(931, present)   # BgStgPresentStatus-L


# ── Async execution helpers ────────────────────────────────────────────────────
def _simulate_start(params: dict, router, state):
    """Background thread: simulate START auto-run cycle.

    Real-machine sequence (dual-side, L and R reported separately):
      CEID 259 x2  BgStgPresenceInformation (side=1, side=2)
      CEID 107 x2  BottomWaferStart         (side=1 with wafer data, side=2)
      CEID 150 x2  ProcessStart             (side=1, side=2)
      CEID 140 x2  AutorunStart             (side=1, side=2)
      [bonding]
      CEID 151     ProcessEnd
      CEID 141     AutorunEnd
    """
    wafer_l  = str(params.get('BOTTOMWAFERID-L', ''))
    wafer_r  = str(params.get('BOTTOMWAFERID-R', ''))
    carrier_l = str(params.get('CARRIERID-L', ''))
    carrier_r = str(params.get('CARRIERID-R', ''))

    state.set_sv(801, carrier_l)
    state.set_sv(881, wafer_l)
    state.set_sv(802, carrier_r)
    state.set_sv(882, wafer_r)
    state.set_sv(921, 0)           # BgStgLoadStatus-L = not ready
    state.set_sv(922, 0)           # BgStgLoadStatus-R = not ready
    state.set_sv(931, 1)           # BgStgPresentStatus-L = present
    state.set_sv(932, 1)           # BgStgPresentStatus-R = present
    state.transition_process(ProcessState.EXECUTING)
    router.publish('process_state_changed', state.process)

    # CEID 259 × 2  BgStgPresenceInformation for L (side=1) then R (side=2)
    _fire(router, 259, [U4(1)])    # side=1 (Left)
    time.sleep(0.05)
    _fire(router, 259, [U4(1)])    # side=2 (Right) — same presence flag per spec

    # CEID 107 × 2  BottomWaferStart: deviceside, flag, waferid, lotid, slotid
    time.sleep(0.05)
    _fire(router, 107, [U4(1), A('1'), A(wafer_l), A(''), A('')])
    time.sleep(0.05)
    _fire(router, 107, [U4(2), A('1'), A(wafer_r), A(''), A('')])

    # CEID 150 × 2  ProcessStart: deviceside, waferid, lotid, slotid
    time.sleep(0.05)
    _fire(router, 150, [U4(1), A(wafer_l), A(''), A('')])
    time.sleep(0.05)
    _fire(router, 150, [U4(2), A(wafer_r), A(''), A('')])

    # CEID 140 × 2  AutorunStart (no variables)
    time.sleep(0.05)
    _fire(router, 140, [])
    time.sleep(0.05)
    _fire(router, 140, [])

    time.sleep(3.0)                # Simulate bonding duration

    _fire(router, 151)             # ProcessEnd (SVID-based vars)
    time.sleep(0.3)
    state.set_sv(931, 0)
    state.set_sv(932, 0)
    _fire(router, 141)             # AutorunEnd

    state.transition_process(ProcessState.IDLE)
    router.publish('process_state_changed', state.process)


def _simulate_bottomstagegoready(params: dict, router, state):
    side = _deviceside(params)
    time.sleep(0.5)
    # CEID 142 report: L[1] = deviceside (U4)
    _fire(router, 142, [U4(side)])


def _simulate_bottommapread(params: dict, router, state):
    """After BOTTOMMAPREAD: EQ reports CEID 153 TopBinRequest.
    Report: L[2] = A(deviceside_str), U4(1)
    """
    time.sleep(0.35)
    fn = str(params.get('MAPFILENAME', '')).strip()
    if fn:
        state.set_sv(990, fn)
    side_str = str(params.get('DEVICESIDE', '1')).strip()
    # CEID 153 report vars: A(deviceside), U4(1)  (matches real machine log)
    _fire(router, 153, [A(side_str), U4(1)])


def _simulate_bottomwaferloadcomplete(params: dict, router, state):
    """After BOTTOMWAFERLOADCOMPLETE: CEID 107 only (259 is tied to START per CEID table).

    CEID 107 report: L[5] = deviceside(U4), flag(A), waferid(A), lotid(A), slotid(A)
    Real machine sends empty strings for most fields here (wafer ID comes from
    the SVIDs set by BOTTOMWAFERLOADCOMPLETE, not passed in the report itself).
    """
    side = _deviceside(params)
    time.sleep(0.3)
    _set_bg_stage(state, side, 1)  # Wafer now present
    wafer_id  = str(params.get('BOTTOMWAFERID', ''))
    carrier_id = str(params.get('CARRIERID', ''))
    lot_id    = str(params.get('LOTID', ''))
    slot_id   = str(params.get('SLOTID', ''))
    state.set_sv(801 if side == 1 else 802, carrier_id)
    state.set_sv(881 if side == 1 else 882, wafer_id)
    state.set_sv(500, wafer_id)
    state.set_sv(568, wafer_id)
    state.set_sv(567, lot_id)
    state.set_sv(569, slot_id)
    # CEID 107 report: deviceside, empty flag, empty waferid, empty lotid, empty slotid
    # (real machine sends empty here — data is in SVIDs, accessible via S1F3)
    _fire(router, 107, [U4(side), A(''), A(''), A(''), A('')])


def _simulate_bottomwaferunloadcomplete(params: dict, router, state):
    side = _deviceside(params)
    time.sleep(0.3)
    _set_bg_stage(state, side, 0)  # Wafer removed
    _fire(router, 260)             # BgStageUnloadMove
    time.sleep(0.4)
    _fire(router, 262)             # LogStored


def _simulate_waferstagegoready(params: dict, router, state):
    """Sequence per spec: WfStgReady (144) → WfStgPresenceInfo (258).
    CEID 258 report: L[3] = WfStgPresentStatus(U4), WfMidTblPresentStatus(U4), WfStgLoadStatus(U4)
    """
    time.sleep(0.5)
    state.set_sv(935, 0)           # Wafer Stage empty (ready to receive)
    state.set_sv(936, 0)
    state.set_sv(925, 1)           # WfStgLoadStatus = ready
    _fire(router, 144, [])         # WfStgReady (no vars)
    time.sleep(0.2)
    # CEID 258 report: presence=0, midtbl=0, loadstatus=1
    _fire(router, 258, [U4(state.get_sv(935) or 0),
                        U4(state.get_sv(936) or 0),
                        U4(state.get_sv(925) or 0)])


def _simulate_topwaferloadcomplete(params: dict, router, state):
    """Sequence: update SVIDs → WfStgPresenceInfo (258)."""
    time.sleep(0.3)
    state.set_sv(935, 1)           # Top Wafer now present
    state.set_sv(936, 0)
    state.set_sv(885, str(params.get('TOPWAFERID', '')))
    state.set_sv(805, str(params.get('CARRIERID', '')))
    state.set_sv(568, str(params.get('TOPWAFERID', '')))
    state.set_sv(567, str(params.get('LOTID', '')))
    state.set_sv(569, str(params.get('SLOTID', '')))
    _fire(router, 258)             # WfStgPresenceInformation


def _simulate_topwaferunloadrequest(params: dict, router, state):
    """Sequence: WfStgPresenceInfo (258) → WfReadyToUnload (145) → TopWfStgUnloadMove (261)."""
    time.sleep(0.5)
    state.set_sv(935, 0)           # Wafer about to leave
    state.set_sv(936, 0)
    _fire(router, 258)             # WfStgPresenceInformation
    time.sleep(0.3)
    _fire(router, 145)             # WfReadyToUnload
    time.sleep(0.2)
    _fire(router, 261)             # TopWaferStageUnloadMove


def _simulate_topwaferunloadcomplete(params: dict, router, state):
    """Sequence: WfStgPresenceInfo (258) → WfUnloadFinish (146) → TopWfStgUnloadMove (261)."""
    time.sleep(0.3)
    state.set_sv(935, 0)           # Top Wafer removed
    state.set_sv(885, '')
    _fire(router, 258)             # WfStgPresenceInformation
    time.sleep(0.3)
    _fire(router, 146)             # WfUnloadFinish
    time.sleep(0.2)
    _fire(router, 261)             # TopWaferStageUnloadMove


def _simulate_generic(ceid_list: list, delay: float, router):
    for ceid in ceid_list:
        time.sleep(delay)
        _fire(router, ceid)


# Map RCMD name → custom async simulation function (or None = use _simulate_generic)
_ASYNC_HANDLERS = {
    'START':                    _simulate_start,
    'BOTTOMSTAGEGOREADY':       _simulate_bottomstagegoready,
    'BOTTOMMAPREAD':            _simulate_bottommapread,
    'BOTTOMWAFERLOADCOMPLETE':  _simulate_bottomwaferloadcomplete,
    'BOTTOMWAFERUNLOADCOMPLETE':_simulate_bottomwaferunloadcomplete,
    'WAFERSTAGEGOREADY':        _simulate_waferstagegoready,
    'TOPWAFERLOADCOMPLETE':     _simulate_topwaferloadcomplete,
    'TOPWAFERLOADCOMPLETE2':    _simulate_topwaferloadcomplete,
    'TOPWAFERUNLOADREQUEST':    _simulate_topwaferunloadrequest,
    'TOPWAFERUNLOADCOMPLETE':   _simulate_topwaferunloadcomplete,
}


# ── Immediate (synchronous) state changes ──────────────────────────────────────
def _apply_immediate(rcmd: str, params: dict, state, router):
    if rcmd == 'GOLOCAL':
        state.transition_control(ControlState.ONLINE_LOCAL)
    elif rcmd == 'GOREMOTE':
        state.transition_control(ControlState.ONLINE_REMOTE)
    elif rcmd == 'PPSELECT':
        ppid = str(params.get('PPID', ''))
        state.set_ppid(ppid)
        router.publish('ppid_changed', ppid)
    elif rcmd == 'STOP':
        if state.process == ProcessState.EXECUTING:
            state.transition_process(ProcessState.STOPPING)
            router.publish('process_state_changed', state.process)


# ── Main S2F41 handler ─────────────────────────────────────────────────────────
def handle_s2f41(hdr: dict, body: bytes, router) -> bytes:
    """S2F41 Host Command Send → S2F42 Acknowledge.

    HCACK codes returned:
      0  Acknowledged, performed          — all valid commands (including async ones)
      1  Command does not exist           — unknown RCMD name
      2  Cannot perform now              — START while already EXECUTING
      3  At least one parameter invalid   — missing required param
      65 Rejected (Servo is OFF)          — START with servo off
    """
    rcmd, params = _parse_s2f41(body)
    cmd_cfg = router.config.get('RCMD', {}).get(rcmd)

    if cmd_cfg is None:
        logger.warning('Unknown RCMD: %r', rcmd)
        return _build_s2f42(HCACK_NO_CMD, [])

    state = router.gem_state

    # Pre-condition checks
    if rcmd == 'START':
        if state.process == ProcessState.EXECUTING:
            return _build_s2f42(HCACK_CANNOT_NOW, [])
        if state.get_sv(960) == 9:        # ServoOff
            return _build_s2f42(HCACK_SERVO_OFF, [])

    # Parameter validation
    schema = cmd_cfg.get('params', {})
    errors = _validate_params(params, schema)
    if errors:
        return _build_s2f42(HCACK_BAD_PARAM, errors)

    triggers  = cmd_cfg.get('triggers_events', [])
    async_fn  = _ASYNC_HANDLERS.get(rcmd)

    # Special fast-path: GOREMOTE / GOLOCAL fire their S6F11 BEFORE S2F42
    # (matches real machine behavior where S6F11 arrives before or with S2F42)
    if rcmd in ('GOREMOTE', 'GOLOCAL'):
        _apply_immediate(rcmd, params, state, router)
        ceid = 2 if rcmd == 'GOREMOTE' else 1
        _fire(router, ceid)        # S6F11 sent synchronously before S2F42
        return _build_s2f42(HCACK_OK, [])

    _apply_immediate(rcmd, params, state, router)

    # Pure immediate commands (no async events)
    if not triggers and async_fn is None:
        return _build_s2f42(HCACK_OK, [])

    # Async execution in background thread
    if async_fn is not None:
        t = threading.Thread(target=async_fn, args=(params, router, state),
                             daemon=True, name=f'EQ-{rcmd}')
    else:
        t = threading.Thread(target=_simulate_generic,
                             args=(triggers, 0.4, router),
                             daemon=True, name=f'EQ-{rcmd}')
    t.start()

    # Real machines always return HCACK=0 ("acknowledged, performed") even for
    # async commands — the S6F11 events come separately after.
    return _build_s2f42(HCACK_OK, [])


# ── Supporting S2 handlers ─────────────────────────────────────────────────────
def handle_s2f13(hdr, body, router): return L().encode()
def handle_s2f17(hdr, body, router):
    now = datetime.datetime.now().strftime('%Y%m%d%H%M%S00')
    return A(now).encode()
def handle_s2f29(hdr, body, router): return L().encode()
def handle_s2f31(hdr, body, router): return B(0).encode()   # TIACK=0
def handle_s2f33(hdr, body, router): return B(0).encode()   # DRACK=0
def handle_s2f35(hdr, body, router): return B(0).encode()   # LRACK=0
def handle_s2f37(hdr, body, router): return B(0).encode()   # ERACK=0


# ── Registration ───────────────────────────────────────────────────────────────
def register(router):
    router.register(2, 13, handle_s2f13)
    router.register(2, 17, handle_s2f17)
    router.register(2, 29, handle_s2f29)
    router.register(2, 31, handle_s2f31)
    router.register(2, 33, handle_s2f33)
    router.register(2, 35, handle_s2f35)
    router.register(2, 37, handle_s2f37)
    router.register(2, 41, handle_s2f41)
