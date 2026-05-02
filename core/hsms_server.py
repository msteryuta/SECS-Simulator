"""
HSMS (High-Speed Message Services) passive server — SEMI E37.

Handles:
  - TCP accept loop (passive/server mode)
  - 14-byte HSMS framing  (4-byte length + 10-byte header)
  - Control messages: Select / Deselect / Linktest / Separate
  - Forwards data messages to the provided on_message callback
  - Fires on_event('connected'|'disconnected'|'listening'|'peer_connected')
"""
import socket
import struct
import threading
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# S-Type codes for HSMS control messages
STYPE_DATA         = 0
STYPE_SELECT_REQ   = 1
STYPE_SELECT_RSP   = 2
STYPE_DESELECT_REQ = 3
STYPE_DESELECT_RSP = 4
STYPE_LINKTEST_REQ = 5
STYPE_LINKTEST_RSP = 6
STYPE_REJECT       = 7
STYPE_SEPARATE     = 9


def _build_header(device_id: int, stream: int, function: int,
                  wbit: bool, stype: int, sys_bytes: int) -> bytes:
    """Build 10-byte HSMS message header."""
    return struct.pack('>H', device_id) + bytes([
        (stream & 0x7F) | (0x80 if wbit else 0),
        function, 0, stype,
    ]) + struct.pack('>I', sys_bytes)


def build_data_frame(device_id: int, stream: int, function: int,
                     wbit: bool, sys_bytes: int, body: bytes = b'') -> bytes:
    header = _build_header(device_id, stream, function, wbit, STYPE_DATA, sys_bytes)
    return struct.pack('>I', 10 + len(body)) + header + body


def _build_control_frame(stype: int, sys_bytes: int = 0) -> bytes:
    header = _build_header(0xFFFF, 0, 0, False, stype, sys_bytes)
    return struct.pack('>I', 10) + header


class HsmsSession:
    """Manages one accepted TCP connection."""

    def __init__(self, sock: socket.socket, device_id: int,
                 on_message: Callable, on_event: Callable):
        self._sock = sock
        self._device_id = device_id
        self._on_message = on_message
        self._on_event = on_event
        self._selected = False
        self._running = False
        self._counter = 1
        self._lock = threading.Lock()

    @property
    def selected(self) -> bool:
        return self._selected

    def _next_sys(self) -> int:
        with self._lock:
            v = self._counter
            self._counter = (self._counter + 1) & 0xFFFFFFFF
            return v

    def send_message(self, stream: int, function: int, wbit: bool,
                     body: bytes = b'', sys_bytes: Optional[int] = None) -> Optional[int]:
        if sys_bytes is None:
            sys_bytes = self._next_sys()
        frame = build_data_frame(self._device_id, stream, function, wbit, sys_bytes, body)
        try:
            self._sock.sendall(frame)
            return sys_bytes
        except OSError as exc:
            logger.error('Send failed: %s', exc)
            return None

    def _recv_exactly(self, n: int) -> Optional[bytes]:
        buf = b''
        while len(buf) < n:
            try:
                chunk = self._sock.recv(n - len(buf))
            except OSError:
                return None
            if not chunk:
                return None
            buf += chunk
        return buf

    def _recv_frame(self) -> Optional[tuple]:
        raw_len = self._recv_exactly(4)
        if raw_len is None:
            return None
        length = struct.unpack('>I', raw_len)[0]
        if length < 10:
            return None
        payload = self._recv_exactly(length)
        if payload is None:
            return None
        hdr_raw = payload[:10]
        body    = payload[10:]
        device_id  = struct.unpack('>H', hdr_raw[0:2])[0]
        stream_b   = hdr_raw[2]
        wbit       = bool(stream_b & 0x80)
        stream     = stream_b & 0x7F
        function   = hdr_raw[3]
        stype      = hdr_raw[5]
        sys_bytes  = struct.unpack('>I', hdr_raw[6:10])[0]
        return {
            'device_id': device_id, 'stream': stream, 'function': function,
            'wbit': wbit, 'stype': stype, 'sys_bytes': sys_bytes,
            'raw_header': hdr_raw,
        }, body

    def _handle_control(self, hdr: dict):
        stype = hdr['stype']
        sys_bytes = hdr['sys_bytes']
        if stype == STYPE_SELECT_REQ:
            self._selected = True
            self._sock.sendall(_build_control_frame(STYPE_SELECT_RSP, sys_bytes))
            self._on_event('connected', None)
        elif stype == STYPE_SELECT_RSP:
            self._selected = True
            self._on_event('connected', None)
        elif stype == STYPE_DESELECT_REQ:
            self._selected = False
            self._sock.sendall(_build_control_frame(STYPE_DESELECT_RSP, sys_bytes))
            self._on_event('disconnected', None)
        elif stype == STYPE_SEPARATE:
            self._selected = False
            self._on_event('disconnected', None)
        elif stype == STYPE_LINKTEST_REQ:
            self._sock.sendall(_build_control_frame(STYPE_LINKTEST_RSP, sys_bytes))

    def run(self):
        self._running = True
        while self._running:
            result = self._recv_frame()
            if result is None:
                break
            hdr, body = result
            if hdr['stype'] != STYPE_DATA:
                self._handle_control(hdr)
            elif self._selected:
                self._on_message(hdr, body)
        self._running = False
        self._selected = False
        self._on_event('disconnected', None)

    def close(self):
        self._running = False
        try:
            self._sock.close()
        except OSError:
            pass


class HsmsServer:
    """Passive HSMS server. Listens for one connection at a time."""

    def __init__(self, host: str, port: int, device_id: int,
                 on_message: Callable, on_event: Callable):
        self._host = host
        self._port = port
        self._device_id = device_id
        self._on_message = on_message
        self._on_event = on_event
        self._srv: Optional[socket.socket] = None
        self._session: Optional[HsmsSession] = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True, name='HSMS-Accept').start()

    def stop(self):
        self._running = False
        if self._session:
            self._session.close()
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass

    def _accept_loop(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._srv.bind((self._host, self._port))
        except OSError as exc:
            logger.error('Bind failed on port %d: %s', self._port, exc)
            self._on_event('bind_error', {'error': str(exc)})
            return
        self._srv.listen(1)
        self._srv.settimeout(1.0)
        self._on_event('listening', {'host': self._host, 'port': self._port})
        while self._running:
            try:
                conn, addr = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            logger.info('Peer connected: %s', addr)
            self._on_event('peer_connected', {'addr': addr})
            self._session = HsmsSession(conn, self._device_id, self._on_message, self._on_event)
            self._session.run()
            self._on_event('peer_disconnected', None)
            self._session = None

    @property
    def session(self) -> Optional[HsmsSession]:
        return self._session

    def send_message(self, stream: int, function: int, wbit: bool,
                     body: bytes = b'', sys_bytes: Optional[int] = None) -> Optional[int]:
        s = self._session
        if s and s.selected:
            return s.send_message(stream, function, wbit, body, sys_bytes)
        return None
