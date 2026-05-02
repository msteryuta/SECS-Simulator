"""
Stream 14 (Object Services) handlers.

  S14F1  GetAttr Request  (HOST → EQ)  → S14F2 GetAttr Data

Request structure (L,5):
  1. OBJSPEC  A64   (empty string = local equipment)
  2. OBJTYPE  A40   (e.g. "Substrate")
  3. L[n]     OBJID A80 each
  4. L[q]     qualifier: L[3] ATTRID, ATTRDATA, ATTRRELN(U1)
  5. L[a]     ATTRID A40 — requested attributes

Reply structure (L,2):
  1. L[n]  objects: each L[2]: OBJID(A), L[b] of L[2]: ATTRID(A), ATTRDATA(A)
  2. L[2]  status: OBJACK(U1 0=OK), L[p] errors (each L[2]: ERRCODE(U8), ERRTEXT(A80))

When ATTRID "MapData" is requested, returns a sample XML die-bond map.
"""
import logging
from core.secs_codec import L, A, B, U1, decode_item, Fmt

logger = logging.getLogger(__name__)

_MAP_XML = (
    '<?xml version="1.0" encoding="utf-8" ?>'
    '<MapData xmlns="urn:semi-org:xsd.E142-1.V0105.SubstrateMap">'
    '<Layouts><Layout><ProductID/><Dimension/><DeviceSize/><StepSize/></Layout></Layouts>'
    '<Substrates><Substrate><LotId/><SlotNumber/><GoodDevices/><SupplierName/></Substrate></Substrates>'
    '<SubstrateMaps><SubstrateMap>'
    '<Overlay MapName="MAPNAME"><BinCodeMap>'
    '<MapHeader>'
    '<Header>BIN COMBINATION SEQ=D1,D2,D3,D4,D5</Header>'
    '<Header>BIN COMBINATION CODE=A:BXXXX,C:11111,X:B11XX,Z:XXXXX</Header>'
    '</MapHeader>'
    '<BinDefinitions/>'
    '<BinCode>.......ZZZZZ......</BinCode>'
    '<BinCode>....AAAAACCCXXC...</BinCode>'
    '<BinCode>..AAAAAAACCCCCCC..</BinCode>'
    '<BinCode>.AAAAAAAACCCCCCCC.</BinCode>'
    '<BinCode>AAAAAAAAACCCCCCCCC</BinCode>'
    '<BinCode>.AAAAAAAACCCCCCCCC</BinCode>'
    '<BinCode>.AAAAAAAACCCCCCCC.</BinCode>'
    '<BinCode>...AXAAAACCCCCX...</BinCode>'
    '<BinCode>....AAAAACCCCCX...</BinCode>'
    '<BinCode>.......AAAC.......</BinCode>'
    '</BinCodeMap><MapFooter/><DeviceIdMap/></Overlay>'
    '</SubstrateMap></SubstrateMaps></MapData>'
)


def _parse_s14f1(body: bytes):
    """Parse S14F1 body. Returns (objtype, objids, attr_names)."""
    if not body:
        return '', [], []
    try:
        item, _ = decode_item(body)
        if item.fmt != Fmt.LIST or len(item.value) < 5:
            return '', [], []
        objtype    = item.value[1].value if item.value[1].fmt == Fmt.ASCII else ''
        objid_list = [e.value for e in item.value[2].value
                      if e.fmt == Fmt.ASCII] if item.value[2].fmt == Fmt.LIST else []
        attr_names = [e.value for e in item.value[4].value
                      if e.fmt == Fmt.ASCII] if item.value[4].fmt == Fmt.LIST else []
        return objtype, objid_list, attr_names
    except Exception:
        return '', [], []


def _build_attr_data(attr_names: list, state) -> list:
    """Return list of L[2](ATTRID, ATTRDATA) items for requested attributes."""
    items = []
    for name in attr_names:
        if name == 'MapData':
            value = _MAP_XML
        elif name == 'SubstrateType':
            value = 'Wafer'
        elif name == 'LotID':
            value = str(state.get_sv(567) or '')
        elif name == 'SlotID':
            value = str(state.get_sv(569) or '')
        elif name == 'WaferID':
            value = str(state.get_sv(568) or '')
        elif name == 'RecipeName':
            value = str(state.get_sv(536) or '')
        else:
            value = ''
        items.append(L(A(name), A(value)))
    return items


def handle_s14f1(hdr: dict, body: bytes, router) -> bytes:
    """GetAttr Request → GetAttr Data."""
    objtype, objids, attr_names = _parse_s14f1(body)
    logger.info('S14F1 GetAttr  objtype=%r  objids=%r  attrs=%r',
                objtype, objids, attr_names)

    state = router.gem_state

    if objids:
        obj_items = []
        for oid in objids:
            attr_pairs = _build_attr_data(attr_names, state)
            obj_items.append(L(A(oid), L(*attr_pairs)))
    else:
        attr_pairs = _build_attr_data(attr_names, state)
        obj_items  = [L(A('LocalEQ'), L(*attr_pairs))]

    objects_list = L(*obj_items)
    status_list  = L(U1(0), L())   # OBJACK=0 (success), no errors

    return L(objects_list, status_list).encode()


# ── Registration ──────────────────────────────────────────────────────────────
def register(router):
    router.register(14, 1, handle_s14f1)
