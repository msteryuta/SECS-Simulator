"""
Sniffer / Event Logger widget.

Color scheme:
  Blue   → Host → EQ  (HOST sends)
  Green  → EQ  → Host (EQ sends / events)
  Gray   → Info / status
  Red    → Errors
  Purple → SECS body decoded content
"""
import queue
import datetime
import tkinter as tk
from tkinter import ttk

# ── Colour palette ───────────────────────────────────────────────────────────
BG          = '#0D1117'
HOST_COLOR  = '#4FC3F7'   # blue
EQ_COLOR    = '#81C784'   # green
INFO_COLOR  = '#90A4AE'   # gray
ERROR_COLOR = '#EF9A9A'   # red
WARN_COLOR  = '#FFD54F'   # yellow
PARAM_COLOR = '#CE93D8'   # purple
BODY_COLOR  = '#7E57C2'   # deep purple — decoded body
TIME_COLOR  = '#546E7A'   # dark gray
SEP_COLOR   = '#161B22'   # separator bg
HEADER_COLOR = '#FFCC80'  # orange


def _decode_body(body: bytes, stream: int = 0, function: int = 0) -> str:
    """Decode raw SECS-II body to SEMI E5 SML with [n/m] length notation.

    The annotation line shows exact byte counts:
      body_bytes  = number of body bytes (what appears after the 10-byte HSMS header)
      frame_bytes = 4 (length field) + 10 (HSMS header) + body_bytes

    Returns empty string if body is None/empty or decoding fails.
    """
    if not body:
        return ''
    try:
        from core.secs_codec import decode_item, _item_total_bytes
        item, _ = decode_item(body)
        body_b  = len(body)
        frame_b = 4 + 10 + body_b   # HSMS: 4B length-field + 10B header + body
        item_b  = _item_total_bytes(item)
        ann = (f'  // body={body_b}B  frame={frame_b}B'
               f'  (HSMS 10B hdr + 4B len-field + {body_b}B body'
               f', item={item_b}B)')
        sml = item.to_sml(indent=1)
        return ann + '\n' + sml
    except Exception:
        hex_preview = body[:32].hex(' ') + ('…' if len(body) > 32 else '')
        return f'  (raw) {hex_preview}'


