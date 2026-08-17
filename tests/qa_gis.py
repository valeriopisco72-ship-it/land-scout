# -*- coding: utf-8 -*-
"""QA gis — export GeoJSON del blocco.

Regola della casa: ogni test deve poter FALLIRE. Qui il rischio non e' il
crash, e' il file **valido ma sbagliato**: lat/lon invertiti danno un GeoJSON
perfettamente formato che disegna i terreni in Somalia, e nessun validatore
protesta. Percio' quasi ogni verifica ha accanto la sua controprova.
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from landscout import gis as G

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


# ---------------------------------------------------------------- fixture
# Morcone: lat ~42.34, lon ~13.66. I due valori NON sono intercambiabili,
# ed e' proprio questo che rende il test dell'inversione capace di fallire.
LAT, LON = 42.34, 13.66


def quad(lat=LAT, lon=LON, d=0.002):
    """Quadrato ~200 m, in ordine ORARIO su (lat,lon) e aperto."""
    return [[lat, lon], [lat + d, lon], [lat + d, lon + d], [lat, lon + d]]


def parcella(fg='70', pla='276', ha=1.0, netti=0.8, ancora=False, poly=None, det=None):
    return {'fg': fg, 'pla': pla, 'ha': ha, 'netti': netti, 'ancora': ancora,
            'poly': quad() if poly is None else poly, 'detrazioni': det or {}}


def blocco(parts=None, titolo='Blocco test'):
    parts = parts if parts is not None else [parcella()]
    return {'titolo': titolo, 'particelle': parts,
            'ha_lordi': sum(p['ha'] for p in parts),
            'ha_netti': sum(p['netti'] for p in parts),
            'ha_ancore': sum(p['netti'] for p in parts if p['ancora']),
            'ha_acquisti': sum(p['netti'] for p in parts if not p['ancora']),
            'n_acquisti': sum(1 for p in parts if not p['ancora'])}


print('\n--- ordine delle coordinate (il bug che non si vede) ---')

a = G.anello_geojson(quad())
t('longitudine in prima posizione', abs(a[0][0] - LON) < 1e-6,
  f'primo vertice = {a[0]}', grave=True)
t('latitudine in seconda posizione', abs(a[0][1] - LAT) < 1e-6,
  f'primo vertice = {a[0]}', grave=True)

# CONTROPROVA: se il modulo NON invertisse, il primo valore sarebbe la latitudine.
# Questo test fallisce nel momento esatto in cui si toglie l'inversione.
t('controprova: nessuna coordinata resta in ordine [lat, lon]',
  all(not (abs(p[0] - LAT) < 1e-6 and abs(p[1] - LON) < 1e-6) for p in a),
  grave=True)

t('tutte le longitudini nel range italiano (6..19)',
  all(6 < p[0] < 19 for p in a), grave=True)
t('tutte le latitudini nel range italiano (35..48)',
  all(35 < p[1] < 48 for p in a), grave=True)

print('\n--- forma dell anello ---')

t('anello chiuso: primo vertice ripetuto in coda', a[0] == a[-1], grave=True)
t('5 vertici da un quadrato di 4', len(a) == 5, f'len={len(a)}')

# CONTROPROVA della chiusura: un anello gia' chiuso non viene chiuso due volte.
gia_chiuso = quad() + [quad()[0]]
t('controprova: anello gia chiuso non raddoppia il vertice',
  len(G.anello_geojson(gia_chiuso)) == 5, f'len={len(G.anello_geojson(gia_chiuso))}')

t('senso antiorario (regola mano destra)', G._area_con_segno(a) > 0,
  f'area con segno = {G._area_con_segno(a):.9f}', grave=True)

# CONTROPROVA del verso: partendo dal verso opposto si deve ottenere lo stesso
# risultato. Se _antiorario fosse un no-op, uno dei due sarebbe negativo.
antiorario_in = [[LAT, LON], [LAT, LON + 0.002], [LAT + 0.002, LON + 0.002], [LAT + 0.002, LON]]
t('controprova: input orario e antiorario danno entrambi CCW',
  G._area_con_segno(G.anello_geojson(antiorario_in)) > 0, grave=True)

print('\n--- geometrie inutilizzabili: scartate, mai in silenzio ---')

t('poligono con 2 vertici rifiutato', G.anello_geojson([[LAT, LON], [LAT, LON + 1]]) is None)
t('poly vuoto rifiutato', G.anello_geojson([]) is None)
t('poly None rifiutato', G.anello_geojson(None) is None)
t('feature senza geometria -> None', G.feature({'fg': '1', 'pla': '2'}) is None)

fc, scarti = G.collezione([parcella(pla='276'), parcella(pla='999', poly=[])])
t('la particella valida resta', len(fc['features']) == 1, f"n={len(fc['features'])}")
t('la particella rotta viene SEGNALATA', scarti == ['70/999'], f'scarti={scarti}', grave=True)

# CONTROPROVA: senza particelle rotte la lista scarti deve essere vuota,
# altrimenti staremmo solo misurando il vuoto.
_, scarti_puliti = G.collezione([parcella(), parcella(pla='277')])
t('controprova: nessuno scarto quando sono tutte valide', scarti_puliti == [])

print('\n--- proprieta utili in QGIS ---')

f_anc = G.feature(parcella(ancora=True), comune='Morcone')
f_acq = G.feature(parcella(ancora=False, netti=0.5))
pr = f_anc['properties']

t('comune riportato', pr['comune'] == 'Morcone')
t('foglio e particella riportati', pr['foglio'] == '70' and pr['particella'] == '276')
t('ha catastali e utili distinti', pr['ha_catastali'] == 1.0 and pr['ha_utili'] == 0.8)
t('ancora marcata come gia di famiglia', pr['gia_di_famiglia'] is True)
t('controprova: la non-ancora NON e marcata',
  f_acq['properties']['gia_di_famiglia'] is False, grave=True)
t('colori diversi fra ancora e da acquisire',
  pr['fill'] != f_acq['properties']['fill'], grave=True)

print('\n--- particella da frazionare: stessa geometria, due destinazioni ---')

# Caso reale Morcone Fg70/654: il perimetro catastale e' uno solo, ma vale come
# due record — porzione offerta e porzione tenuta. Senza `cat` sono gemelli muti.
vign = G.feature(parcella(pla='654', ha=0.248, netti=0.248, ancora=True,
                          det=None) | {'cat': 'FAMIGLIA - NON IN VENDITA (vigneto)',
                                       'nota': 'porzione vigneto 2.506 m2'})
prato = G.feature(parcella(pla='654', ha=0.872, netti=0.872, ancora=True) |
                  {'cat': 'FAMIGLIA - OFFERTA (prato, dopo frazionamento)'})
t('categoria riportata', vign['properties']['categoria'].startswith('FAMIGLIA - NON'))
t('nota riportata', vign['properties']['nota'] == 'porzione vigneto 2.506 m2')
t('le due porzioni sono distinguibili',
  vign['properties']['categoria'] != prato['properties']['categoria'], grave=True)
t('stessa geometria, ettari diversi',
  vign['geometry'] == prato['geometry']
  and vign['properties']['ha_catastali'] != prato['properties']['ha_catastali'], grave=True)
# CONTROPROVA: senza `cat` il campo non deve comparire inventato
t('controprova: nessuna categoria se il dato non c e',
  'categoria' not in G.feature(parcella())['properties'], grave=True)
t('controprova: nessuna nota se il dato non c e',
  'nota' not in G.feature(parcella())['properties'])

det = G.feature(parcella(det={'bosco_pct': 12.4, 'fascia_pct': 0.2}))['properties']
t('detrazione sopra soglia riportata', det['detrazioni_pct'] == {'bosco': 12.4},
  f"det={det.get('detrazioni_pct')}")
t('controprova: detrazione sotto 1% esclusa', 'fascia' not in (det['detrazioni_pct'] or {}))

print('\n--- file scritto su disco ---')

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, 'sub', 'blocco.geojson')
    out, sc = G.esporta_geojson(blocco([parcella(ancora=True), parcella(pla='54')]),
                                p, comune='Morcone')
    t('cartella creata se manca', os.path.exists(out), grave=True)

    j = json.load(open(out, encoding='utf-8'))
    t('e un FeatureCollection', j['type'] == 'FeatureCollection', grave=True)
    t('due feature scritte', len(j['features']) == 2)
    t('geometria di tipo Polygon', j['features'][0]['geometry']['type'] == 'Polygon')
    t('coordinate annidate in un anello',
      len(j['features'][0]['geometry']['coordinates']) == 1)
    t('riepilogo ettari nel file', j['properties']['ha_lordi'] == 2.0)
    t('nessun membro crs (deprecato da RFC 7946)', 'crs' not in j, grave=True)

    # CONTROPROVA del riepilogo: se cambia il blocco deve cambiare il totale.
    p2 = os.path.join(d, 'uno.geojson')
    G.esporta_geojson(blocco([parcella()]), p2)
    j2 = json.load(open(p2, encoding='utf-8'))
    t('controprova: blocco diverso -> ettari diversi',
      j2['properties']['ha_lordi'] != j['properties']['ha_lordi'], grave=True)

print('\n--- integrazione con esporta() ---')

from landscout import blocco as B

with tempfile.TemporaryDirectory() as d:
    file, _ = B.esporta(blocco([parcella(ancora=True)]), d, comune='Morcone',
                        satellite=False, verbose=False)
    t('esporta() produce il geojson', 'geojson' in file, f'chiavi={sorted(file)}', grave=True)
    t('il file esiste davvero', os.path.exists(file.get('geojson', '')), grave=True)

# una particella senza geometria deve finire nei RISCHI, non sparire
with tempfile.TemporaryDirectory() as d:
    b = {}
    B.esporta(blocco([parcella(), parcella(pla='999', poly=[])]), d,
              satellite=False, verbose=False, b=b)
    t('geometria mancante segnalata nei rischi',
      any('SENZA geometria' in r for r in b.get('rischi', [])),
      f"rischi={b.get('rischi')}", grave=True)

    b2 = {}
    B.esporta(blocco([parcella()]), d, satellite=False, verbose=False, b=b2)
    t('controprova: nessun rischio geometria se sono tutte valide',
      not any('geometria' in r for r in b2.get('rischi', [])), grave=True)


print('\n--- il buco del 26/07: salvare un blocco perdendo le geometrie ---')

t('geometrie_mancanti le elenca',
  B.geometrie_mancanti(blocco([parcella(), parcella(pla='9', poly=[])])) == ['70/9'],
  grave=True)
t('controprova: blocco integro -> lista vuota',
  B.geometrie_mancanti(blocco([parcella()])) == [])

# la riga esatta che ha causato il danno il 26/07
spogliato = blocco([{k: v for k, v in parcella().items() if k != 'poly'}])
t('riproduce il bug storico (filtro su poly)',
  B.geometrie_mancanti(spogliato) == ['70/276'], grave=True)

with tempfile.TemporaryDirectory() as d:
    p, manc = B.salva_json(blocco([parcella(ancora=True), parcella(pla='54')]),
                           os.path.join(d, 'a', 'blocco.json'), comune='Morcone')
    j = json.load(open(p, encoding='utf-8'))
    t('salva_json conserva le geometrie',
      all('poly' in x for x in j['blocco']['particelle']), grave=True)
    t('salva_json non segnala falsi mancanti', manc == [])
    t('salva_json accetta campi extra', j.get('comune') == 'Morcone')

    p2, manc2 = B.salva_json(spogliato, os.path.join(d, 'b.json'))
    j2 = json.load(open(p2, encoding='utf-8'))
    t('salva_json DENUNCIA le geometrie perse', manc2 == ['70/276'], grave=True)
    t('la denuncia finisce anche nel file',
      j2['particelle_senza_geometria'] == ['70/276'], grave=True)
    # controprova: sul blocco integro il campo non deve accusare nulla
    p3, _ = B.salva_json(blocco([parcella()]), os.path.join(d, 'c.json'))
    t('controprova: blocco integro -> nessuna denuncia nel file',
      json.load(open(p3, encoding='utf-8'))['particelle_senza_geometria'] is None,
      grave=True)

# ---------------------------------------------------------------- esito
print('\n' + '=' * 76)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 76)
sys.exit(1 if GRAVI else 0)
