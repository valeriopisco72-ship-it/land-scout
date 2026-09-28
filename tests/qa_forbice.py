# -*- coding: utf-8 -*-
"""QA forbice — quanto vale un voto costruito su controlli mancanti.

Un 8,2 con il PAI verificato pulito e un 8,2 con il PAI non raggiunto sono lo
stesso numero nella graduatoria dello scan, e non valgono la stessa cosa: il
secondo puo' diventare 2,5 alla prima consultazione di IdroGEO. Il flag "PAI
NON verificato" c'e', ma sta in fondo a una lista, e ordinando per voto si
guarda il numero.

`forbice` ricalcola il voto nei due scenari estremi — ogni lacuna sfavorevole,
ogni lacuna favorevole — e ordina le lacune per quanto pesano: prima quelle che
possono BLOCCARE, poi le altre. Non inventa vincoli e non li toglie: dice solo
fin dove il voto puo' muoversi, e quale verifica fare per prima.

I modi di sbagliare, tutti con controprova:
  - una particella verificata ovunque che risulta "fragile" (forbice inventata);
  - una lacuna bloccante che non risulta tale;
  - una forbice che non contiene il voto attuale (peggiore > voto, migliore < voto);
  - uno scan che non porta la forbice fino al CSV e al GeoJSON.

Strada facendo (28/09/2026) il dossier ha rivelato tre difetti suoi, chiusi qui:
la raccomandazione non riceveva PAI e paesaggio da `feasibility` (frana P4 ->
"agriPV RACCOMANDATO, voto 10"), la distanza dalla rete misurata dal dossier non
arrivava al motore, e `recommend` "consigliava" una tecnologia in classe D.
Lo scan ricalcola la classe dopo le penalita' OSM ("voto 7,4 classe A").
"""
import csv
import io
import json
import os
import random
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


try:
    from landscout import forbice as F
except Exception as e:          # noqa: BLE001 — fase rossa: il modulo non esiste
    print(f'  FAIL import landscout.forbice ({type(e).__name__}: {e})')
    print('\n' + '=' * 72)
    print('  RISULTATO: 0/1 pass   ·   1 FAIL (1 gravi)')
    print('=' * 72)
    sys.exit(1)

from landscout import engine as E

# Una particella verificata su ogni fonte automatica, e pulita.
PULITA = {'ha': 3.0, 'slope': 3.0, 'zps_pct': 0.0, 'zps_border_m': 9e9,
          'pai_fr': -1, 'pai_idr': 0, 'pai_incompleto': False,
          'habitat_ban': False, 'in_sic': False,
          'usi_civici': False, 'bosco_142g': False, 'tratturo': False, 'art136': False,
          'paesaggio_incompleto': False, 'd_se_m': 600.0, 'd_150kv_m': 400.0}


def chiavi(fb):
    return [x['chiave'] for x in fb['lacune']]


print('\n[1] tutto verificato: nessuna forbice inventata')

fb = F.forbice(dict(PULITA), 'agriPV')
s, cl, _ = E.score_parcel(dict(PULITA), 'agriPV')
t('il voto e quello del motore', fb['voto'] == E.voto_10(s, cl), f"{fb['voto']} vs {s}",
  grave=True)
t('nessuna lacuna', fb['lacune'] == [], str(chiavi(fb)), grave=True)
t('peggiore = voto = migliore', fb['voto_peggiore'] == fb['voto'] == fb['voto_migliore'],
  str(fb), grave=True)
t('dichiarata robusta', fb['robusto'] is True, str(fb['robusto']), grave=True)
t('e nessuna "verifica prima"', fb['verifica_prima'] is None, str(fb['verifica_prima']))

print('\n[2] PAI non raggiunto: la lacuna che puo bloccare viene per prima')

p = dict(PULITA, pai_fr=None, pai_idr=None, pai_incompleto=True)
fb = F.forbice(p, 'agriPV')
t('la lacuna PAI c e', 'pai' in chiavi(fb), str(chiavi(fb)), grave=True)
pai = next((x for x in fb['lacune'] if x['chiave'] == 'pai'), {})
t('e puo bloccare', pai.get('puo_bloccare') is True, str(pai), grave=True)
t('nel caso peggiore il voto crolla al tetto dei bloccati (<= 2,5)',
  fb['voto_peggiore'] <= 2.5, str(fb['voto_peggiore']), grave=True)
