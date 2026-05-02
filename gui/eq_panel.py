"""
Equipment Status Panel — right column of the simulator GUI.

Displays:
  • Control State with colour indicator
  • Process State with colour indicator
  • Current PPID (recipe)
  • Stage presence (BG-L, BG-R, Wafer Stage)
  • Recent collection events (CEID log)

All update methods are thread-safe via queue + after().
"""
import queue
import datetime
import tkinter as tk
from tkinter import ttk

from core.gem_state import ControlState, ProcessState

BG = '#1A1E24'

_CTRL_STYLE = {
    ControlState.EQUIPMENT_OFFLINE: ('#EF9A9A', 'EQ OFFLINE'),
    ControlState.ATTEMPT_ONLINE:    ('#FFD54F', 'ATTEMPT ONLINE'),
    ControlState.HOST_OFFLINE:      ('#FFB74D', 'HOST OFFLINE'),
    ControlState.ONLINE_LOCAL:      ('#A5D6A7', 'ONLINE  LOCAL'),
    ControlState.ONLINE_REMOTE:     ('#4CAF50', 'ONLINE REMOTE'),
}

_PROC_STYLE = {
    ProcessState.IDLE:      ('#78909C', 'IDLE'),
    ProcessState.SETUP:     ('#FFD54F', 'SETUP'),
    ProcessState.EXECUTING: ('#4CAF50', 'EXECUTING'),
    ProcessState.PAUSE:     ('#FFB74D', 'PAUSE'),
    ProcessState.ALARM:     ('#EF5350', 'ALARM'),
    ProcessState.STOPPING:  ('#FF8A65', 'STOPPING'),
}


