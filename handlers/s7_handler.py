"""
Stream 7 (Process Program Management) handlers.

S7F3   Process Program Send              — Host → EQ  → S7F4
S7F17  Delete Process Program Send      — Host → EQ  → S7F18
S7F19  Current EPPD Request             — Host → EQ  → S7F20
S7F25  Formatted Process Program Request— Host → EQ  → S7F26

Recipes are stored persistently under:
    <project_root>/recipes/<PPID>/recipe.json

recipe.json schema:
  Structured body:  {"ccode_list": [{"ccode": int, "params": [str, ...]}, ...]}
  Binary body:      {"raw_hex": "<hex string>"}

S7F26 formatted body is always L[4]: PPID (from S7F25), MDLN/SOFTREV (from router.config),
then the fixed S7F26_CCODE_LIST (same shape as equipment log). Upload (S7F3) only persists
recipe.json; S7F25 does not read ccode_list from disk for the reply.
"""
import json
import logging
import shutil
from pathlib import Path
from typing import List

from core.secs_codec import L, A, B, U4, decode_item, Fmt

logger = logging.getLogger(__name__)

RECIPES_DIR: Path = Path(__file__).parent.parent / 'recipes'

# Fixed S7F26 CCODE block: L[17] of L[ U4, L[A,...] ] — edit here only; not merged from uploads.
S7F26_CCODE_LIST: list[dict] = [
    {'ccode': 1000, 'params': ['0.5']},
    {'ccode': 1010, 'params': ['10']},
    {'ccode': 1020, 'params': ['0']},
    {'ccode': 1030, 'params': ['0']},
    {'ccode': 1040, 'params': ['0']},
    {'ccode': 1050, 'params': ['0.05']},
    {'ccode': 1170, 'params': ['0.2']},
    {'ccode': 1180, 'params': ['1']},
    {'ccode': 1190, 'params': ['0.2']},
    {'ccode': 1200, 'params': ['5']},
    {'ccode': 1210, 'params': ['0']},
    {'ccode': 1220, 'params': ['0']},
    {'ccode': 1230, 'params': ['0']},
    {'ccode': 1240, 'params': ['0']},
    {'ccode': 1250, 'params': ['0']},
    {'ccode': 1260, 'params': ['0']},
    {'ccode': 1500, 'params': ['1']},
]


# ── Internal helpers ────────────────────────────────────────────────────────────

def _get_ppid_list() -> List[str]:
    """Return list of PPIDs that exist on disk."""
    if not RECIPES_DIR.exists():
        return []
    return [d.name for d in RECIPES_DIR.iterdir() if d.is_dir()]


def _recipe_path(ppid: str) -> Path:
    return RECIPES_DIR / ppid / 'recipe.json'


def _load_recipe(ppid: str) -> dict | None:
    p = _recipe_path(ppid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception as exc:
        logger.warning('Failed to read recipe %r: %s', ppid, exc)
        return None


def _save_recipe(ppid: str, content: dict):
    folder = RECIPES_DIR / ppid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'recipe.json').write_text(
        json.dumps(content, indent=2, ensure_ascii=False), encoding='utf-8'
    )


def _parse_ppid_from_body(body: bytes) -> str:
    """
    Parse PPID from S7F25 / S7F3 body.

    Accepts both:
      - A(ppid)         — bare ASCII item
      - L[A(ppid), ...]  — list with ASCII as first element
    """
    if not body:
        return ''
    try:
        item, _ = decode_item(body)
        if item.fmt == Fmt.ASCII:
            return item.value
        if item.fmt == Fmt.LIST and item.value:
            first = item.value[0]
            if first.fmt == Fmt.ASCII:
                return first.value
    except Exception:
        pass
    return ''


# ── S7F3 Process Program Send → S7F4 (ACKC7) ──────────────────────────────────

