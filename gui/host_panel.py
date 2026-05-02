"""
HOST Control left panel — UI building + all HOST-side send actions.

HostPanel is a tk.Frame that owns the left column of the main window.
It receives the router, gem_state and callback references it needs at construction;
it never calls back into MainWindow directly (loose coupling).
"""
import json
import threading
import logging
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path

from core.secs_codec import L, A, B, U1

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.parent


def recipe_ppids_in_dir(recipes_dir: Path) -> list[str]:
    """Return sorted PPID names (one subfolder = one recipe) under recipes_dir."""
    if not recipes_dir.is_dir():
        return []
    return sorted(d.name for d in recipes_dir.iterdir() if d.is_dir())


MSG_NAMES = {
    (1,  1):  'Are You There (S1F1)',
    (1,  2):  'On Line Data (S1F2)',
    (1,  3):  'Selected EQ Status Request (S1F3)',
    (1,  4):  'Selected EQ Status Data (S1F4)',
    (1, 13):  'Establish Communications (S1F13)',
    (1, 14):  'Establish Comms Acknowledge (S1F14)',
    (1, 15):  'Request OFF-LINE (S1F15)',
    (1, 16):  'OFF-LINE Acknowledge (S1F16)',
    (1, 17):  'Request ON-LINE (S1F17)',
    (1, 18):  'ON-LINE Acknowledge (S1F18)',
    (2, 13):  'Equipment Constant Request (S2F13)',
    (2, 14):  'Equipment Constant Data (S2F14)',
    (2, 17):  'Date & Time Request (S2F17)',
    (2, 18):  'Date & Time Data (S2F18)',
    (2, 29):  'Constant Namelist Request (S2F29)',
    (2, 30):  'Constant Namelist (S2F30)',
    (2, 31):  'Date & Time Set (S2F31)',
    (2, 32):  'Date & Time Set Acknowledge (S2F32)',
    (2, 33):  'Define Report (S2F33)',
    (2, 34):  'Define Report Acknowledge (S2F34)',
    (2, 35):  'Link Event Report (S2F35)',
    (2, 36):  'Link Event Report Acknowledge (S2F36)',
    (2, 37):  'Enable/Disable Event (S2F37)',
    (2, 38):  'Enable/Disable Event Acknowledge (S2F38)',
    (2, 41):  'Host Command Send (S2F41)',
    (2, 42):  'Host Command Acknowledge (S2F42)',
    (5,  1):  'Alarm Report Send (S5F1)',
    (5,  2):  'Alarm Report Acknowledge (S5F2)',
    (5,  3):  'Enable/Disable Alarm (S5F3)',
    (5,  4):  'Enable/Disable Alarm Acknowledge (S5F4)',
    (6, 11):  'Event Report Send (S6F11)',
    (6, 12):  'Event Report Acknowledge (S6F12)',
    (7,  3):  'Process Program Send (S7F3)',
    (7,  4):  'Process Program Acknowledge (S7F4)',
    (7, 17):  'Delete Process Program (S7F17)',
    (7, 18):  'Delete Process Program Acknowledge (S7F18)',
    (7, 19):  'Current EPPD Request (S7F19)',
    (7, 20):  'Current EPPD Data (S7F20)',
    (7, 25):  'Formatted Process Program Request (S7F25)',
    (7, 26):  'Formatted Process Program Data (S7F26)',
    (9,  1):  'Unrecognized Device ID (S9F1)',
    (9,  3):  'Unrecognized Stream Type (S9F3)',
    (9,  5):  'Unrecognized Function Type (S9F5)',
    (9,  7):  'Illegal Data (S9F7)',
    (9,  9):  'Transaction Timer Timeout (S9F9)',
    (9, 11):  'Data Too Long (S9F11)',
    (10, 3):  'Terminal Display Single (S10F3)',
    (10, 4):  'Terminal Display Single Ack (S10F4)',
    (10, 5):  'Terminal Display Multi (S10F5)',
    (10, 6):  'Terminal Display Multi Ack (S10F6)',
    (14, 1):  'GetAttr Request (S14F1)',
    (14, 2):  'GetAttr Data (S14F2)',
}