t('non e robusta', fb['robusto'] is False, grave=True)
t('verifica prima: il PAI', fb['verifica_prima'] and 'PAI' in fb['verifica_prima'],
  str(fb['verifica_prima']), grave=True)
t('il voto attuale non cambia: la forbice non e una penalita',
  fb['voto'] == F.forbice(dict(PULITA), 'agriPV')['voto'],
  f"{fb['voto']} vs {F.forbice(dict(PULITA), 'agriPV')['voto']}")

print('\n[3] Natura 2000 non raggiunta: blocca solo se l habitat non e verificato')

fb_hok = F.forbice(dict(PULITA, zps_pct=None, zps_border_m=None), 'agriPV')
n2k = next((x for x in fb_hok['lacune'] if x['chiave'] == 'natura2000'), {})
t('con habitat verificato sgombro: in ZPS e iter VINCA, non blocco',
  n2k.get('puo_bloccare') is False and n2k.get('voto_se_peggio', 9) < fb_hok['voto'],
  str(n2k), grave=True)
fb_hnv = F.forbice(dict(PULITA, zps_pct=None, zps_border_m=None, habitat_ban=None),
                   'agriPV')
n2k2 = next((x for x in fb_hnv['lacune'] if x['chiave'] == 'natura2000'), {})
t('con habitat ignoto: la ZPS puo bloccare l agriPV', n2k2.get('puo_bloccare') is True,
  str(n2k2), grave=True)
t('e anche l habitat, da solo, puo bloccare',
  any(x['chiave'] == 'habitat' and x['puo_bloccare'] for x in fb_hnv['lacune']),
  str(fb_hnv['lacune']), grave=True)
fb_bess = F.forbice(dict(PULITA, zps_pct=None, zps_border_m=None), 'BESS')
n2k3 = next((x for x in fb_bess['lacune'] if x['chiave'] == 'natura2000'), {})
t('BESS: la ZPS pesa (-3 punti di voto) ma non blocca',
  n2k3.get('puo_bloccare') is False and n2k3.get('voto_se_peggio', 99) < fb_bess['voto'],
  str(n2k3))

print('\n[4] le lacune che non bloccano: rete e paesaggio')

fb = F.forbice(dict(PULITA, d_se_m=None, d_150kv_m=None), 'BESS')
rete = next((x for x in fb['lacune'] if x['chiave'] == 'rete'), {})
t('SE non individuata: lacuna "rete"', bool(rete), str(chiavi(fb)), grave=True)
t('non blocca', rete.get('puo_bloccare') is False, str(rete))
t('e il caso migliore sta sopra il voto attuale', fb['voto_migliore'] > fb['voto'],
  f"{fb['voto_migliore']} vs {fb['voto']}", grave=True)

fb = F.forbice(dict(PULITA, paesaggio_incompleto=True, usi_civici=None, bosco_142g=None,
                    tratturo=None, art136=None), 'agriPV')
pae = next((x for x in fb['lacune'] if x['chiave'] == 'paesaggio'), {})
t('SITAP non raggiunto: lacuna "paesaggio"', bool(pae), str(chiavi(fb)), grave=True)
t('abbassa il voto nel caso peggiore ma non blocca',
  pae.get('puo_bloccare') is False and pae.get('voto_se_peggio', 99) < fb['voto'], str(pae))

print('\n[5] ordine: prima cio che blocca, poi il resto')

p = dict(PULITA, d_se_m=None, slope=None, pai_fr=None, pai_idr=None, pai_incompleto=True,
         paesaggio_incompleto=True)
fb = F.forbice(p, 'agriPV')
bl = [x['puo_bloccare'] for x in fb['lacune']]
t('le bloccanti stanno tutte davanti', bl == sorted(bl, reverse=True), str(bl), grave=True)
t('pendenza ignota e bloccante (oltre il 15% l agriPV non si fa)',
  any(x['chiave'] == 'pendenza' and x['puo_bloccare'] for x in fb['lacune']),
  str(fb['lacune']), grave=True)
t('bloccanti_ignoti conta le bloccanti', fb['bloccanti_ignoti'] == sum(bl),
  f"{fb['bloccanti_ignoti']} vs {sum(bl)}")

print('\n[6] invariante: peggiore <= voto <= migliore, sempre (fuzz)')

