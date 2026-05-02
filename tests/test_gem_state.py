"""Unit tests for core/gem_state.py — GEM state machine."""
import pytest
from core.gem_state import GemState, ControlState, ProcessState


@pytest.fixture
def state():
    return GemState()


# ── Initial state ──────────────────────────────────────────────────────────────
class TestInitialState:
    def test_control_state(self, state):
        assert state.control == ControlState.EQUIPMENT_OFFLINE

    def test_process_state(self, state):
        assert state.process == ProcessState.IDLE

    def test_svid_comm_status(self, state):
        assert state.get_sv(1) == 2    # NOT_COMMUNICATING

    def test_svid_control_status(self, state):
        assert state.get_sv(11) == 1   # EQ_OFFLINE


# ── Control state transitions ──────────────────────────────────────────────────
class TestControlTransitions:
    def test_offline_to_attempt(self, state):
        assert state.transition_control(ControlState.ATTEMPT_ONLINE) is True
        assert state.control == ControlState.ATTEMPT_ONLINE

    def test_attempt_to_host_offline(self, state):
        state.transition_control(ControlState.ATTEMPT_ONLINE)
        assert state.transition_control(ControlState.HOST_OFFLINE) is True

    def test_host_offline_to_online_remote(self, state):
        state.force_control(ControlState.HOST_OFFLINE)
        assert state.transition_control(ControlState.ONLINE_REMOTE) is True
        assert state.control == ControlState.ONLINE_REMOTE

    def test_host_offline_to_online_local(self, state):
        state.force_control(ControlState.HOST_OFFLINE)
        assert state.transition_control(ControlState.ONLINE_LOCAL) is True

    def test_online_remote_to_online_local(self, state):
        state.force_control(ControlState.ONLINE_REMOTE)
        assert state.transition_control(ControlState.ONLINE_LOCAL) is True

    def test_online_local_to_online_remote(self, state):
        state.force_control(ControlState.ONLINE_LOCAL)
        assert state.transition_control(ControlState.ONLINE_REMOTE) is True

    def test_online_to_host_offline(self, state):
        state.force_control(ControlState.ONLINE_REMOTE)
        assert state.transition_control(ControlState.HOST_OFFLINE) is True

    def test_invalid_offline_to_online_remote(self, state):
        """Cannot skip directly from EQ_OFFLINE to ONLINE_REMOTE."""
        result = state.transition_control(ControlState.ONLINE_REMOTE)
        assert result is False
        assert state.control == ControlState.EQUIPMENT_OFFLINE

    def test_invalid_attempt_to_online_remote(self, state):
        state.transition_control(ControlState.ATTEMPT_ONLINE)
        result = state.transition_control(ControlState.ONLINE_REMOTE)
        assert result is False

    def test_svid_updated_on_transition(self, state):
        state.force_control(ControlState.HOST_OFFLINE)
        state.transition_control(ControlState.ONLINE_REMOTE)
        assert state.get_sv(11) == int(ControlState.ONLINE_REMOTE)

    def test_comm_status_online(self, state):
        state.force_control(ControlState.HOST_OFFLINE)
        state.transition_control(ControlState.ONLINE_REMOTE)
        assert state.get_sv(1) == 3    # COMMUNICATING

    def test_comm_status_offline(self, state):
        assert state.get_sv(1) == 2    # NOT_COMMUNICATING

    def test_force_control_bypasses_validation(self, state):
        state.force_control(ControlState.ONLINE_REMOTE)
        assert state.control == ControlState.ONLINE_REMOTE


# ── Control state callbacks ────────────────────────────────────────────────────
class TestControlCallbacks:
    def test_callback_on_valid_transition(self, state):
        changes = []
        state.set_on_control_change(lambda o, n: changes.append((o, n)))
        state.force_control(ControlState.HOST_OFFLINE)
        state.transition_control(ControlState.ONLINE_REMOTE)
        assert (ControlState.HOST_OFFLINE, ControlState.ONLINE_REMOTE) in changes

    def test_no_callback_on_invalid_transition(self, state):
        changes = []
        state.set_on_control_change(lambda o, n: changes.append((o, n)))
        state.transition_control(ControlState.ONLINE_REMOTE)   # invalid
        assert len(changes) == 0

    def test_callback_on_force(self, state):
        changes = []
        state.set_on_control_change(lambda o, n: changes.append(n))
        state.force_control(ControlState.ONLINE_LOCAL)
        assert ControlState.ONLINE_LOCAL in changes


# ── Process state ──────────────────────────────────────────────────────────────
class TestProcessState:
    def test_transition_to_executing(self, state):
        state.transition_process(ProcessState.EXECUTING)
        assert state.process == ProcessState.EXECUTING

    def test_sv960_executing(self, state):
        state.transition_process(ProcessState.EXECUTING)
        assert state.get_sv(960) == 1   # AutoRunning

    def test_sv960_idle(self, state):
        state.transition_process(ProcessState.IDLE)
        assert state.get_sv(960) == 2   # AutoRunStop

    def test_sv960_alarm(self, state):
        state.transition_process(ProcessState.ALARM)
        assert state.get_sv(960) == 6   # Error

    def test_process_callback(self, state):
        changes = []
        state.set_on_process_change(lambda o, n: changes.append(n))
        state.transition_process(ProcessState.EXECUTING)
        assert ProcessState.EXECUTING in changes


# ── PPID and SVIDs ─────────────────────────────────────────────────────────────
class TestPpidAndSvid:
    def test_set_ppid(self, state):
        state.set_ppid('RecipeA')
        assert state.ppid == 'RecipeA'

    def test_ppid_updates_svid_555(self, state):
        state.set_ppid('RecipeA')
        assert state.get_sv(555) == 'RecipeA'

    def test_ppid_updates_svid_970(self, state):
        state.set_ppid('RecipeB')
        assert state.get_sv(970) == 'RecipeB'

    def test_set_sv(self, state):
        state.set_sv(800, 'test')
        assert state.get_sv(800) == 'test'

    def test_get_all_svids_is_copy(self, state):
        all_sv = state.get_all_svids()
        all_sv[999] = 'MUTATED'
        assert state.get_sv(999) is None   # original unchanged


# ── Query helpers ──────────────────────────────────────────────────────────────
class TestQueryHelpers:
    def test_is_online_false_offline(self, state):
        assert state.is_online() is False

    def test_is_online_true_local(self, state):
        state.force_control(ControlState.ONLINE_LOCAL)
        assert state.is_online() is True

    def test_is_online_true_remote(self, state):
        state.force_control(ControlState.ONLINE_REMOTE)
        assert state.is_online() is True

    def test_is_online_remote(self, state):
        state.force_control(ControlState.ONLINE_REMOTE)
        assert state.is_online_remote() is True

    def test_is_online_local(self, state):
        state.force_control(ControlState.ONLINE_LOCAL)
        assert state.is_online_local() is True

    def test_host_offline_is_not_online(self, state):
        state.force_control(ControlState.HOST_OFFLINE)
        assert state.is_online() is False