class EqPanel(tk.Frame):
    """Equipment status display panel."""

    def __init__(self, parent, **kwargs):
        bg = kwargs.pop('bg', BG)   # avoid duplicate-keyword error
        super().__init__(parent, bg=bg, **kwargs)
        self._q: queue.Queue = queue.Queue()
        self._build_ui()
        self._drain()

    def _lf(self, parent, text: str) -> tk.LabelFrame:
        return tk.LabelFrame(parent, text=text, bg=BG,
                             fg='#78909C', font=('Consolas', 8))

    def _build_ui(self):
        # ── Title ──────────────────────────────────────────────────────────────
        tk.Label(self, text='🖥  Equipment Status',
                 bg='#0D1B2A', fg='#90CAF9',
                 font=('Consolas', 10, 'bold'),
                 anchor='w', padx=10, pady=3).pack(fill='x')

        pad = {'padx': 6, 'pady': 3, 'fill': 'x'}

        # ── Servo Power ───────────────────────────────────────────────────────
        fs = self._lf(self, 'Servo Power')
        fs.pack(**pad)
        self._servo_lbl = tk.Label(fs, text='● ON  (Ready)',
                                   bg=BG, fg='#4CAF50',
                                   font=('Consolas', 11, 'bold'))
        self._servo_lbl.pack(pady=3)

        # ── Control State ─────────────────────────────────────────────────────
        f = self._lf(self, 'Control State')
        f.pack(**pad)
        self._ctrl_lbl = tk.Label(f, text='● EQ OFFLINE',
                                  bg=BG, fg='#EF9A9A',
                                  font=('Consolas', 12, 'bold'))
        self._ctrl_lbl.pack(pady=4)

        # ── Process State ─────────────────────────────────────────────────────
        f2 = self._lf(self, 'Process State')
        f2.pack(**pad)
        self._proc_lbl = tk.Label(f2, text='● IDLE',
                                  bg=BG, fg='#78909C',
                                  font=('Consolas', 12, 'bold'))
        self._proc_lbl.pack(pady=4)

        # ── PPID ──────────────────────────────────────────────────────────────
        f3 = self._lf(self, 'Recipe (PPID)')
        f3.pack(**pad)
        self._ppid_var = tk.StringVar(value='(none)')
        tk.Label(f3, textvariable=self._ppid_var,
                 bg=BG, fg='#CE93D8',
                 font=('Consolas', 10)).pack(pady=4)

        # ── Stage status ──────────────────────────────────────────────────────
        f4 = self._lf(self, 'Stage Presence')
        f4.pack(**pad)
        self._stage_labels = {}
        for key, display in [('bg_l', 'BG Stage L'), ('bg_r', 'BG Stage R'),
                              ('wf',   'Wafer Stage')]:
            row = tk.Frame(f4, bg=BG)
            row.pack(fill='x', padx=4, pady=1)
            tk.Label(row, text=f'{display}:', bg=BG, fg='#546E7A',
                     font=('Consolas', 9), width=12, anchor='w').pack(side='left')
            lbl = tk.Label(row, text='Empty', bg=BG, fg='#546E7A',
                           font=('Consolas', 9), anchor='w')
            lbl.pack(side='left')
            self._stage_labels[key] = lbl

        # ── Event history ─────────────────────────────────────────────────────
        f5 = self._lf(self, 'Recent Events')
        f5.pack(padx=6, pady=3, fill='both', expand=True)

        self._evt = tk.Text(f5, bg='#0D1117', fg='#90A4AE',
                            font=('Consolas', 8), height=10,
                            state='disabled', relief='flat', wrap='word')
        vsb = ttk.Scrollbar(f5, orient='vertical', command=self._evt.yview)
        self._evt.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self._evt.pack(fill='both', expand=True)
        self._evt.tag_configure('ceid', foreground='#81C784')
        self._evt.tag_configure('ts',   foreground='#37474F')

    # ── Queue drain ────────────────────────────────────────────────────────────
    def _drain(self):
        try:
            while True:
                fn, args = self._q.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.after(40, self._drain)

    # ── Public API (thread-safe) ───────────────────────────────────────────────
    def update_control_state(self, state: ControlState):
        self._q.put((self._do_ctrl, (state,)))

    def _do_ctrl(self, state):
        color, text = _CTRL_STYLE.get(state, ('#90A4AE', str(state)))
        self._ctrl_lbl.config(text=f'● {text}', fg=color)

    def update_process_state(self, state: ProcessState):
        self._q.put((self._do_proc, (state,)))

    def _do_proc(self, state):
        color, text = _PROC_STYLE.get(state, ('#90A4AE', str(state)))
        self._proc_lbl.config(text=f'● {text}', fg=color)

    def update_ppid(self, ppid: str):
        self._q.put((self._do_ppid, (ppid,)))

    def _do_ppid(self, ppid):
        self._ppid_var.set(ppid if ppid else '(none)')

    def update_stage(self, bg_l: int, bg_r: int, wf: int):
        self._q.put((self._do_stage, (bg_l, bg_r, wf)))

    def _do_stage(self, bg_l, bg_r, wf):
        def _fmt(v): return 'Wafer Present' if v else 'Empty'
        def _col(v): return '#81C784' if v else '#546E7A'
        self._stage_labels['bg_l'].config(text=_fmt(bg_l), fg=_col(bg_l))
        self._stage_labels['bg_r'].config(text=_fmt(bg_r), fg=_col(bg_r))
        self._stage_labels['wf'].config(text=_fmt(wf),   fg=_col(wf))

    def update_servo(self, is_on: bool):
        self._q.put((self._do_servo, (is_on,)))

    def _do_servo(self, is_on: bool):
        if is_on:
            self._servo_lbl.config(text='● ON  (Ready)', fg='#4CAF50')
        else:
            self._servo_lbl.config(text='● OFF (Servo Power Off)', fg='#EF5350')

    def log_event(self, ceid: int, name: str):
        self._q.put((self._do_log_event, (ceid, name)))

    def _do_log_event(self, ceid, name):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        self._evt.config(state='normal')
        self._evt.insert('end', f'{ts} ', 'ts')
        self._evt.insert('end', f'CEID {ceid:>4}: {name}\n', 'ceid')
        self._evt.config(state='disabled')
        self._evt.see('end')