rnd = random.Random(20260928)
violazioni = []
for i in range(400):
    q = {'ha': rnd.choice([0.4, 1.2, 3.0, 8.0])}
    q['zps_pct'] = rnd.choice([None, 0.0, 5.0, 60.0, 100.0])
    q['zps_border_m'] = None if q['zps_pct'] is None else rnd.choice([-1, 200, 9e9])
    q['pai_fr'] = rnd.choice([None, -1, 0, 2, 4])
    q['pai_idr'] = rnd.choice([None, 0, 1, 3])
    q['pai_incompleto'] = q['pai_fr'] is None or q['pai_idr'] is None
    q['habitat_ban'] = rnd.choice([None, False, True])
    q['slope'] = rnd.choice([None, 1.0, 9.0, 13.0, 30.0])
    q['d_se_m'] = rnd.choice([None, 100.0, 2500.0, 9e9])
    q['paesaggio_incompleto'] = rnd.choice([True, False])
    for k in ('usi_civici', 'bosco_142g', 'art136'):
        q[k] = rnd.choice([None, False, True])
    tech = rnd.choice(['BESS', 'agriPV'])
    try:
        r = F.forbice(q, tech, aggiustamento=rnd.choice([0.0, -8.0, -18.0]))
        if not (r['voto_peggiore'] <= r['voto'] <= r['voto_migliore']):
            violazioni.append((q, tech, r['voto_peggiore'], r['voto'], r['voto_migliore']))
    except Exception as e:      # noqa: BLE001
        violazioni.append((q, tech, repr(e)))
t('400 particelle casuali: nessuna forbice che esclude il voto attuale',
  not violazioni, str(violazioni[:2]), grave=True)

print('\n[7] i controlli "mai eseguiti" si dichiarano, e su richiesta entrano nella forbice')

fb = F.forbice(dict(PULITA), 'agriPV')
t('di default elenca i blocker mai controllati (EUAP, aree non idonee, incendi…)',
  len(fb['mai_controllati']) >= 3 and any('fuoco' in m for m in fb['mai_controllati']),
  str(fb['mai_controllati']), grave=True)
t('...senza sporcare la forbice delle fonti automatiche', fb['robusto'] is True,
  str(fb['lacune']))
fbc = F.forbice(dict(PULITA), 'agriPV', completa=True)
t('completa=True: entrano fra le lacune', any(x['tipo'] == 'controllo' for x in fbc['lacune']),
  str(chiavi(fbc)), grave=True)
t('e il caso peggiore diventa un blocco', fbc['voto_peggiore'] <= 2.5, str(fbc['voto_peggiore']))
fbv = F.forbice(dict(PULITA, area_protetta=False, area_non_idonea=False, percorsa_fuoco=False,
                     coltura_storica=False), 'agriPV')
t('controprova: controlli popolati -> non piu "mai controllati"',
  not any(k in ' '.join(fbv['mai_controllati']).lower() for k in ('euap', 'fuoco')),
  str(fbv['mai_controllati']))

print('\n[8] aggiustamento (le penalita OSM dello scan) e riga di scan')

fb0 = F.forbice(dict(PULITA), 'agriPV')
fb8 = F.forbice(dict(PULITA), 'agriPV', aggiustamento=-10.0)
t('l aggiustamento sposta il voto come fa lo scan', abs(fb0['voto'] - fb8['voto'] - 1.0) < 0.051,
  f"{fb0['voto']} -> {fb8['voto']}", grave=True)

riga = {'ha': 2.0, 'slope': 4.0, 'n2k_pct': None, 'n2k_border_m': None, 'n2k_incompleto': True,
        'pai_fr': -1, 'pai_idr': 0, 'pai_incompleto': False, 'habitat_ban': None,
        'usi_civici': None, 'in_sic': None, 'd_se_m': 1200, 'd_150kv_m': 900}
p = F.da_riga_scan(riga)
t('da_riga_scan: n2k_pct None -> zps_pct None', p['zps_pct'] is None, str(p), grave=True)
t('...e habitat None resta None', p['habitat_ban'] is None, str(p), grave=True)
fb = F.forbice(p, 'agriPV')
t('e la forbice ci lavora sopra', 'natura2000' in chiavi(fb) and 'habitat' in chiavi(fb),
  str(chiavi(fb)))
riga_ok = dict(riga, n2k_pct=0.0, n2k_border_m=None, n2k_incompleto=False)
t('controprova: n2k verificato 0% -> zps_pct 0', F.da_riga_scan(riga_ok)['zps_pct'] == 0.0)

print('\n[9] descrivi: una riga leggibile')

