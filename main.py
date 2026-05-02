"""
SECS/GEM Simulator — Entry point.

Usage:
    python main.py                    # startup dialog to choose model
    python main.py --model 6600WB     # start directly with TFC-6600-WB
    python main.py --model 6500WB     # start directly with TFC-6500-WB
"""
import sys
import json
import logging
import tkinter as tk
from tkinter import ttk

from paths import config_path
from core.gem_state   import GemState
from core.hsms_server import HsmsServer
from core.router      import SecsRouter
import handlers.s1_handler  as s1
import handlers.s2_handler  as s2
import handlers.s5_handler  as s5
import handlers.s6_handler  as s6
import handlers.s7_handler  as s7
import handlers.s9_handler  as s9
import handlers.s10_handler as s10
import handlers.s14_handler as s14
from gui.main_window  import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)-20s] %(levelname)s: %(message)s',
)
logger = logging.getLogger(__name__)

# Available models: display name → config file prefix
_MODELS = {
    'TFC-6600-WB  (6600WB)': '6600WB',
    'TFC-6500-WB  (6500WB)': '6500WB',
}
_DEFAULT_MODEL = '6600WB'


# ── Startup model picker ───────────────────────────────────────────────────────
def _pick_model() -> str:
    """Show a tiny dialog to pick the machine model. Returns config prefix."""
    result = {'key': _DEFAULT_MODEL}

    dlg = tk.Tk()
    dlg.title('SECS/GEM Simulator — Select Machine')
    dlg.geometry('360x180')
    dlg.configure(bg='#0D1117')
    dlg.resizable(False, False)

    tk.Label(dlg, text='Select Machine Model',
             bg='#0D1117', fg='#58A6FF',
             font=('Consolas', 13, 'bold')).pack(pady=(20, 8))

    var = tk.StringVar(value=list(_MODELS.keys())[0])
    cb = ttk.Combobox(dlg, textvariable=var,
                       values=list(_MODELS.keys()),
                       state='readonly', font=('Consolas', 11), width=30)
    cb.pack(pady=6)

    def _confirm():
        result['key'] = _MODELS[var.get()]
        dlg.destroy()

    tk.Button(dlg, text='  Start Simulator  ',
              bg='#1565C0', fg='white',
              font=('Consolas', 11, 'bold'), relief='flat',
              cursor='hand2', command=_confirm).pack(pady=12)

    dlg.protocol('WM_DELETE_WINDOW', dlg.destroy)
    dlg.mainloop()
    return result['key']


# ── Config loader ──────────────────────────────────────────────────────────────
def _load(filename: str) -> dict:
    path = config_path(filename)
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _load_model_config(model_key: str) -> dict:
    """Load and merge eq_constants + s2f41_cmds for the given model key."""
    config = _load(f'{model_key}_eq_constants.json')
    config['RCMD'] = _load(f'{model_key}_s2f41_cmds.json')
    return config


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    # Parse CLI arg --model
    model_key = _DEFAULT_MODEL
    if '--model' in sys.argv:
        idx = sys.argv.index('--model')
        if idx + 1 < len(sys.argv):
            model_key = sys.argv[idx + 1]
    elif len(sys.argv) == 1:
        # No args: show picker
        model_key = _pick_model()

    # Load config
    try:
        config = _load_model_config(model_key)
    except FileNotFoundError as exc:
        logger.error('Config file not found: %s', exc)
        sys.exit(1)

    hsms_cfg  = config.get('HSMS', {})
    port      = hsms_cfg.get('port', 5000)
    device_id = config.get('DEVICE_ID', 1)

    # ── Core objects ───────────────────────────────────────────────────────────
    gem_state = GemState()
    gem_state.set_sv(7, config.get('MODEL',   'UNKNOWN'))
    gem_state.set_sv(8, config.get('SOFTREV', '0.0.0'))

    # RouterProxy breaks the chicken-and-egg dependency between HsmsServer
    # and SecsRouter (each needs the other at construction time).
    class _Proxy:
        def __init__(self):       self._r = None
        def set(self, r):         self._r = r
        def process_message(self, h, b):
            if self._r: self._r.process_message(h, b)
        def publish(self, e, d):
            if self._r: self._r.publish(e, d)

    proxy = _Proxy()

    hsms_server = HsmsServer(
        host='0.0.0.0', port=port, device_id=device_id,
        on_message=proxy.process_message,
        on_event=lambda evt, data: proxy.publish(evt, data),
    )

    router = SecsRouter(gem_state, hsms_server, config)
    proxy.set(router)

    # ── Handler registration ───────────────────────────────────────────────────
    s1.register(router)
    s2.register(router)
    s5.register(router)
    s6.register(router)
    s7.register(router)
    s9.register(router)
    s10.register(router)
    s14.register(router)

    # ── GUI ────────────────────────────────────────────────────────────────────
    root = tk.Tk()
    MainWindow(root, router, gem_state, hsms_server, config)

    logger.info('Simulator started  model=%s  device_id=%d  port=%d',
                config.get('MODEL', '?'), device_id, port)
    root.mainloop()

    # ── Cleanup ────────────────────────────────────────────────────────────────
    hsms_server.stop()
    logger.info('Simulator stopped')


if __name__ == '__main__':
    main()
