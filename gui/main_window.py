"""
Main application window — 3-panel SECS/GEM simulator.

Left   : HOST Control  (machine model, quick actions, RCMD, event/alarm triggers)
Center : SECS Sniffer  (colour-coded message log + decoded SECS body)
Right  : EQ Status     (control/process state, PPID, stage presence, event log)

HOST panel is delegated to gui.host_panel.HostPanel for size management.
"""
import logging
import tkinter as tk
from tkinter import ttk

from gui.event_logger import EventLogger
from gui.eq_panel     import EqPanel
from gui.host_panel   import HostPanel, MSG_NAMES
from core.gem_state   import ControlState, ProcessState

logger = logging.getLogger(__name__)

# Virtual framebuffer / HF noVNC target (width x height x depth handled in Xvfb / Dockerfile).
UI_WIDTH = 1024
UI_HEIGHT = 768
# Side rail widths scaled from prior 310+270 layout @ 1520px content width.
_LEFT_W = max(208, round(310 * UI_WIDTH / 1520))
_RIGHT_W = max(180, round(270 * UI_WIDTH / 1520))


class MainWindow:
    """Main 3-panel simulator window."""

    def __init__(self, root: tk.Tk, router, gem_state, hsms_server, config: dict):
        self.root        = root
        self.router      = router
        self.gem_state   = gem_state
        self.hsms_server = hsms_server
        self.config      = config

        root.title(f"SECS/GEM Simulator  —  {config.get('MODEL', 'EQ')}")
        root.geometry(f'{UI_WIDTH}x{UI_HEIGHT}')
        root.configure(bg='#0D1117')
        root.protocol('WM_DELETE_WINDOW', self._on_close)

        self._setup_styles()
        self._build_ui()
        self._bind_events()

    # ── Style ──────────────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use('clam')
        for name, bg in [
            ('Send.TButton',       '#1565C0'),
            ('Connect.TButton',    '#1B5E20'),
            ('Disconnect.TButton', '#B71C1C'),
        ]:
            s.configure(name, background=bg, foreground='white',
                        font=('Consolas', 9, 'bold'), relief='flat', borderwidth=0)
            s.map(name, background=[('active', bg)])

    # ── Layout ─────────────────────────────────────────────────────────────────
    def _build_ui(self):
        bar = tk.Frame(self.root, bg='#010409', height=24)
        bar.pack(fill='x')
        bar.pack_propagate(False)
        self._status_var = tk.StringVar(value='Idle')
        tk.Label(bar, textvariable=self._status_var,
                 bg='#010409', fg='#8B949E',
                 font=('Consolas', 9)).pack(side='left', padx=10, pady=3)
        self._model_lbl = tk.Label(bar, text='', bg='#010409', fg='#444C56',
                                   font=('Consolas', 9))
        self._model_lbl.pack(side='right', padx=10)

        main = tk.Frame(self.root, bg='#0D1117')
        main.pack(fill='both', expand=True, padx=3, pady=3)

        # Right panel first so center can expand
        right = tk.Frame(main, bg='#161B22', width=_RIGHT_W)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)
        self.eq_panel = EqPanel(right)
        self.eq_panel.pack(fill='both', expand=True)

        # Center sniffer
        center = tk.Frame(main, bg='#0D1117')
        center.pack(side='right', fill='both', expand=True, padx=(0, 3))
        self.logger = EventLogger(center)
        self.logger.pack(fill='both', expand=True)

        # Left HOST panel
        left_scroll = tk.Frame(main, bg='#161B22', width=_LEFT_W)
        left_scroll.pack(side='left', fill='y', padx=(0, 3))
        left_scroll.pack_propagate(False)
        canvas = tk.Canvas(left_scroll, bg='#161B22', highlightthickness=0)
        sb = ttk.Scrollbar(left_scroll, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(canvas, bg='#161B22')
        win_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox('all'))
        def _on_canvas_configure(e):
            canvas.itemconfig(win_id, width=e.width)
        inner.bind('<Configure>', _on_inner_configure)
        canvas.bind('<Configure>', _on_canvas_configure)

        def _wheel(e):
            if e.delta:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
            else:
                canvas.yview_scroll(-1 if e.num == 4 else 1, 'units')

        for w in (canvas, inner):
            w.bind('<MouseWheel>', _wheel)
            w.bind('<Button-4>', _wheel)
            w.bind('<Button-5>', _wheel)

        self.host_panel = HostPanel(
            inner, self.router, self.gem_state, self.hsms_server,
            self.config, self.logger, self.eq_panel,
            on_config_change=self._on_config_change,
        )
        self.host_panel.pack(fill='x')

    # ── Config change callback (from HostPanel model switch) ───────────────────
    def _on_config_change(self, new_config: dict):
        self.config = new_config
        model = new_config.get('MODEL', '')
        softrev = new_config.get('SOFTREV', '')
        port = new_config.get('HSMS', {}).get('port', 5000)
        self.root.title(f"SECS/GEM Simulator  —  {model}")
        self._model_lbl.config(text=f'{model} v{softrev} :{port}')

    # ── Event bindings ─────────────────────────────────────────────────────────
    def _bind_events(self):
        r = self.router
        r.subscribe('rx_message',            self._on_rx)
        r.subscribe('tx_message',            self._on_tx)
        r.subscribe('eq_event',              self._on_eq_event)
        r.subscribe('alarm_event',           self._on_alarm_event)
        r.subscribe('ppid_changed',          self._on_ppid_changed)
        r.subscribe('process_state_changed', self._on_proc_changed)
        r.subscribe('connected',             self._on_connected)
        r.subscribe('disconnected',          self._on_disconnected)
        r.subscribe('listening',             self._on_listening)
        r.subscribe('bind_error',            self._on_bind_error)
        r.subscribe('terminal_display',      self._on_terminal_display)
        self.gem_state.set_on_control_change(self._on_ctrl_change)
        self.gem_state.set_on_process_change(self._on_proc_state)
        self.root.after(0, lambda: self.eq_panel.update_control_state(self.gem_state.control))

    # ── Event handlers ─────────────────────────────────────────────────────────
    def _on_rx(self, d):
        s, f = d['stream'], d['function']
        if d.get('direction', 'Host->EQ') == 'Host->EQ':
            desc = MSG_NAMES.get((s, f), d.get('description', f'S{s}F{f}'))
            self.logger.log_message(
                'Host->EQ', s, f, desc,
                extra=d.get('extra'),
                body=d.get('body') or None,
            )

    def _on_tx(self, d):
        s, f = d['stream'], d['function']
        desc = MSG_NAMES.get((s, f), f'S{s}F{f}')
        extra = {}
        if s == 2 and f == 42 and d.get('body'):
            try:
                from core.secs_codec import decode_item
                item, _ = decode_item(d['body'])
                if item.fmt == 0 and item.value:
                    hcack = item.value[0].value
                    if isinstance(hcack, (bytes, bytearray)):
                        hcack = hcack[0]
                    extra['hcack'] = hcack
            except Exception:
                pass
        if s == 5 and f == 1 and d.get('alid') is not None:
            extra['alid'] = d['alid']
            extra['action'] = d.get('action', '')
            extra['text'] = d.get('text', '')
        self.logger.log_message('EQ->Host', s, f, desc, extra or None,
                                body=d.get('body') or None)

        # Auto-send S6F12 (Host ACK) after EQ sends S6F11 Event Report
        if s == 6 and f == 11:
            self.root.after(120, self._auto_s6f12)

    def _auto_s6f12(self):
        """Simulate Host automatically acknowledging an S6F11 Event Report."""
        import threading
        from core.secs_codec import B
        body = B(0).encode()       # ACKC6 = 0 (OK)
        hdr = {
            'stream': 6, 'function': 12,
            'wbit': False, 'sys_bytes': 0,
            'raw_header': b'\x00' * 10,
            'device_id': 1, 'direction': 'Host->EQ',
            'description': 'Event Report Acknowledge (S6F12)',
        }
        threading.Thread(target=self.router.process_message,
                         args=(hdr, body), daemon=True,
                         name='Auto-S6F12').start()

    def _on_eq_event(self, d):
        ceid = d.get('ceid')
        if ceid is not None:
            self.eq_panel.log_event(ceid, d.get('ceid_name', ''))
            sv = self.gem_state
            self.root.after(0, lambda: self.eq_panel.update_stage(
                sv.get_sv(931) or 0,
                sv.get_sv(932) or 0,
                sv.get_sv(935) or 0,
            ))

    def _on_alarm_event(self, d):
        alid   = d.get('alid', 0)
        action = d.get('action', '')
        self.eq_panel.log_event(alid, f'[ALARM {action}] {d.get("name","")}')

    def _on_ppid_changed(self, ppid):
        self.root.after(0, lambda: self.eq_panel.update_ppid(ppid))

    def _on_proc_changed(self, state):
        self.root.after(0, lambda: self.eq_panel.update_process_state(state))

    def _on_ctrl_change(self, old, new):
        self.root.after(0, lambda: self.eq_panel.update_control_state(new))
        self.logger.log_info(f'Control State:  {old.name} → {new.name}')

    def _on_proc_state(self, old, new):
        self.root.after(0, lambda: self.eq_panel.update_process_state(new))

    def _on_connected(self, _):
        self.root.after(0, lambda: self._status_var.set('Connected — HSMS Selected'))
        self.logger.log_info('External HOST connected — session selected')

    def _on_disconnected(self, _):
        self.root.after(0, lambda: self._status_var.set('Listening — peer disconnected'))
        self.logger.log_info('Peer disconnected')

    def _on_listening(self, d):
        if d:
            self.root.after(0, lambda: self._status_var.set(
                f'Listening on :{d.get("port")}'))

    def _on_bind_error(self, d):
        self.logger.log_error(f'Cannot bind port: {d.get("error")}')
        self.root.after(0, lambda: self._status_var.set('Bind error — see log'))

    def _on_terminal_display(self, d):
        kind = 'Multi' if d.get('multi') else 'Single'
        msg  = f'Terminal Display ({kind}) TID={d.get("tid")}  TEXT: {d.get("text","")}'
        self.logger.log_info(msg)

    def _on_close(self):
        self.hsms_server.stop()
        self.root.destroy()