d = F.descrivi(F.forbice(dict(PULITA, pai_fr=None, pai_idr=None, pai_incompleto=True),
                         'agriPV'))
t('mostra la forbice e la prima verifica', '–' in d and 'PAI' in d, d, grave=True)
d = F.descrivi(F.forbice(dict(PULITA), 'agriPV'))
t('controprova: robusta -> lo dice', 'robust' in d.lower(), d)

# ------------------------------------------------------------------ scan
print('\n[10] scan: la forbice arriva alla riga, al CSV e al GeoJSON')

_argv = list(sys.argv)
sys.argv = ['qa_forbice']
from landscout import scan                        # noqa: E402
sys.argv = _argv


def quad(lat, lon, d=0.0012):
    return [(lat, lon), (lat, lon + d), (lat + d, lon + d), (lat + d, lon)]


PARTICELLE = {'IT.AGE.PLA.F717_00007000.100': quad(42.3300, 13.7000),
              'IT.AGE.PLA.F717_00007000.101': quad(42.3320, 13.7020)}
# un edificio OSM sopra la 100: lo scan toglie 10 punti DOPO il motore
EDIFICIO = {'type': 'way', 'tags': {'building': 'yes'},
            'geometry': [{'lat': la, 'lon': lo} for la, lo in
                         quad(42.3302, 13.7002, 0.0004) + [(42.3302, 13.7002)]]}


# ...e un bosco sul 17% della 100 (-8) e una SE a ~2,9 km: il motore la mette in A
# (~92), le penalita' OSM la portano a ~74. Senza ricalcolo la classe restava A.
BOSCO = {'type': 'way', 'tags': {'natural': 'wood'},
         'geometry': [{'lat': la, 'lon': lo} for la, lo in
                      quad(42.3300, 13.7000, 0.0005) + [(42.3300, 13.7000)]]}
SE = {'type': 'node', 'lat': 42.3570, 'lon': 13.7006, 'tags': {'power': 'substation'}}


def prepara(nome, osm):
    base = os.path.join(tempfile.mkdtemp(), nome)
    json.dump({k: [list(q) for q in v] for k, v in PARTICELLE.items()},
              open(base + '_parcels_cache.json', 'w'))
    json.dump({'elements': osm}, open(base + '_osm_cache.json', 'w'))
    json.dump({'F717_70_100': 3.0, 'F717_70_101': 3.0}, open(base + '_dem_cache.json', 'w'))
    return base


def esegui(base, get_finta):
    veri = (scan.get, scan.time.sleep, scan.urllib.request.urlopen)
    scan.get = get_finta
    scan.time.sleep = lambda *_a, **_k: None

    def _muto(*_a, **_k):
        raise OSError('rete disattivata nel test')

    scan.urllib.request.urlopen = _muto
    buf, vero = io.StringIO(), sys.stdout
    try:
        sys.stdout = buf
        scan.main(['--bbox', '42.3290,13.6990,42.3340,13.7040', '--min-ha', '0.01',
                   '--tech', 'agriPV', '--out', os.path.relpath(base, scan.BASE)])
    finally:
        sys.stdout = vero
        scan.get, scan.time.sleep, scan.urllib.request.urlopen = veri
    return json.load(open(base + '.json', encoding='utf-8'))['risultati']


def get_ok(url, timeout=120):
    return json.dumps({'features': []})


def get_pai_giu(url, timeout=120):
    if 'idrogeo' in url:
        raise OSError('ISPRA non raggiungibile')
    return json.dumps({'features': []})


b_ok = prepara('ok', [EDIFICIO, BOSCO, SE])
righe = esegui(b_ok, get_ok)
rr = {r['pla']: r for r in righe}
t('ogni riga porta la forbice', all('forbice' in r for r in righe), str(righe[0].keys()),
  grave=True)
r100 = rr.get('100', {})
fb100 = r100.get('forbice') or {}
t('il voto della forbice e il voto della riga (penalita OSM compresa)',
  fb100.get('voto') == r100.get('voto'), f"{fb100.get('voto')} vs {r100.get('voto')}",
  grave=True)
# la classe si decide sul PUNTEGGIO (come nel motore): 79,9 e' B anche se il voto
# arrotondato mostra 8,0
t('la classe della riga e coerente col punteggio dopo le penalita OSM',
  all((r['classe'] == 'D') or (r['classe'] == ('A' if r['score'] >= 80 else
                                               ('B' if r['score'] >= 60 else 'C')))
      for r in righe), str([(r['score'], r['classe']) for r in righe]), grave=True)
