# -*- coding: utf-8 -*-
"""QA scan — la porta d'ingresso, che fino al 12/08/2026 non era testabile.

`scan.py` faceva `argparse` a livello di modulo: importarlo alzava SystemExit(2).
Erano 357 righe — quelle che trovano le particelle e le arricchiscono di vincoli,
il primo stadio di ogni analisi — senza un test e senza modo di scriverne uno.
Spostato il corpo in `main(argv)`, questo file e' il primo test che lo esercita.

Gira **senza rete**: le tre cache che lo scan usa gia' (particelle, OSM, DEM)
vengono pre-riempite in una cartella temporanea, e le due chiamate che restano
passano tutte da `scan.get`, che viene sostituita. Cosi' il test misura la
PIPELINE, non la disponibilita' dei servizi.

L'invariante che conta piu' di tutti: **il PAI che non si scarica non e' un'area
senza frane, e' un'area non verificata**. Lo scan lo dichiara gia' (c'e' il
commento nel codice): qui viene inchiodato, perche' un commento non e' un test.
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


print('\n[1] il modulo si importa senza uccidere il processo chiamante')

_argv = list(sys.argv)
sys.argv = ['qa_scan']
try:
    from landscout import scan
    importato = True
    errore = ''
except SystemExit as e:
    importato = False
    errore = f'SystemExit({e})'
finally:
    sys.argv = _argv
t('import landscout.scan non alza SystemExit', importato, errore, grave=True)
if not importato:
    print('  (senza import non si puo proseguire)')
    sys.exit(1)
t('espone main() invocabile con argv espliciti', callable(scan.main), grave=True)
t('e la chiamata di rete passa da un solo punto: get()', callable(scan.get), grave=True)


# ---------------------------------------------------------------- fixture
def quad(lat, lon, d=0.0012):
    return [(lat, lon), (lat, lon + d), (lat + d, lon + d), (lat + d, lon)]


# gli id devono rispettare il regex dello scan: IT.AGE.PLA.<COM>_0*<FG>00.<PLA>
PARTICELLE = {
    'IT.AGE.PLA.F717_00007000.100': quad(42.3300, 13.7000),
    'IT.AGE.PLA.F717_00007000.101': quad(42.3320, 13.7020),
    # controprova: un poligono non-particella (strada) deve essere scartato
    'IT.AGE.PLA.F717_00007000.STRADA': quad(42.3335, 13.7035),
}
ATTESE = 2
OSM_VUOTO = {'elements': []}


def prepara(dirtmp, nome='s'):
    """Semina le tre cache che lo scan usa gia': cosi' non tocca la rete."""
    base = os.path.join(dirtmp, nome)
    json.dump({k: [list(p) for p in v] for k, v in PARTICELLE.items()},
              open(base + '_parcels_cache.json', 'w'))
    json.dump(OSM_VUOTO, open(base + '_osm_cache.json', 'w'))
    json.dump({}, open(base + '_dem_cache.json', 'w'))
    return base


def esegui(base, get_finta, extra=()):
    """Lancia main() con la rete disinnescata. Ritorna le righe del JSON."""
    veri = (scan.get, scan.time.sleep, scan.urllib.request.urlopen)
    scan.get = get_finta
    scan.time.sleep = lambda *_a, **_k: None

    def _muto(*_a, **_k):
        raise OSError('rete disattivata nel test')

    scan.urllib.request.urlopen = _muto
    buf, vero_out = io.StringIO(), sys.stdout
    try:
        sys.stdout = buf
        scan.main(['--bbox', '42.3290,13.6990,42.3340,13.7040', '--min-ha', '0.01',
                   '--out', os.path.relpath(base, scan.BASE)] + list(extra))
    finally:
        sys.stdout = vero_out
        scan.get, scan.time.sleep, scan.urllib.request.urlopen = veri
    with open(base + '.json', encoding='utf-8') as f:
        d = json.load(f)
    return d['risultati'], buf.getvalue()


def get_ok(url, timeout=120):
    """N2K e PAI raggiungibili e VUOTI: nessun sito, nessuna frana."""
    return json.dumps({'features': []})


def get_pai_rotto(url, timeout=120):
    if 'idrogeo' in url:
        raise OSError('ISPRA non raggiungibile')
    return json.dumps({'features': []})


print('\n[2] la pipeline gira offline e produce i due file')

d1 = tempfile.mkdtemp()
b1 = prepara(d1)
righe, log = esegui(b1, get_ok)
t('scrive il .json', os.path.exists(b1 + '.json'), grave=True)
t('e il .csv', os.path.exists(b1 + '.csv'), grave=True)
t('una riga per particella VERA (la strada e scartata)', len(righe) == ATTESE,
  f'{len(righe)} righe', grave=True)
r0 = righe[0] if righe else {}
for campo in ('com', 'fg', 'pla', 'ha', 'voto', 'classe', 'poly'):
    t(f'ogni riga porta "{campo}"', campo in r0, str(sorted(r0))[:120], grave=True)
t('il poligono viaggia con la riga: e il ponte verso blocco.da_scan',
  isinstance(r0.get('poly'), list) and len(r0['poly']) >= 3, str(r0.get('poly'))[:60],
  grave=True)
t('gli ettari sono positivi', bool(righe) and all(x['ha'] > 0 for x in righe),
  str([x['ha'] for x in righe]))

print('\n[3] il PAI che non si scarica NON e un area senza frane')

d2 = tempfile.mkdtemp()
b2 = prepara(d2)
righe2, log2 = esegui(b2, get_pai_rotto)
t('la pipeline non si ferma per un layer muto', len(righe2) == ATTESE,
  f'{len(righe2)} righe', grave=True)
t('ogni riga esce con pai_incompleto = True',
  bool(righe2) and all(x.get('pai_incompleto') is True for x in righe2),
  str([x.get('pai_incompleto') for x in righe2]), grave=True)
t('e la pericolosita frane e None (non -1, che vorrebbe dire "controllato e pulito")',
  bool(righe2) and all(x.get('pai_fr') is None for x in righe2),
  str([x.get('pai_fr') for x in righe2]), grave=True)
t('la pericolosita idraulica idem',
  bool(righe2) and all(x.get('pai_idr') is None for x in righe2),
  str([x.get('pai_idr') for x in righe2]), grave=True)
t('e lo dice a schermo, non in silenzio', 'NON VERIFICATO' in log2, log2[-300:],
  grave=True)

print('\n[4] controprova: PAI raggiunto e vuoto = controllato e pulito')

t('pai_incompleto = False',
  bool(righe) and all(x.get('pai_incompleto') is False for x in righe),
  str([x.get('pai_incompleto') for x in righe]), grave=True)
t('e pai_fr = -1 (controllato, nessuna classe di frana)',
  bool(righe) and all(x.get('pai_fr') == -1 for x in righe), str([x.get('pai_fr') for x in righe]),
  grave=True)
t('nel log non compare l allarme', 'NON VERIFICATO' not in log, log[-200:], grave=True)

print('\n[5] i due esiti si distinguono davvero')

t('lo stesso identico input da esiti diversi solo per la fonte muta',
  [x.get('pai_fr') for x in righe] != [x.get('pai_fr') for x in righe2],
  f"{[x.get('pai_fr') for x in righe]} vs {[x.get('pai_fr') for x in righe2]}",
  grave=True)

print('\n[6] la CLI resta quella di prima')

try:
    scan.main([])
    alzato = False
except SystemExit as e:
    alzato = (e.code == 2)
t('senza --bbox e --out esce con codice 2, come argparse deve fare', alzato, grave=True)

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