def handle_s7f3(hdr: dict, body: bytes, router) -> bytes:
    """S7F3 Process Program Send → S7F4 (ACKC7)."""
    if not body:
        logger.warning('S7F3: empty body received')
        return B(3).encode()   # ACKC7 = 3 (format error)

    try:
        item, _ = decode_item(body)
    except Exception as exc:
        logger.warning('S7F3: decode error: %s', exc)
        return B(3).encode()

    # Expect L[A(PPID), B(PPBODY)]
    if item.fmt != Fmt.LIST or len(item.value) < 2:
        logger.warning('S7F3: unexpected body format')
        return B(3).encode()

    ppid_item  = item.value[0]
    ppbody_item = item.value[1]

    if ppid_item.fmt != Fmt.ASCII:
        return B(3).encode()

    ppid = ppid_item.value.strip()
    if not ppid:
        logger.warning('S7F3: empty PPID rejected')
        return B(3).encode()

    # Decode PPBODY
    if ppbody_item.fmt == Fmt.BINARY:
        raw_bytes: bytes = ppbody_item.value
    else:
        logger.warning('S7F3: PPBODY is not BINARY (fmt=%s)', ppbody_item.fmt)
        return B(3).encode()

    # Try to interpret PPBODY as JSON (structured recipe)
    try:
        content = json.loads(raw_bytes.decode('utf-8'))
        if not isinstance(content, dict):
            raise ValueError('not a dict')
    except Exception:
        # Store as raw hex
        content = {'raw_hex': raw_bytes.hex()}

    try:
        _save_recipe(ppid, content)
        logger.info('S7F3: uploaded recipe %r (%d bytes)', ppid, len(raw_bytes))
        return B(0).encode()   # ACKC7 = 0 (OK)
    except Exception as exc:
        logger.error('S7F3: failed to save recipe %r: %s', ppid, exc)
        return B(5).encode()   # ACKC7 = 5 (storage error)


# ── S7F17 Delete Process Program Send → S7F18 (ACKC7) ─────────────────────────

def handle_s7f17(hdr: dict, body: bytes, router) -> bytes:
    """S7F17 Delete Process Program Send → S7F18 (ACKC7)."""
    ppids_to_delete: List[str] = []
    if body:
        try:
            item, _ = decode_item(body)
            if item.fmt == Fmt.LIST:
                ppids_to_delete = [e.value for e in item.value if e.fmt == Fmt.ASCII]
            elif item.fmt == Fmt.ASCII:
                ppids_to_delete = [item.value] if item.value else []
        except Exception:
            pass

    if not ppids_to_delete:
        # Empty list = delete all
        if RECIPES_DIR.exists():
            for folder in list(RECIPES_DIR.iterdir()):
                if folder.is_dir():
                    shutil.rmtree(folder, ignore_errors=True)
        logger.info('S7F17: deleted all recipes')
        return B(0).encode()

    ackc7 = 0
    for ppid in ppids_to_delete:
        folder = RECIPES_DIR / ppid
        if folder.exists() and folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            logger.info('S7F17: deleted recipe %r', ppid)
        else:
            logger.warning('S7F17: recipe %r not found', ppid)
            ackc7 = 4   # PPID not found
    return B(ackc7).encode()


# ── S7F19 Current EPPD Request → S7F20 (pplist) ───────────────────────────────

def handle_s7f19(hdr: dict, body: bytes, router) -> bytes:
    """S7F19 Current EPPD Request → S7F20 (list of PPIDs in equipment)."""
    ppids = _get_ppid_list()
    # Also include currently loaded PPID if set
    current = router.gem_state.ppid
    if current and current not in ppids:
        ppids = [current] + ppids
    items = [A(p) for p in ppids]
    logger.debug('S7F20: returning %d PPIDs', len(items))
    return L(*items).encode()


# ── S7F25 Formatted Process Program Request → S7F26 ───────────────────────────

def handle_s7f25(hdr: dict, body: bytes, router) -> bytes:
    """S7F25 Formatted Process Program Request → S7F26 (fixed CCODE list + request PPID)."""
    ppid = _parse_ppid_from_body(body)
    if not ppid:
        logger.warning('S7F25: empty PPID')
        return L().encode()

    cfg     = router.config
    model   = cfg.get('MODEL', 'UNKNOWN')[:6]
    softrev = cfg.get('SOFTREV', '0.0.0')[:6]

    # Build ccode list: L[L[CCODE, L[PPARM...]]] — always S7F26_CCODE_LIST
    ccode_items = []
    for entry in S7F26_CCODE_LIST:
        ccode  = entry.get('ccode', 0)
        params = [A(str(p)) for p in entry.get('params', [])]
        ccode_items.append(L(U4(ccode), L(*params)))

    reply = L(A(ppid), A(model), A(softrev), L(*ccode_items))
    logger.debug('S7F25 → S7F26: ppid=%r model=%r softrev=%r ccodes=%d',
                 ppid, model, softrev, len(ccode_items))
    return reply.encode()


# ── Registration ───────────────────────────────────────────────────────────────

def register(router):
    router.register(7,  3, handle_s7f3)
    router.register(7, 17, handle_s7f17)
    router.register(7, 19, handle_s7f19)
    router.register(7, 25, handle_s7f25)