t('...e la particella con l edificio non resta in classe A con un punteggio da B',
  not (r100.get('classe') == 'A' and r100.get('score', 100) < 80),
  f"{r100.get('score')} {r100.get('classe')}", grave=True)

righe_giu = esegui(prepara('giu', []), get_pai_giu)
t('PAI giu: il peggiore crolla e la prima verifica e il PAI',
  all(r['forbice']['voto_peggiore'] <= 2.5 and 'PAI' in (r['forbice']['verifica_prima'] or '')
      for r in righe_giu), str([r['forbice'] for r in righe_giu][:1]), grave=True)

with open(b_ok + '.csv', encoding='utf-8-sig') as f:
    intest = next(csv.reader(f, delimiter=';'))
for c in ('voto_peggiore', 'voto_migliore', 'verifica_prima'):
    t(f'il CSV ha la colonna {c}', c in intest, str(intest), grave=True)

print('\n[11] scan: GeoJSON pronto per QGIS / geojson.io')

gj_path = b_ok + '.geojson'
t('scrive il .geojson', os.path.exists(gj_path), grave=True)
if os.path.exists(gj_path):
    gj = json.load(open(gj_path, encoding='utf-8'))
    t('FeatureCollection con una feature per particella',
      gj.get('type') == 'FeatureCollection' and len(gj.get('features', [])) == len(righe),
      str(len(gj.get('features', []))), grave=True)
    f0 = gj['features'][0]
    x, y = f0['geometry']['coordinates'][0][0]
    t('coordinate [lon, lat] (RFC 7946), non [lat, lon]', 13 < x < 14 and 42 < y < 43,
      str((x, y)), grave=True)
    anello = f0['geometry']['coordinates'][0]
    t('anello chiuso', anello[0] == anello[-1], str(anello[:2]))
    pr = f0['properties']
    for c in ('voto', 'classe', 'voto_peggiore', 'voto_migliore', 'verifica_prima', 'fill'):
        t(f'la feature porta "{c}"', c in pr, str(sorted(pr)), grave=True)

from landscout import gis as G                    # noqa: E402

sint = [dict(pla='1', fg='7', com='X000', ha=2.0, voto=8.5, classe='A', poly=quad(42.33, 13.70),
             flags=[], forbice={'voto': 8.5, 'voto_peggiore': 8.5, 'voto_migliore': 8.5,
                                'verifica_prima': None, 'bloccanti_ignoti': 0}),
        dict(pla='2', fg='7', com='X000', ha=2.0, voto=8.5, classe='A', poly=quad(42.34, 13.70),
             flags=['⚠ PAI NON verificato'],
             forbice={'voto': 8.5, 'voto_peggiore': 2.5, 'voto_migliore': 8.5,
                      'verifica_prima': 'PAI frane/idraulica', 'bloccanti_ignoti': 1}),
        dict(pla='3', fg='7', com='X000', ha=2.0, voto=2.5, classe='D', poly=quad(42.35, 13.70),
             flags=['PAI frana P4: BLOCKER'], forbice=None),
        dict(pla='4', fg='7', com='X000', ha=2.0, voto=7.0, classe='B', poly=[], flags=[])]
fc, scartate = G.collezione_scan(sint)
pr = {f['properties']['particella']: f['properties'] for f in fc['features']}
t('A e D hanno colori diversi', pr['1']['fill'] != pr['3']['fill'], str(pr['1']['fill']),
  grave=True)
t('stesso voto, ma la fragile si distingue dal contorno',
  pr['1']['stroke'] != pr['2']['stroke'] and pr['2'].get('fragile') is True
  and pr['1'].get('fragile') is False, f"{pr['1']['stroke']} vs {pr['2']['stroke']}",
  grave=True)
t('la particella senza geometria non sparisce in silenzio: torna fra gli scarti',
  scartate == ['7/4'] and '4' not in pr, str(scartate), grave=True)

print('\n[12] dossier: la raccomandazione vede il PAI, e il dossier porta la forbice')

from landscout import dossier as D                # noqa: E402
from landscout import recommend as R              # noqa: E402

