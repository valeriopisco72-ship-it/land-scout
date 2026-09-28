# -*- coding: utf-8 -*-
"""QA fonti — le risposte che arrivano ma non valgono, nei punti dove non si guardava.

`vincoli.json_valido` (16/07) ha chiuso il *semi-guasto* — HTTP 200 con dentro un
errore — per il percorso vincoli. Lo scan, cioe' la porta d'ingresso del tool,
interrogava gli stessi servizi (EEA, IdroGEO) con un `json.loads` nudo e
`.get('features', [])`: un errore mascherato da 200 diventava "nessuna ZPS",
"nessuna frana". E se l'EEA era giu' del tutto, lo scan usciva con `zps_pct=0`
senza dirlo: per l'agriPV la differenza fra un blocker e un terreno pulito.

Stessa famiglia, altri punti (audit 28/09/2026):
  - `scan --vincoli` leggeva `habitat_ban()` nel formato di prima del 16/07
    (stringa) e riceveva un dict: AttributeError, scan morto;
  - senza `--vincoli` la riga dello scan scriveva `habitat_ban: False` —
    "verificato, nessun divieto" — su un controllo mai eseguito;
  - `cache.cached_file(ttl_giorni=0)` non scadeva MAI (lo zero-falsy che
    `JsonCache` aveva gia' corretto il 16/07);
  - una feature in un CRS sbagliato veniva scartata in silenzio (PAI, SITAP,
    EEA): il layer risultava "verificato", con un poligono in meno;
  - SITAP indovinava l'ordine lat/lon con una finestra sulla Campania: fuori
    regione una risposta (lat, lon) finiva nel posto sbagliato.

Gira OFFLINE: ogni chiamata di rete e' sostituita.
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shapely.geometry import Point

OK = FAIL = 0
GRAVI = []


def t(nome, cond, dettaglio='', grave=False):
    global OK, FAIL
    if cond:
        OK += 1
        print(f'  ok   {nome}')
    else:
        FAIL += 1
        print(f'  FAIL {nome} {dettaglio}')
        if grave:
            GRAVI.append(nome)


def zitto(fn, *a, **k):
    """Esegue fn col suo output catturato. Ritorna (risultato, eccezione, output)."""
    buf, vero = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        return fn(*a, **k), None, buf.getvalue()
    except Exception as e:           # noqa: BLE001
        return None, e, buf.getvalue()
    finally:
        sys.stdout = vero


_argv = list(sys.argv)
sys.argv = ['qa_fonti']
from landscout import scan                       # noqa: E402
sys.argv = _argv
from landscout import cache as CA                # noqa: E402
from landscout import vincoli as V               # noqa: E402

# ------------------------------------------------------------------ fixture scan
def quad(lat, lon, d=0.0012):
    return [(lat, lon), (lat, lon + d), (lat + d, lon + d), (lat + d, lon)]


PARTICELLE = {
    'IT.AGE.PLA.F717_00007000.100': quad(42.3300, 13.7000),
    'IT.AGE.PLA.F717_00007000.101': quad(42.3320, 13.7020),
}


def prepara(nome):
    d = tempfile.mkdtemp()
    base = os.path.join(d, nome)
    json.dump({k: [list(p) for p in v] for k, v in PARTICELLE.items()},
              open(base + '_parcels_cache.json', 'w'))
    json.dump({'elements': []}, open(base + '_osm_cache.json', 'w'))
    json.dump({}, open(base + '_dem_cache.json', 'w'))
    return base


def esegui(base, get_finta, extra=()):
    veri = (scan.get, scan.time.sleep, scan.urllib.request.urlopen)
    scan.get = get_finta
    scan.time.sleep = lambda *_a, **_k: None

    def _muto(*_a, **_k):
        raise OSError('rete disattivata nel test')

    scan.urllib.request.urlopen = _muto
    try:
        _, e, log = zitto(scan.main, ['--bbox', '42.3290,13.6990,42.3340,13.7040',
                                      '--min-ha', '0.01', '--tech', 'agriPV',
                                      '--out', os.path.relpath(base, scan.BASE)] + list(extra))
    finally:
        scan.get, scan.time.sleep, scan.urllib.request.urlopen = veri
    if e is not None:
        return None, log, e
    with open(base + '.json', encoding='utf-8') as f:
        return json.load(f)['risultati'], log, None


VUOTA = json.dumps({'features': []})
ERRORE_200 = json.dumps({'error': {'code': 500, 'message': 'Unable to complete operation'}})


def get_ok(url, timeout=120):
    return VUOTA


def get_eea_giu(url, timeout=120):
    if 'discomap' in url:
        raise OSError('EEA non raggiungibile')
    return VUOTA


def get_eea_200(url, timeout=120):
    return ERRORE_200 if 'discomap' in url else VUOTA


def get_pai_200(url, timeout=120):
    return ERRORE_200 if 'idrogeo' in url else VUOTA


def avviso_n2k(r):
    return any('Natura 2000' in f and 'NON verificat' in f for f in r.get('flags', []))


print('\n[1] scan: EEA giu -> Natura 2000 NON verificata, non "fuori ZPS"')

ok_r, ok_log, e = esegui(prepara('ok'), get_ok)
t('controprova: con EEA raggiunta e vuota lo scan gira', e is None and ok_r, repr(e), grave=True)
t('controprova: e nessun avviso Natura 2000 inventato',
  bool(ok_r) and not any(avviso_n2k(r) for r in ok_r), str(ok_r and ok_r[0]['flags']))
t('controprova: n2k_pct = 0 (verificato fuori)', bool(ok_r) and all(r['n2k_pct'] == 0
                                                                     for r in ok_r))

giu, log, e = esegui(prepara('giu'), get_eea_giu)
t('EEA giu: lo scan non si ferma', e is None and bool(giu), repr(e), grave=True)
if giu:
    t('n2k_pct e None, non 0 (0 vorrebbe dire "controllato e fuori")',
      all(r.get('n2k_pct') is None for r in giu), str([r.get('n2k_pct') for r in giu]),
      grave=True)
    t('la riga porta n2k_incompleto = True', all(r.get('n2k_incompleto') is True for r in giu),
      str([r.get('n2k_incompleto') for r in giu]), grave=True)
    t('e il motore lo scrive nei flag', all(avviso_n2k(r) for r in giu),
      str(giu[0]['flags']), grave=True)
    t('lo dice a schermo', 'Natura 2000 NON verificat' in log, log[-300:], grave=True)

print('\n[2] scan: il semi-guasto (HTTP 200 con un errore dentro) non e "nessun vincolo"')

s200, log200, e = esegui(prepara('eea200'), get_eea_200)
t('EEA 200+errore: lo scan non si ferma', e is None and bool(s200), repr(e), grave=True)
if s200:
    t('ZPS NON verificata, non "fuori"', all(r.get('n2k_pct') is None for r in s200),
      str([r.get('n2k_pct') for r in s200]), grave=True)

p200, logp, e = esegui(prepara('pai200'), get_pai_200)
t('IdroGEO 200+errore: lo scan non si ferma', e is None and bool(p200), repr(e), grave=True)
if p200:
    t('PAI NON verificato, non "nessuna frana"',
      all(r.get('pai_incompleto') is True and r.get('pai_fr') is None for r in p200),
      str([(r.get('pai_incompleto'), r.get('pai_fr')) for r in p200]), grave=True)

print('\n[3] scan: senza --vincoli l habitat non e "verificato pulito"')

if ok_r:
    t('habitat_ban e None nella riga (controllo non eseguito)',
      all(r.get('habitat_ban') is None for r in ok_r),
      str([r.get('habitat_ban') for r in ok_r]), grave=True)
    t('idem usi civici e SIC', all(r.get('usi_civici') is None and r.get('in_sic') is None
                                   for r in ok_r),
      str([(r.get('usi_civici'), r.get('in_sic')) for r in ok_r]))

print('\n[4] scan --vincoli: il formato di habitat_ban() dal 16/07 e un dict')

K100, K101 = 'F717_70_100', 'F717_70_101'
finti = {
    'natura2000': lambda plist, to_xy: (None, None, True),
    'sitap_paesaggio': lambda plist, to_xy, regione=None: ({}, True),
    'habitat_ban': lambda parcels: {
        K100: {'codici': {'6220*': 40.0, '5330': 10.0}, 'geometria': 'poligono'},
        K101: {'codici': {}, 'geometria': 'poligono'}},
}
ricevuti = {}


def spia_habitat(parcels):
    ricevuti.update(parcels)
    return finti['habitat_ban'](parcels)


veri = {k: getattr(V, k) for k in finti}
try:
    V.natura2000 = finti['natura2000']
    V.sitap_paesaggio = finti['sitap_paesaggio']
    V.habitat_ban = spia_habitat
    vin, logv, e = esegui(prepara('vinc'), get_ok, extra=['--vincoli', '--prov', 'BN'])
finally:
    for k, fn in veri.items():
        setattr(V, k, fn)
t('scan --vincoli non muore sul nuovo formato', e is None and bool(vin), repr(e), grave=True)
if vin:
    rr = {f"{r['com']}_{r['fg']}_{r['pla']}": r for r in vin}
    t('40% su 6220*: habitat_ban True', rr.get(K100, {}).get('habitat_ban') is True,
      str(rr.get(K100, {}).get('habitat_ban')), grave=True)
    t('e il codice dominante e una stringa, non un dict',
      rr.get(K100, {}).get('habitat') == '6220*', str(rr.get(K100, {}).get('habitat')),
      grave=True)
    t('controprova: nessun codice -> habitat_ban False (verificato sgombro)',
      rr.get(K101, {}).get('habitat_ban') is False, str(rr.get(K101, {}).get('habitat_ban')),
      grave=True)
    t('il blocker arriva al voto', rr.get(K100, {}).get('classe') == 'D',
      str(rr.get(K100, {}).get('classe')), grave=True)
t('habitat_ban riceve il POLIGONO della particella, non solo il centroide',
  all(v.get('anello') for v in ricevuti.values()) and len(ricevuti) == 2,
  str({k: bool(v.get('anello')) for k, v in ricevuti.items()}))

print('\n[4b] scan --vincoli fuori Campania: layer e carta habitat della REGIONE giusta')

# Lo scan interrogava sempre i layer SITAP con i nomi della Campania e la Carta
# Habitat della Campania, qualunque fosse il bbox. In Abruzzo quei layer non tornano
# nulla, e "nulla" diventava "verificato: nessun usi civici, nessun habitat vietato".
# Il dossier aveva gia' chiuso la stessa porta togliendo il default 'BN'.
try:
    esegui(prepara('noprov'), get_ok, extra=['--vincoli'])
    senza_prov = 'nessun errore'
except SystemExit as ex:
    senza_prov = f'exit {ex.code}'
t('--vincoli senza --prov: errore chiaro, non layer della Campania a caso',
  senza_prov == 'exit 2', senza_prov, grave=True)

chiamate_v = {'sitap': [], 'hab_reg': 0, 'hab_ispra': 0}


def sitap_spia(plist, to_xy, regione=None):
    chiamate_v['sitap'].append(regione)
    return ({}, True)


def hab_reg_spia(parcels):
    chiamate_v['hab_reg'] += 1
    return {k: {'codici': {}, 'geometria': 'poligono'} for k in parcels}


def hab_ispra_spia(parcels):
    chiamate_v['hab_ispra'] += 1
    return {k: {'codici': ({'34.5': 30.0} if k == K100 else {}), 'geometria': 'poligono'}
            for k in parcels}


veri = {k: getattr(V, k) for k in ('natura2000', 'sitap_paesaggio', 'habitat_ban', 'habitat_ispra')}
try:
    V.natura2000 = lambda plist, to_xy: (None, None, True)
    V.sitap_paesaggio = sitap_spia
    V.habitat_ban = hab_reg_spia
    V.habitat_ispra = hab_ispra_spia
    aq, logaq, e = esegui(prepara('aq'), get_ok, extra=['--vincoli', '--prov', 'AQ'])
    chiamate_aq = dict(chiamate_v, sitap=list(chiamate_v['sitap']))
    chiamate_v.update(sitap=[], hab_reg=0, hab_ispra=0)
    bn, logbn, e2 = esegui(prepara('bn'), get_ok, extra=['--vincoli', '--prov', 'BN'])
finally:
    for k, fn in veri.items():
        setattr(V, k, fn)
t('Abruzzo: lo scan gira', e is None and bool(aq), repr(e), grave=True)
t('Abruzzo: SITAP non mappato -> non interrogato con i layer campani',
  chiamate_aq['sitap'] == [], str(chiamate_aq['sitap']), grave=True)
if aq:
    t('...e usi civici restano NON verificati (None), non "assenti"',
      all(r.get('usi_civici') is None for r in aq), str([r.get('usi_civici') for r in aq]),
      grave=True)
    ra = {f"{r['com']}_{r['fg']}_{r['pla']}": r for r in aq}
    t('Abruzzo: habitat dal fallback ISPRA (CORINE 34.5 -> 6220) -> divieto rilevato',
      ra.get(K100, {}).get('habitat_ban') is True, str(ra.get(K100, {}).get('habitat_ban')),
      grave=True)
t('Abruzzo: la Carta Habitat della Campania NON viene usata',
  chiamate_aq['hab_reg'] == 0 and chiamate_aq['hab_ispra'] == 1, str(chiamate_aq), grave=True)
t('controprova Campania: SITAP con i layer CAMPANIA e carta regionale',
  e2 is None and chiamate_v['sitap'] == ['CAMPANIA'] and chiamate_v['hab_reg'] == 1
  and chiamate_v['hab_ispra'] == 0, str(chiamate_v), grave=True)

# ------------------------------------------------------------------ cache
print('\n[5] cache.cached_file: ttl_giorni=0 significa "sempre scaduto", non "mai"')

tmp = tempfile.mkdtemp()
vero_dir, vero_open = CA.CACHE_DIR, CA.urllib.request.urlopen


class _Risposta:
    def __init__(self, b):
        self.b = b

    def read(self):
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


chiamate = []


def _open_finto(req, timeout=None):
    chiamate.append(req.full_url)
    return _Risposta(b'NUOVO')


try:
    CA.CACHE_DIR = tmp
    CA.urllib.request.urlopen = _open_finto
    with open(os.path.join(tmp, 'x.bin'), 'wb') as f:
        f.write(b'VECCHIO')
    p = CA.cached_file('https://esempio.invalid/x', 'x.bin', ttl_giorni=0)
    t('ttl 0: riscarica', p is not None and open(p, 'rb').read() == b'NUOVO',
      str(p and open(p, 'rb').read()), grave=True)
    with open(os.path.join(tmp, 'y.bin'), 'wb') as f:
        f.write(b'VECCHIO')
    n0 = len(chiamate)
    p = CA.cached_file('https://esempio.invalid/y', 'y.bin', ttl_giorni=365)
    t('controprova: ttl lungo -> riusa senza rete',
      open(p, 'rb').read() == b'VECCHIO' and len(chiamate) == n0, str(chiamate))
finally:
    CA.CACHE_DIR, CA.urllib.request.urlopen = vero_dir, vero_open

# ------------------------------------------------------------------ geometrie
print('\n[6] una feature in un CRS sbagliato rende il layer NON verificato')

LA, LO = 42.3392, 13.7446


def to_xy(lat, lon):
    return (lon * 83000.0, lat * 111132.0)


def anello(la=LA, lo=LO, d=0.001):
    return [(la, lo), (la + d, lo), (la + d, lo + d), (la, lo + d)]


METRI = [[1641362.3, 5062498.5], [1641562.3, 5062498.5],
         [1641562.3, 5062698.5], [1641362.3, 5062698.5], [1641362.3, 5062498.5]]


def fc(coords, props=None, gtype='Polygon'):
    return json.dumps({'type': 'FeatureCollection', 'numberMatched': 1, 'numberReturned': 1,
                       'features': [{'type': 'Feature', 'properties': props or {},
                                     'geometry': {'type': gtype, 'coordinates': [coords]}}]})


VUOTA_WFS = json.dumps({'type': 'FeatureCollection', 'features': [],
                        'numberMatched': 0, 'numberReturned': 0})


def con_get(fn, chiamata):
    vero = V.get
    V.get = fn
    try:
        return zitto(chiamata)
    finally:
        V.get = vero


V.reset_interruttore_pai()
(fr, idr, ok), e, _ = con_get(
    lambda url, timeout=None: fc(METRI, {'cod_per_it': 4}) if 'frane' in url else VUOTA_WFS,
    lambda: V.pai([{'id': 'a', 'lat': LA, 'lon': LO, 'ha': 1.0}], to_xy))
t('PAI: la frana in metri non viene piazzata a caso', fr.get(4) is None, str(fr))
t('PAI: ...e il layer NON risulta verificato', ok is False, str(ok), grave=True)
(fr, idr, ok), e, _ = con_get(lambda url, timeout=None: VUOTA_WFS,
                              lambda: V.pai([{'id': 'a', 'lat': LA, 'lon': LO, 'ha': 1.0}], to_xy))
t('PAI controprova: quattro layer vuoti -> verificato', ok is True, str(ok), grave=True)

plist = [{'id': 'a', 'lat': LA, 'lon': LO, 'ha': 1.0}]
res, e, _ = con_get(lambda url, timeout=None: fc(METRI),
                    lambda: V.sitap_paesaggio(plist, to_xy, regione='CAMPANIA'))
out, ok = res if res else ({}, None)
t('SITAP: layer con geometrie in metri -> NON verificato', ok is False, str(ok), grave=True)
t('SITAP: ...e il layer e None, non un "vuoto = pulito"',
  out.get('bosco_142g') is None, str(out.get('bosco_142g')), grave=True)

# Piemonte: lat ~45, lon ~7.6. Server che risponde (lat, lon) — l'ordine "urn".
PLA, PLO = 45.0500, 7.6500
quadr_latlon = [[PLA - 0.01, PLO - 0.01], [PLA - 0.01, PLO + 0.01], [PLA + 0.01, PLO + 0.01],
                [PLA + 0.01, PLO - 0.01], [PLA - 0.01, PLO - 0.01]]
pl_pie = [{'id': 'b', 'lat': PLA, 'lon': PLO, 'ha': 1.0}]
res, e, _ = con_get(lambda url, timeout=None: fc(quadr_latlon),
                    lambda: V.sitap_paesaggio(pl_pie, to_xy, regione='PIEMONTE'))
out, ok = res if res else ({}, None)
g = out.get('fiume_150m')
t('SITAP fuori Campania: una risposta (lat, lon) finisce sulla particella',
  g is not None and not g.is_empty and g.contains(Point(to_xy(PLA, PLO))),
  str(g and g.bounds), grave=True)
quadr_lonlat = [[b, a] for a, b in quadr_latlon]
res, e, _ = con_get(lambda url, timeout=None: fc(quadr_lonlat),
                    lambda: V.sitap_paesaggio(pl_pie, to_xy, regione='PIEMONTE'))
out, ok = res if res else ({}, None)
g = out.get('fiume_150m')
t('controprova: la stessa risposta in (lon, lat) standard idem',
  g is not None and not g.is_empty and g.contains(Point(to_xy(PLA, PLO))),
  str(g and g.bounds), grave=True)

EEA_METRI = json.dumps({'features': [{'attributes': {'SITECODE': 'IT0', 'SITETYPE': 'A'},
                                      'geometry': {'rings': [METRI]}}]})
res, e, _ = con_get(lambda url, timeout=None: EEA_METRI, lambda: V.natura2000(plist, to_xy))
t('EEA: anelli in metri -> Natura 2000 NON verificata', res is not None and res[2] is False,
  str(res and res[2]), grave=True)
EEA_OK = json.dumps({'features': [{'attributes': {'SITECODE': 'IT0', 'SITETYPE': 'A'},
                                   'geometry': {'rings': [[[LO - 0.01, LA - 0.01],
                                                           [LO + 0.01, LA - 0.01],
                                                           [LO + 0.01, LA + 0.01],
                                                           [LO - 0.01, LA + 0.01],
                                                           [LO - 0.01, LA - 0.01]]]}}]})
res, e, _ = con_get(lambda url, timeout=None: EEA_OK, lambda: V.natura2000(plist, to_xy))
t('EEA controprova: anelli in gradi -> verificata, e la ZPS copre la particella',
  res is not None and res[2] is True and res[0] is not None
  and res[0].contains(Point(to_xy(LA, LO))), str(res), grave=True)

print('\n[7] siti transfrontalieri e coordinate 3D (revisione del 28/09/2026)')

# Un sito Natura 2000 a cavallo del confine ha vertici FUORI dal riquadro Italia ma
# in gradi validi: non e' un CRS sbagliato. Scartarlo (o dichiarare non verificato
# per sempre ogni particella di confine) e' sbagliato in entrambi i sensi.
BLA, BLO = 45.80, 6.95          # Valle d'Aosta, vicino al confine francese
bplist = [{'id': 'c', 'lat': BLA, 'lon': BLO, 'ha': 1.0}]
EEA_CONFINE = json.dumps({'features': [{'attributes': {'SITECODE': 'IT0', 'SITETYPE': 'A'},
                                        'geometry': {'rings': [[[6.30, BLA - 0.05],
                                                                [BLO + 0.05, BLA - 0.05],
                                                                [BLO + 0.05, BLA + 0.05],
                                                                [6.30, BLA + 0.05],
                                                                [6.30, BLA - 0.05]]]}}]})
res, e, _ = con_get(lambda url, timeout=None: EEA_CONFINE, lambda: V.natura2000(bplist, to_xy))
t('EEA: sito transfrontaliero (vertici oltre 6,5 E) -> verificato, e la ZPS c e',
  res is not None and res[2] is True and res[0] is not None
  and res[0].contains(Point(to_xy(BLA, BLO))), str(res and res[2]), grave=True)


def get_confine(url, timeout=120):
    return EEA_CONFINE if 'discomap' in url else VUOTA


# lo scan con un solo layer che risponde in metri e gli altri validi: NON verificato
def get_un_layer_metri(url, timeout=120):
    if 'discomap' in url and '/1/query' in url:
        return EEA_METRI
    return VUOTA


um, logum, e = esegui(prepara('unlayermetri'), get_un_layer_metri)
t('scan: un layer EEA in metri basta a rendere Natura 2000 NON verificata',
  e is None and bool(um) and all(r.get('n2k_incompleto') is True for r in um),
  str(e or [r.get('n2k_incompleto') for r in um]), grave=True)

# PAI con coordinate 3D (x, y, z): sono gradi validi, la frana va letta
QUADRATO_3D = [[LO, LA, 350.0], [LO + 0.002, LA, 350.0], [LO + 0.002, LA + 0.002, 351.0],
               [LO, LA + 0.002, 352.0], [LO, LA, 350.0]]
V.reset_interruttore_pai()
(fr, idr, ok), e, _ = con_get(
    lambda url, timeout=None: fc(QUADRATO_3D, {'cod_per_it': 4}) if 'frane' in url else VUOTA_WFS,
    lambda: V.pai([{'id': 'a', 'lat': LA, 'lon': LO, 'ha': 1.0}], to_xy))
t('PAI 3D: la P4 viene letta', e is None and fr.get(4) is not None, str(e or fr), grave=True)
t('PAI 3D: e il layer e verificato', e is None and ok is True, str(ok), grave=True)

DUE = json.dumps({'type': 'FeatureCollection', 'numberMatched': 2, 'numberReturned': 2,
                  'features': [{'type': 'Feature', 'properties': {'cod_per_it': 'x?'},
                                'geometry': {'type': 'Polygon', 'coordinates': [QUADRATO_3D]}},
                               {'type': 'Feature', 'properties': {'cod_per_it': 4},
                                'geometry': {'type': 'Polygon', 'coordinates': [QUADRATO_3D]}}]})
V.reset_interruttore_pai()
(fr, idr, ok), e, _ = con_get(
    lambda url, timeout=None: DUE if 'frane' in url else VUOTA_WFS,
    lambda: V.pai([{'id': 'a', 'lat': LA, 'lon': LO, 'ha': 1.0}], to_xy))
t('PAI: una classe illeggibile non fa saltare le feature successive',
  e is None and fr.get(4) is not None, str(e or fr), grave=True)
t('...ma rende il layer NON verificato', e is None and ok is False, str(ok), grave=True)

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