class EventLogger(tk.Frame):
    """
    Scrolled dark-theme text widget with colour-tagged SECS message logging.
    All public methods are thread-safe (dispatch via queue + after()).
    """

    def __init__(self, parent, **kwargs):
        bg = kwargs.pop('bg', BG)
        super().__init__(parent, bg=bg, **kwargs)
        self._q: queue.Queue = queue.Queue()
        self._show_body = tk.BooleanVar(value=True)
        self._build_ui()
        self._drain()

    def _build_ui(self):
        # ── Title bar ──────────────────────────────────────────────────────────
        tk.Label(self, text='SECS Sniffer',
                 bg='#010409', fg='#58A6FF',
                 font=('Consolas', 10, 'bold'),
                 anchor='w', padx=10, pady=4).pack(fill='x')

        # ── Toolbar ────────────────────────────────────────────────────────────
        bar = tk.Frame(self, bg='#010409')
        bar.pack(fill='x', pady=(0, 1))

        tk.Button(bar, text=' Clear ', bg='#21262D', fg='#8B949E',
                  relief='flat', font=('Consolas', 9), cursor='hand2',
                  command=self.clear).pack(side='left', padx=4, pady=2)

        tk.Checkbutton(
            bar, text='Show Body', variable=self._show_body,
            bg='#010409', fg='#8B949E', selectcolor='#21262D',
            activebackground='#010409', relief='flat',
            font=('Consolas', 9),
        ).pack(side='left', padx=8)

        tk.Label(bar, text='Filter:', bg='#010409', fg='#444C56',
                 font=('Consolas', 9)).pack(side='left')
        self._filter = tk.StringVar(value='ALL')
        for f in ('ALL', 'S1', 'S2', 'S5', 'S6', 'S7'):
            tk.Radiobutton(
                bar, text=f, variable=self._filter, value=f,
                bg='#010409', fg='#8B949E', selectcolor='#21262D',
                activebackground='#010409', relief='flat',
                font=('Consolas', 9),
            ).pack(side='left', padx=1)
        bar2 = tk.Frame(self, bg='#010409')
        bar2.pack(fill='x', pady=(0, 1))
        tk.Label(bar2, text='      ', bg='#010409').pack(side='left')
        for f in ('S9', 'S10', 'S14'):
            tk.Radiobutton(
                bar2, text=f, variable=self._filter, value=f,
                bg='#010409', fg='#8B949E', selectcolor='#21262D',
                activebackground='#010409', relief='flat',
                font=('Consolas', 9),
            ).pack(side='left', padx=1)

        # ── Text area ──────────────────────────────────────────────────────────
        frame = tk.Frame(self, bg=BG)
        frame.pack(fill='both', expand=True)

        self._text = tk.Text(
            frame, bg=BG, fg='#C9D1D9',
            font=('Consolas', 9), wrap='none',
            state='disabled', relief='flat',
            selectbackground='#264F78',
            padx=8, pady=4, insertbackground='white',
        )
        vsb = ttk.Scrollbar(frame, orient='vertical',   command=self._text.yview)
        hsb = ttk.Scrollbar(frame, orient='horizontal', command=self._text.xview)
        self._text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side='right',  fill='y')
        hsb.pack(side='bottom', fill='x')
        self._text.pack(side='left', fill='both', expand=True)

        # ── Colour tags ────────────────────────────────────────────────────────
        self._text.tag_configure('host',   foreground=HOST_COLOR)
        self._text.tag_configure('eq',     foreground=EQ_COLOR)
        self._text.tag_configure('info',   foreground=INFO_COLOR)
        self._text.tag_configure('error',  foreground=ERROR_COLOR)
        self._text.tag_configure('warn',   foreground=WARN_COLOR)
        self._text.tag_configure('param',  foreground=PARAM_COLOR)
        self._text.tag_configure('body',   foreground=BODY_COLOR,
                                           font=('Consolas', 8))
        self._text.tag_configure('time',   foreground=TIME_COLOR)
        self._text.tag_configure('sep',    foreground=SEP_COLOR,
                                           background=SEP_COLOR)
        self._text.tag_configure('header', foreground=HEADER_COLOR)
        self._text.tag_configure('bold',   font=('Consolas', 9, 'bold'))

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
    def clear(self):
        self._q.put((self._do_clear, ()))

    def _do_clear(self):
        self._text.config(state='normal')
        self._text.delete('1.0', 'end')
        self._text.config(state='disabled')

    def log_message(self, direction: str, stream: int, function: int,
                    description: str, extra: dict = None, body: bytes = None):
        """Log a SECS message. Thread-safe."""
        filt = self._filter.get()
        if filt != 'ALL' and filt != f'S{stream}':
            return
        self._q.put((self._do_log_msg,
                     (direction, stream, function, description, extra, body)))

    def _do_log_msg(self, direction, stream, function, description, extra, body):
        ts  = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        tag = 'host' if direction == 'Host->EQ' else 'eq'
        arrow = '>' if direction == 'Host->EQ' else '<'

        t = self._text
        t.config(state='normal')

        # Separator
        t.insert('end', ' \n', 'sep')

        # Header line
        t.insert('end', f'{ts}  ', 'time')
        t.insert('end', f'[{arrow}] ', (tag, 'bold'))
        t.insert('end', f'S{stream}F{function} ', (tag, 'bold'))
        t.insert('end', f'{description}\n', tag)

        # Extra metadata (CEID, RCMD, HCACK)
        if extra:
            self._render_extra(extra, tag)

        # Decoded SECS body (SEMI E5 SML with [n/m] byte annotation)
        if self._show_body.get():
            if body:
                decoded = _decode_body(body, stream, function)
                if decoded:
                    t.insert('end', decoded + '\n', 'body')
            else:
                # Header-only message (e.g. S7F19, S1F15): show frame size
                t.insert('end',
                          f'  // body=0B  frame=14B  (header only)\n'
                          f'  <S{stream}F{function}>\n',
                          'body')

        t.config(state='disabled')
        t.see('end')

    def _render_extra(self, extra: dict, tag: str):
        t = self._text
        if extra.get('ceid') is not None:
            ceid_name = extra.get('ceid_name', '')
            t.insert('end', f'  CEID={extra["ceid"]}', 'param')
            if ceid_name:
                t.insert('end', f'  ({ceid_name})', 'param')
            t.insert('end', '\n')
        if extra.get('rcmd'):
            t.insert('end', f'  RCMD={extra["rcmd"]}\n', 'param')
            for k, v in extra.get('params', {}).items():
                if v:
                    t.insert('end', f'    {k}={v}\n', 'param')
        if extra.get('hcack') is not None:
            labels = {
                0: 'OK', 1: 'No command', 2: 'Cannot now',
                3: 'Bad param', 4: 'Will signal later', 5: 'Already',
                65: 'Servo OFF', 71: 'No Map',
                72: 'Not ready', 74: 'Tape sensor OFF', 77: 'Wrong recipe type',
            }
            code = extra['hcack']
            t.insert('end', f'  HCACK={code}  {labels.get(code, "?")}\n', 'header')
        if extra.get('alid') is not None:
            action = extra.get('action', '')
            t.insert('end', f'  ALID={extra["alid"]}  [{action}]  {extra.get("text","")}\n',
                     'warn' if action == 'SET' else 'param')

    def log_info(self, message: str):
        self._q.put((self._do_log_info, (message,)))

    def _do_log_info(self, message):
        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        t  = self._text
        t.config(state='normal')
        t.insert('end', f'{ts}  ', 'time')
        t.insert('end', f'{message}\n', 'info')
        t.config(state='disabled')
        t.see('end')

    def log_error(self, message: str):
        self._q.put((self._do_log_error, (message,)))

    def _do_log_error(self, message):
        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        t  = self._text
        t.config(state='normal')
        t.insert('end', f'{ts}  ', 'time')
        t.insert('end', f'[ERR]  {message}\n', 'error')
        t.config(state='disabled')
        t.see('end')