v_p4 = {'zps': False, 'zps_pct': 0.0, 'sic': False, 'n2k_ok': True,
        'habitat_ban': False, 'habitat_ok': True,
        'pai_fr': 4, 'pai_idr': 0, 'pai_ok': True, 'pai_blocker': True,
        'usi_civici': False, 'bosco_142g': False, 'tratturo': False, 'archeo_area': False,
        'art136': False, 'lago_300m': False, 'fiume_150m': False, 'sitap_ok': True,
        'verdetto': 'BLOCK_PAI(frana P4 100%)'}
ep = D.parcella_motore({'ha': 3.0, 'slope': 3.0, 'd_se_m': 500}, v_p4)
t('parcella_motore porta la classe di frana al motore', ep.get('pai_fr') == 4, str(ep),
  grave=True)
reco = R.recommend(ep)
agri = next(x for x in reco['ranking'] if x['tech'] == 'agriPV')
t('frana P4: l agriPV non e piu "RACCOMANDATO"', agri['verdetto'] != 'RACCOMANDATO'
  and agri.get('classe') == 'D', str(agri), grave=True)
v_ok = dict(v_p4, pai_fr=-1, pai_blocker=False, verdetto='CLEAN')
reco_ok = R.recommend(D.parcella_motore({'ha': 3.0, 'slope': 3.0, 'd_se_m': 500}, v_ok))
agri_ok = next(x for x in reco_ok['ranking'] if x['tech'] == 'agriPV')
t('controprova: senza frana resta raccomandato', agri_ok['verdetto'] == 'RACCOMANDATO',
  str(agri_ok))
v_nv = dict(v_p4, pai_fr=None, pai_idr=None, pai_ok=False, pai_blocker=None)
ep_nv = D.parcella_motore({'ha': 3.0, 'slope': 3.0, 'd_se_m': 500}, v_nv)
t('PAI non raggiunto: arriva come incompleto, non come "nessuna frana"',
  ep_nv.get('pai_incompleto') is True and ep_nv.get('pai_fr') is None, str(ep_nv), grave=True)

sol = getattr(D, 'solidita', None)
t('dossier espone solidita()', callable(sol), grave=True)
if callable(sol):
    S = sol({'a': {'ha': 3.0, 'slope': 3.0, 'd_se_m': 500}},
            {'a': v_nv}, 'agriPV')
    t('una particella col PAI muto e fragile', S['fragili'] == 1 and
      'PAI' in (S['particelle']['a']['verifica_prima'] or ''), str(S), grave=True)
    S2 = sol({'a': {'ha': 3.0, 'slope': 3.0, 'd_se_m': 500}}, {'a': v_ok}, 'agriPV')
    t('controprova: tutto verificato -> nessuna fragile', S2['fragili'] == 0, str(S2),
      grave=True)

    cr = getattr(D, 'con_rete', None)
    t('dossier espone con_rete', callable(cr), grave=True)
    if callable(cr):
        pp = {'a': {'ha': 3.0}, 'b': {'ha': 2.0, 'd_se_m': 4000}}
        q = cr(pp, {'verificato': True, 'd_se_m': 300})
        t('la distanza misurata dal dossier arriva alle particelle che non ce l hanno',
          q['a'].get('d_se_m') == 300, str(q), grave=True)
        t('...senza sovrascrivere quella gia fornita', q['b']['d_se_m'] == 4000, str(q))
        q = cr({'a': {'ha': 3.0}}, {'verificato': False})
        t('controprova: Overpass giu -> nessuna distanza inventata',
          q['a'].get('d_se_m') is None, str(q), grave=True)
        s_con = R.recommend(D.parcella_motore(cr({'a': {'ha': 3.0, 'slope': 3.0}},
                                                 {'verificato': True, 'd_se_m': 300})['a'], v_ok))
        s_senza = R.recommend(D.parcella_motore({'ha': 3.0, 'slope': 3.0}, v_ok))
        t('con la SE a 300 m il voto BESS sale rispetto a "SE non individuata"',
          next(x for x in s_con['ranking'] if x['tech'] == 'BESS')['score']
          > next(x for x in s_senza['ranking'] if x['tech'] == 'BESS')['score'],
          '', grave=True)

    d = {'comune': 'Esempio', 'prov': 'BN', 'n': 1, 'tot_ha': 3.0, 'avvisi_luogo': [],
         'fattibilita': {'verdetti': {'NON VERIFICATO: PAI': 1}, 'ha_habitat_vietato': 0.0,
                         'usi_civici_n': 0, 'sitap_ok': True, 'habitat_ok': True, 'n2k_ok': True,
                         'copertura': {'regione': 'CAMPANIA', 'habitat_regionale': True,
                                       'habitat_fonte': 'carta regionale', 'sitap': True,
                                       'sitap_mancanti': []}},
         'solidita': S,
         'tecnologia': {'consigliata': 'agriPV', 'distribuzione': {'agriPV': 1}},
         'rete': {'verificato': False, 'comune': 'Esempio', 'prov': 'BN', 'nota': '-'},
         'rete_distanza': {'verificato': False}, 'resa': {'error': 'offline'},
         'valore_eur': {'errore': 'n.d. nel test'}, 'aziende': []}
    buf, vero = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        D.print_dossier(d)
    finally:
        sys.stdout = vero
    riga = next((x for x in buf.getvalue().splitlines() if 'Solidit' in x), '')
    t('la stampa del dossier dichiara il voto fragile e cosa verificare',
      'fragil' in riga.lower() and 'PAI' in riga, riga or buf.getvalue()[-300:], grave=True)