class HostPanel(tk.Frame):
    """Left-column HOST Control panel."""

    def __init__(self, parent, router, gem_state, hsms_server, config: dict,
                 logger_widget, eq_panel_widget, on_config_change=None):
        super().__init__(parent, bg='#161B22')
        self.router         = router
        self.gem_state      = gem_state
        self.hsms_server    = hsms_server
        self.config         = config
        self.log            = logger_widget
        self.eq_panel       = eq_panel_widget
        self._on_cfg_change = on_config_change
        self._rcmd_cfg:     dict = {}
        self._sys_ctr       = 1
        self._param_vars:   dict = {}
        self._port_var      = tk.StringVar(
            value=str(config.get('HSMS', {}).get('port', 5000)))

        self._build_panel()
        self._reload_rcmd_config()
        self._reload_host_send_actions()

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _load_json(self, filename: str) -> dict:
        try:
            with open(BASE_DIR / 'config' / filename, encoding='utf-8') as f:
                return json.load(f)
        except Exception as exc:
            logger.warning('Cannot load %s: %s', filename, exc)
            return {}

    def _next_sys(self) -> int:
        v = self._sys_ctr
        self._sys_ctr = (self._sys_ctr + 1) & 0xFFFFFFFF
        return v

    def _make_hdr(self, stream, function, wbit=True, extra: dict = None) -> dict:
        h = {
            'stream': stream, 'function': function,
            'wbit': wbit, 'sys_bytes': self._next_sys(),
            'raw_header': b'\x00' * 10,
            'device_id': 1, 'direction': 'Host->EQ',
        }
        if extra:
            h['extra'] = extra
        return h

    def _ui(self, fn, *args):
        self.after(0, lambda: fn(*args))

    def _lf(self, text: str) -> tk.LabelFrame:
        return tk.LabelFrame(self, text=text, bg='#161B22',
                             fg='#8B949E', font=('Consolas', 8))

    # ── Panel builder ──────────────────────────────────────────────────────────
    def _build_panel(self):
        tk.Label(self, text='  HOST Control',
                 bg='#0D2137', fg='#58A6FF',
                 font=('Consolas', 10, 'bold'),
                 anchor='w', pady=4).pack(fill='x')
        self._build_model_selector()
        self._build_connection()
        self._build_servo_control()
        self._build_host_send_menu()
        self._build_rcmd_panel()
        self._build_alarm_trigger()

    def _build_model_selector(self):
        f = self._lf('Machine Model')
        f.pack(fill='x', padx=5, pady=3)
        self._model_var = tk.StringVar(value=self.config.get('MODEL', 'TFC-6600'))
        row = tk.Frame(f, bg='#161B22')
        row.pack(fill='x', padx=4, pady=4)
        tk.Label(row, text='Model:', bg='#161B22', fg='#8B949E',
                 font=('Consolas', 9), width=7, anchor='w').pack(side='left')
        cb = ttk.Combobox(row, textvariable=self._model_var,
                          values=['TFC-6600', 'TFC-6500'], state='readonly',
                          font=('Consolas', 9), width=10)
        cb.pack(side='left', padx=4)
        cb.bind('<<ComboboxSelected>>', self._on_model_changed)

    def _build_connection(self):
        f = self._lf('Connection (EQ Passive)')
        f.pack(fill='x', padx=5, pady=3)
        row = tk.Frame(f, bg='#161B22')
        row.pack(fill='x', padx=4, pady=2)
        tk.Label(row, text='Port:', bg='#161B22', fg='#8B949E',
                 font=('Consolas', 9), width=6, anchor='w').pack(side='left')
        tk.Entry(row, textvariable=self._port_var, bg='#21262D', fg='white',
                 font=('Consolas', 9), relief='flat', width=8,
                 insertbackground='white').pack(side='left')
        bf = tk.Frame(f, bg='#161B22')
        bf.pack(fill='x', pady=3)
        tk.Button(bf, text='Start Listening', bg='#1B5E20', fg='white',
                  font=('Consolas', 9, 'bold'), relief='flat', cursor='hand2',
                  command=self._on_start).pack(side='left', expand=True, fill='x', padx=2)
        tk.Button(bf, text='Stop', bg='#B71C1C', fg='white',
                  font=('Consolas', 9, 'bold'), relief='flat', cursor='hand2',
                  command=self._on_stop).pack(side='left', expand=True, fill='x', padx=2)

    def _build_servo_control(self):
        f = self._lf('EQ Operator  (Servo Power)')
        f.pack(fill='x', padx=5, pady=3)
        bf = tk.Frame(f, bg='#161B22')
        bf.pack(fill='x', padx=4, pady=4)
        tk.Button(bf, text='Servo ON', bg='#1B5E20', fg='white',
                  font=('Consolas', 9, 'bold'), relief='flat', cursor='hand2',
                  command=lambda: threading.Thread(
                      target=self._servo_action, args=(True,), daemon=True).start()
                  ).pack(side='left', expand=True, fill='x', padx=2)
        tk.Button(bf, text='Servo OFF', bg='#B71C1C', fg='white',
                  font=('Consolas', 9, 'bold'), relief='flat', cursor='hand2',
                  command=lambda: threading.Thread(
                      target=self._servo_action, args=(False,), daemon=True).start()
                  ).pack(side='left', expand=True, fill='x', padx=2)

    def _build_host_send_menu(self):
        f = self._lf('HOST Send')
        f.pack(fill='x', padx=5, pady=3)
        tk.Label(
            f, text='Choose a message, then Send.',
            bg='#161B22', fg='#484F58', font=('Consolas', 8),
            wraplength=280, justify='left',
        ).pack(anchor='w', padx=4, pady=(2, 0))
        self._host_send_var = tk.StringVar()
        self._host_send_handlers: dict[str, Callable[[], None]] = {}
        self._host_send_cb = ttk.Combobox(
            f, textvariable=self._host_send_var,
            values=[], state='readonly', font=('Consolas', 9), width=34,
        )
        self._host_send_cb.pack(fill='x', padx=4, pady=4)
        tk.Button(
            f, text='Send', bg='#1565C0', fg='white',
            font=('Consolas', 9, 'bold'), relief='flat', cursor='hand2',
            command=self._on_host_send_execute,
        ).pack(fill='x', padx=4, pady=(0, 4))

    def _reload_host_send_actions(self):
        """Populate single HOST Send combobox (S1/S2/S7/S9/S10/S14 + S6F12 only)."""
        handlers: dict[str, Callable[[], None]] = {}
        labels: list[str] = []

        def add(label: str, fn: Callable[[], None]) -> None:
            labels.append(label)
            handlers[label] = fn

        add('S1F13  Establish Comms', self._send_s1f13)
        add('S1F17  Request Online', self._send_s1f17)
        add('S1F15  Request Offline', self._send_s1f15)
        add('S1F1   Are You There?', self._send_s1f1)
        add('S1F3   Status Request', self._send_s1f3)
        add('S2F13  Constant Request', self._send_s2f13)
        add('S2F17  Date/Time Request', self._send_s2f17)
        add('S2F31  Set Time', self._send_s2f31)
        add('S7F3   Upload Recipe…', self._send_s7f3_dialog)
        add('S7F17  Delete Recipe…', self._send_s7f17_dialog)
        add('S7F19  List Recipes', self._send_s7f19)
        add('S7F25  Recipe Body Request', self._send_s7f25)
        add('S10F3  Terminal Display', self._send_s10f3)
        add('S14F1  GetAttr (MapData)', self._send_s14f1)
        add('S6F12  Event Report Ack (Host)', self._send_s6f12)

        for s9_label, fn_num in [
            ('S9F1   Bad device ID', 1),
            ('S9F3   Bad stream', 3),
            ('S9F5   Bad function', 5),
            ('S9F7   Illegal data', 7),
            ('S9F9   Transaction timeout', 9),
            ('S9F11  Data too long', 11),
        ]:

            def _s9_send(n: int = fn_num) -> None:
                threading.Thread(
                    target=self._send_s9, args=(n,), daemon=True,
                ).start()

            add(s9_label, _s9_send)

        self._host_send_handlers = handlers
        self._host_send_cb['values'] = labels
        if labels:
            self._host_send_cb.set(labels[0])
        else:
            self._host_send_var.set('')

    def _on_host_send_execute(self):
        label = self._host_send_var.get().strip()
        fn = self._host_send_handlers.get(label)
        if fn is None:
            return
        fn()

    def _build_rcmd_panel(self):
        f = self._lf('Remote Command  S2F41')
        f.pack(fill='x', padx=5, pady=3)
        tk.Label(f, text='RCMD:', bg='#161B22', fg='#8B949E',
                 font=('Consolas', 9)).pack(anchor='w', padx=4, pady=(2, 0))
        self._rcmd_var = tk.StringVar()
        self._rcmd_cb = ttk.Combobox(f, textvariable=self._rcmd_var,
                                     values=[], state='readonly',
                                     font=('Consolas', 9))
        self._rcmd_cb.pack(fill='x', padx=4, pady=2)
        self._rcmd_cb.bind('<<ComboboxSelected>>', self._on_rcmd_changed)
        self._rcmd_desc = tk.Label(f, text='', bg='#161B22', fg='#484F58',
                                   font=('Consolas', 8), wraplength=250, justify='left')
        self._rcmd_desc.pack(anchor='w', padx=6)
        self._params_frame = tk.Frame(f, bg='#161B22')
        self._params_frame.pack(fill='x', padx=4)
        tk.Button(f, text='Send S2F41', bg='#1565C0', fg='white',
                  font=('Consolas', 9, 'bold'), relief='flat', cursor='hand2',
                  command=self._send_s2f41).pack(fill='x', padx=4, pady=4)

    def _build_alarm_trigger(self):
        f = self._lf('Trigger EQ Alarm  S5F1')
        f.pack(fill='x', padx=5, pady=3)
        self._alid_var = tk.StringVar()
        self._alid_cb = ttk.Combobox(f, textvariable=self._alid_var,
                                     values=[], state='readonly',
                                     font=('Consolas', 9))
        self._alid_cb.pack(fill='x', padx=4, pady=2)
        bf = tk.Frame(f, bg='#161B22')
        bf.pack(fill='x', padx=4, pady=(0, 4))
        tk.Button(bf, text='Set Alarm',   bg='#B71C1C', fg='white',
                  font=('Consolas', 9), relief='flat', cursor='hand2',
                  command=lambda: self._fire_alarm(True)
                  ).pack(side='left', expand=True, fill='x', padx=1)
        tk.Button(bf, text='Clear Alarm', bg='#1B5E20', fg='white',
                  font=('Consolas', 9), relief='flat', cursor='hand2',
                  command=lambda: self._fire_alarm(False)
                  ).pack(side='left', expand=True, fill='x', padx=1)
        self._reload_alid_combo()

    # ── Model change ───────────────────────────────────────────────────────────
    def _on_model_changed(self, _):
        model_raw = self._model_var.get()
        key = model_raw.replace('TFC-', '') + 'WB'
        new_eq  = self._load_json(f'{key}_eq_constants.json')
        new_cmd = self._load_json(f'{key}_s2f41_cmds.json')
        if not new_eq:
            self.log.log_error(f'Config not found: {key}_eq_constants.json')
            return
        self.config.update(new_eq)
        self.config['RCMD'] = new_cmd
        self.router.config  = self.config
        if self._on_cfg_change:
            self._on_cfg_change(self.config)
        self._reload_rcmd_config()
        self._reload_host_send_actions()
        self._reload_alid_combo()
        self.log.log_info(f'Model changed → {new_eq.get("MODEL", model_raw)}')

    def _reload_rcmd_config(self):
        self._rcmd_cfg = self.config.get('RCMD', {})
        names = list(self._rcmd_cfg.keys())
        self._rcmd_cb['values'] = names
        if names:
            self._rcmd_cb.set(names[0])
            self._on_rcmd_changed(None)

    def _reload_alid_combo(self):
        items = [f'{k}: {v["name"]}' for k, v in
                 sorted(self.config.get('ALID', {}).items(), key=lambda x: int(x[0]))]
        self._alid_cb['values'] = items
        if items:
            self._alid_cb.set(items[0])

    # ── RCMD param builder ─────────────────────────────────────────────────────
    def _on_rcmd_changed(self, _):
        rcmd = self._rcmd_var.get()
        cfg  = self._rcmd_cfg.get(rcmd, {})
        self._rcmd_desc.config(text=cfg.get('desc', ''))
        for w in self._params_frame.winfo_children():
            w.destroy()
        self._param_vars.clear()
        for pname, spec in cfg.get('params', {}).items():
            row = tk.Frame(self._params_frame, bg='#161B22')
            row.pack(fill='x', pady=1)
            tk.Label(row, text=f'{pname}:', bg='#161B22', fg='#CE93D8',
                     font=('Consolas', 8), width=22, anchor='w').pack(side='left')
            var = tk.StringVar()
            self._param_vars[pname] = var
            if 'values' in spec:
                cb2 = ttk.Combobox(row, textvariable=var, values=spec['values'],
                                   state='readonly', font=('Consolas', 8), width=6)
                cb2.set(spec['values'][0])
                cb2.pack(side='left')
            else:
                tk.Entry(row, textvariable=var, bg='#21262D', fg='white',
                         font=('Consolas', 8), relief='flat', width=14,
                         insertbackground='white').pack(side='left')

    # ── Dispatch helper ────────────────────────────────────────────────────────
    def _dispatch(self, stream, function, body, extra: dict = None):
        hdr = self._make_hdr(stream, function, extra=extra)
        threading.Thread(target=self.router.process_message,
                         args=(hdr, body), daemon=True,
                         name=f'Dispatch-S{stream}F{function}').start()

    # ── S1 quick actions ───────────────────────────────────────────────────────
    def _send_s1f1(self):  self._dispatch(1,  1, b'')
    def _send_s1f13(self): self._dispatch(1, 13, b'')
    def _send_s1f15(self): self._dispatch(1, 15, b'')
    def _send_s1f17(self): self._dispatch(1, 17, b'')
    def _send_s1f3(self):
        body = L().encode()   # empty list = report all SVIDs
        self._dispatch(1, 3, body)

    # ── S2 quick actions ───────────────────────────────────────────────────────
    def _send_s2f13(self):
        body = L().encode()   # empty = all constants
        self._dispatch(2, 13, body)

    def _send_s2f31(self):
        import datetime
        ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S00')
        body = A(ts).encode()
        self._dispatch(2, 31, body)

    def _send_s2f17(self):
        self._dispatch(2, 17, b'')

    def _send_s2f41(self):
        rcmd = self._rcmd_var.get()
        if not rcmd:
            return
        params = [(k, v.get()) for k, v in self._param_vars.items() if v.get()]
        body   = L(A(rcmd), L(*[L(A(n), A(v)) for n, v in params])).encode()
        hdr = self._make_hdr(
            2, 41,
            extra={'rcmd': rcmd, 'params': dict(params)},
        )
        threading.Thread(target=self.router.process_message,
                         args=(hdr, body), daemon=True, name='Dispatch-S2F41').start()

    # ── S7 quick actions ───────────────────────────────────────────────────────
    def _send_s7f3_dialog(self):
        """Open a dialog to upload a recipe via S7F3."""
        win = tk.Toplevel(self)
        win.title('S7F3 – Upload Recipe')
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text='PPID:', anchor='w').grid(row=0, column=0, sticky='w', padx=8, pady=(8, 2))
        ppid_var = tk.StringVar()
        tk.Entry(win, textvariable=ppid_var, width=32).grid(row=0, column=1, padx=8, pady=(8, 2))

        tk.Label(win, text='Recipe Body (JSON):', anchor='nw').grid(row=1, column=0, sticky='nw', padx=8, pady=2)
        body_text = scrolledtext.ScrolledText(win, width=40, height=10)
        body_text.grid(row=1, column=1, padx=8, pady=2)
        body_text.insert('1.0', '{\n  "ccode_list": []\n}')

        status_var = tk.StringVar()
        tk.Label(win, textvariable=status_var, fg='red').grid(row=2, column=0, columnspan=2, padx=8)

        def _do_send():
            ppid = ppid_var.get().strip()
            if not ppid:
                status_var.set('PPID must not be empty.')
                return
            raw = body_text.get('1.0', 'end').strip()
            try:
                json.loads(raw)
            except json.JSONDecodeError as exc:
                status_var.set(f'Invalid JSON: {exc}')
                return
            ppbody_bytes = raw.encode('utf-8')
            body = L(A(ppid), B(*ppbody_bytes)).encode()
            self._dispatch(7, 3, body)
            win.destroy()

        btn_frame = tk.Frame(win)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=8)
        tk.Button(btn_frame, text='Upload', command=_do_send, bg='#4E342E', fg='white', width=10).pack(side='left', padx=4)
        tk.Button(btn_frame, text='Cancel', command=win.destroy, width=10).pack(side='left', padx=4)

    def _recipe_ppids_on_disk(self) -> list[str]:
        return recipe_ppids_in_dir(BASE_DIR / 'recipes')

    def _send_s7f17_dialog(self):
        """Open a dialog to delete one recipe via S7F17 (dropdown, one PPID per send)."""
        win = tk.Toplevel(self)
        win.title('S7F17 – Delete Recipe')
        win.resizable(False, False)
        win.grab_set()

        tk.Label(
            win,
            text='Select PPID to delete (one recipe per send).',
            justify='left',
        ).pack(padx=12, pady=(10, 4), anchor='w')

        combo = ttk.Combobox(win, width=38, state='readonly')
        combo.pack(padx=12, pady=4)

        status_var = tk.StringVar()
        tk.Label(win, textvariable=status_var, fg='#c62828').pack(padx=12, pady=(0, 4), anchor='w')

        def _fill_combo():
            names = self._recipe_ppids_on_disk()
            combo['values'] = names
            if names:
                combo.set(names[0])
                combo.configure(state='readonly')
                status_var.set('')
            else:
                combo.set('')
                combo.configure(state='disabled')
                status_var.set('No recipes on disk.')

        def _refresh():
            _fill_combo()

        _fill_combo()

        tk.Button(win, text='Refresh list', command=_refresh).pack(padx=12, pady=(0, 4), anchor='w')

        def _do_send():
            ppid = combo.get().strip()
            if not ppid:
                status_var.set('Select a recipe from the list.')
                return
            if not messagebox.askyesno('Confirm', f'Delete recipe "{ppid}"?', parent=win):
                return
            body = L(A(ppid)).encode()
            self._dispatch(7, 17, body)
            logger.info('S7F17 sent for PPID: %s', ppid)
            win.destroy()

        btn_frame = tk.Frame(win)
        btn_frame.pack(pady=8)
        tk.Button(btn_frame, text='Delete', command=_do_send, bg='#B71C1C', fg='white', width=10).pack(side='left', padx=4)
        tk.Button(btn_frame, text='Cancel', command=win.destroy, width=10).pack(side='left', padx=4)

    def _send_s7f19(self): self._dispatch(7, 19, b'')

    def _send_s7f25(self):
        ppid = str(self.gem_state.get_sv(970) or 'DEMO-RECIPE')
        body = L(A(ppid)).encode()
        self._dispatch(7, 25, body)

    # ── S10 quick actions ──────────────────────────────────────────────────────
    def _send_s10f3(self):
        body = L(B(0), A('Hello from Simulator HOST')).encode()
        self._dispatch(10, 3, body)

    # ── S14 quick actions ──────────────────────────────────────────────────────
    def _send_s14f1(self):
        """Send GetAttr Request for MapData of current wafer."""
        wafer_id = str(self.gem_state.get_sv(568) or 'Bottom-0001')
        recipe   = str(self.gem_state.get_sv(536) or 'Recipe-A')
        body = L(
            A(''),             # OBJSPEC (empty = local)
            A('Substrate'),    # OBJTYPE
            L(A(wafer_id), A(recipe)),   # OBJIDs
            L(L(A('SubstrateType'), A('Wafer'), U1(0))),  # qualifier
            L(A('MapData')),   # requested ATTRIDs
        ).encode()
        self._dispatch(14, 1, body)

    # ── S9 manual trigger (EQ sends) ──────────────────────────────────────────
    def _send_s9(self, fn_num: int):
        from handlers.s9_handler import _send_s9
        _send_s9(self.router, fn_num, b'\x00' * 10)

    # ── S6 / S5 triggers ──────────────────────────────────────────────────────
    def _send_s6f12(self):
        """Host acknowledges last S6F11 (Event Report Acknowledge, ACKC6=0)."""
        body = B(0).encode()
        self._dispatch(6, 12, body)

    def _fire_alarm(self, alarm_set: bool):
        val = self._alid_var.get()
        if not val:
            return
        try:
            alid = int(val.split(':')[0].strip())
        except ValueError:
            return
        threading.Thread(target=self._do_fire_alarm,
                         args=(alid, alarm_set), daemon=True).start()

    def _do_fire_alarm(self, alid: int, alarm_set: bool):
        from handlers.s5_handler import send_s5f1
        send_s5f1(self.router, alid, alarm_set)

    # ── Servo ──────────────────────────────────────────────────────────────────
    def _servo_action(self, is_on: bool):
        from handlers.s6_handler import send_s6f11
        if is_on:
            self.gem_state.set_sv(960, 2)
            send_s6f11(self.router, 180)
        else:
            self.gem_state.set_sv(960, 9)
            send_s6f11(self.router, 181)
        self._ui(self.eq_panel.update_servo, is_on)

    # ── HSMS server control ────────────────────────────────────────────────────
    def _on_start(self):
        self.hsms_server.start()
        self.log.log_info(f'EQ passive server listening on port {self._port_var.get()}')

    def _on_stop(self):
        self.hsms_server.stop()
        self.log.log_info('Server stopped')
