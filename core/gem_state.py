"""
GEM (Generic Equipment Model) state machine — SEMI E30 compliant.

Manages:
  - Control State:  EQUIPMENT_OFFLINE / ATTEMPT_ONLINE / HOST_OFFLINE /
                    ONLINE_LOCAL / ONLINE_REMOTE
  - Process State:  IDLE / SETUP / EXECUTING / PAUSE / ALARM / STOPPING

All state access is thread-safe via RLock.
"""
import threading
import logging
from enum import IntEnum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ControlState(IntEnum):
    EQUIPMENT_OFFLINE = 1
    ATTEMPT_ONLINE    = 2
    HOST_OFFLINE      = 3
    ONLINE_LOCAL      = 4
    ONLINE_REMOTE     = 5


class ProcessState(IntEnum):
    IDLE      = 0
    SETUP     = 1
    EXECUTING = 2
    PAUSE     = 3
    ALARM     = 4
    STOPPING  = 5


# Valid transitions per SEMI E30 Control State Model
_VALID_CONTROL_TRANSITIONS = {
    ControlState.EQUIPMENT_OFFLINE: {ControlState.ATTEMPT_ONLINE},
    ControlState.ATTEMPT_ONLINE:    {ControlState.HOST_OFFLINE, ControlState.EQUIPMENT_OFFLINE},
    ControlState.HOST_OFFLINE:      {ControlState.ONLINE_LOCAL, ControlState.ONLINE_REMOTE, ControlState.EQUIPMENT_OFFLINE},
    ControlState.ONLINE_LOCAL:      {ControlState.HOST_OFFLINE, ControlState.ONLINE_REMOTE, ControlState.EQUIPMENT_OFFLINE},
    ControlState.ONLINE_REMOTE:     {ControlState.HOST_OFFLINE, ControlState.ONLINE_LOCAL,  ControlState.EQUIPMENT_OFFLINE},
}

# Map ProcessState → _ProcessState SV (VID 960)
_PROCESS_SV_MAP = {
    ProcessState.IDLE:      2,   # AutoRunStop (ReadyToPPStart)
    ProcessState.SETUP:     7,   # PowerOn
    ProcessState.EXECUTING: 1,   # AutoRunning
    ProcessState.PAUSE:     11,  # PresetStop
    ProcessState.ALARM:     6,   # Error
    ProcessState.STOPPING:  11,  # PresetStop
}


class GemState:
    """Thread-safe GEM state holder with transition callbacks."""

    def __init__(self):
        self._lock = threading.RLock()
        self._control = ControlState.EQUIPMENT_OFFLINE
        self._process = ProcessState.IDLE
        self._on_control_change: Optional[Callable] = None
        self._on_process_change: Optional[Callable] = None

        # Status Variable values (VID → value), initial defaults
        self._svid: dict = {
            1:   2,    # CommunicateStatus: NOT_COMMUNICATING
            7:   'TFC-6600',
            8:   '6.3.100',
            11:  1,    # ControlStatus: EQ_OFFLINE
            500: '',   # BottomWaferID
            501: 0,    # UnitUseSelect: Both L/R
            536: '',   # RecipeName
            551: '',   # ProcessJobID
            555: '',   # ProcessingPPID
            567: '',   # LotID
            568: '',   # WaferID
            569: '',   # SlotID
            801: '', 802: '',       # BgStgCarrierID L/R
            805: '',               # WfStgCarrierID
            881: '', 882: '',       # BgStgWaferID L/R
            885: '',               # WfStgWaferID
            921: 0, 922: 0,        # BgStgLoadStatus L/R
            925: 0,                # WfStgLoadStatus
            931: 0, 932: 0,        # BgStgPresentStatus L/R
            935: 0, 936: 0,        # WfStgPresentStatus, WfMidTblPresentStatus
            960: 2,   # _ProcessState: AutoRunStop = ReadyToPPStart (servo ON by default)
            970: '',  # PPID
            990: '',  # XmlFormatMapFile
        }

    # ── Callback setters ──────────────────────────────────────────────────────
    def set_on_control_change(self, cb: Callable):
        self._on_control_change = cb

    def set_on_process_change(self, cb: Callable):
        self._on_process_change = cb

    # ── Property accessors ────────────────────────────────────────────────────
    @property
    def control(self) -> ControlState:
        with self._lock:
            return self._control

    @property
    def process(self) -> ProcessState:
        with self._lock:
            return self._process

    @property
    def ppid(self) -> str:
        with self._lock:
            return self._svid.get(555, '')

    def set_ppid(self, ppid: str):
        with self._lock:
            self._svid[555] = ppid
            self._svid[970] = ppid
            self._svid[536] = ppid

    def get_sv(self, svid: int):
        with self._lock:
            return self._svid.get(svid)

    def set_sv(self, svid: int, value):
        with self._lock:
            self._svid[svid] = value

    def get_all_svids(self) -> dict:
        with self._lock:
            return dict(self._svid)

    # ── State transitions ─────────────────────────────────────────────────────
    def transition_control(self, new_state: ControlState) -> bool:
        """Attempt a validated control state transition. Returns True on success."""
        with self._lock:
            old = self._control
            if new_state not in _VALID_CONTROL_TRANSITIONS.get(old, set()):
                logger.warning(f'Invalid control transition: {old.name} → {new_state.name}')
                return False
            self._control = new_state
            self._svid[11] = int(new_state)
            self._svid[1] = 3 if new_state in (
                ControlState.HOST_OFFLINE,
                ControlState.ONLINE_LOCAL,
                ControlState.ONLINE_REMOTE,
            ) else 2

        if self._on_control_change:
            self._on_control_change(old, new_state)
        return True

    def force_control(self, new_state: ControlState):
        """Force control state without validation (for init / testing)."""
        with self._lock:
            old = self._control
            self._control = new_state
            self._svid[11] = int(new_state)
            self._svid[1] = 3 if new_state in (
                ControlState.HOST_OFFLINE,
                ControlState.ONLINE_LOCAL,
                ControlState.ONLINE_REMOTE,
            ) else 2
        if self._on_control_change:
            self._on_control_change(old, new_state)

    def transition_process(self, new_state: ProcessState):
        """Change process state and update related SVIDs."""
        with self._lock:
            old = self._process
            self._process = new_state
            self._svid[960] = _PROCESS_SV_MAP.get(new_state, 0)
        if self._on_process_change:
            self._on_process_change(old, new_state)

    # ── Convenience queries ───────────────────────────────────────────────────
    def is_online(self) -> bool:
        return self.control in (ControlState.ONLINE_LOCAL, ControlState.ONLINE_REMOTE)

    def is_online_remote(self) -> bool:
        return self.control == ControlState.ONLINE_REMOTE

    def is_online_local(self) -> bool:
        return self.control == ControlState.ONLINE_LOCAL