print('\n[13] build_dossier gira da capo a fondo (offline) e resta coerente')

# E' il percorso della pagina web e non l'aveva mai eseguito nessun test: ogni pezzo
# qui sotto parla con la rete e viene sostituito, il resto e' codice vero.
import landscout.catasto as CT                    # noqa: E402

finti = {
    'risolvi_luogo': lambda la, lo, c, p: ('Esempio', 'BN', []),
    'contesto_nodo': lambda c, p: {},
    'nodo_info': lambda c, p: {'verificato': False, 'comune': c, 'prov': p, 'nota': '-'},
    'distanza_rete': lambda punti: {'verificato': True, 'd_se_m': 300, 'n_se': 1,
                                    'd_linea_m': 200, 'linea_kv': 150, 'tensioni_kv': [150]},
    'resa_terreno': lambda *a, **k: {'error': 'offline'},
    'match_companies': lambda *a, **k: [],
}
veri = {k: getattr(D, k) for k in finti}
vero_cat, vero_feas = CT.arricchisci, D.VC.feasibility
try:
    for k, fn in finti.items():
        setattr(D, k, fn)
    CT.arricchisci = lambda parcels: (parcels, [])
    D.VC.feasibility = lambda parcels, prov=None: {
        'p1': dict(v_nv, ha=3.0, verdetto='NON VERIFICATO: PAI frane/idraulica (IdroGEO non raggiunto)'),
        'p2': dict(v_p4, ha=2.0)}
    dd, e, _ = None, None, ''
    try:
        dd = D.build_dossier({'p1': {'lat': 41.30, 'lon': 14.60, 'ha': 3.0, 'slope': 3.0},
                              'p2': {'lat': 41.301, 'lon': 14.601, 'ha': 2.0, 'slope': 3.0}},
                             'Esempio', 'BN', geo=False)
    except Exception as ex:     # noqa: BLE001
        e = ex
finally:
    for k, fn in veri.items():
        setattr(D, k, fn)
    CT.arricchisci, D.VC.feasibility = vero_cat, vero_feas
t('build_dossier completa senza eccezioni', e is None and dd is not None, repr(e), grave=True)
if dd:
    t('la frana P4: nessuna tecnologia "consigliata" (erano tutte in classe D)',
      dd['reco_per_particella'].get('p2') is None, str(dd['reco_per_particella']), grave=True)
    t('controprova: la particella senza blocchi ha una tecnologia consigliata',
      dd['reco_per_particella'].get('p1') is not None, str(dd['reco_per_particella']))

    t('il dossier porta la solidita: 1 particella fragile (PAI muto)',
      dd['solidita']['fragili'] == 1 and 'PAI' in (dd['solidita']['verifica_prima'] or ''),
      str(dd['solidita']), grave=True)
    t('la distanza di rete e la stessa nella sezione ③ e nel motore',
      dd['rete_distanza']['d_se_m'] == 300, str(dd['rete_distanza']))

r_d = R.recommend(D.parcella_motore({'ha': 3.0, 'slope': 3.0, 'd_se_m': 500}, v_p4))
t('recommend: se tutte le tecnologie sono in classe D, top = None',
  r_d['top'] is None, f"top={r_d['top']} sintesi={r_d['sintesi']}", grave=True)
t('...e la sintesi non scrive "Tecnologia consigliata"',
  'consigliata' not in (r_d['sintesi'] or ''), r_d['sintesi'], grave=True)

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
