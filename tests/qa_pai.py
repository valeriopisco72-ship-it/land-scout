# -*- coding: utf-8 -*-
"""QA pai — frane e idraulica dentro il percorso aggregatore.

Fino all'08/08/2026 il PAI era l'unico vincolo BLOCCANTE che `vincoli.feasibility`
non guardava affatto: `engine` sapeva che P3/P4 e' un blocker, ma nessuno riempiva
i campi, e `blocco` costruiva blocchi senza sapere se stavano su una frana.

I due modi di sbagliare qui sono opposti e vanno provati tutti e due:
  - dire "nessuna frana" quando il servizio non ha risposto (falso pulito);
  - escludere mezza provincia contando le aree di attenzione (AA copre il 55%
    del territorio di Morcone e sulle tavole ufficiali non e' un vincolo).

I test girano OFFLINE: la rete la sostituisce una risposta finta. Il 08/08/2026
l'host IdroGEO ha smesso di rispondere a meta' lavoro — motivo in piu' per non
legare la verifica di una regola alla disponibilita' di un server.
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import blocco as B
from landscout import engine as E
from landscout import vincoli as V

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


LA, LO = 42.3392, 13.7446


def anello(la=LA, lo=LO, d=0.001):
    return [(la, lo), (la + d, lo), (la + d, lo + d), (la, lo + d)]


def parcels():
    return [{'id': '70_142', 'lat': LA + 0.0005, 'lon': LO + 0.0005, 'ha': 1.0,
             'anello': anello()}]


def to_xy(lat, lon):
    return (lon * 83000.0, lat * 111132.0)


def risposta(coords, cod=None, crs='EPSG:4326'):
    """Una FeatureCollection finta, nel CRS richiesto."""
    props = {'cod_per_it': cod} if cod is not None else {}
    return json.dumps({'type': 'FeatureCollection',
                       'crs': {'type': 'name', 'properties': {'name': crs}},
                       'numberMatched': 1, 'numberReturned': 1,
                       'features': [{'type': 'Feature', 'properties': props,
                                     'geometry': {'type': 'Polygon',
                                                  'coordinates': [coords]}}]})


VUOTA = json.dumps({'type': 'FeatureCollection', 'features': [],
                    'numberMatched': 0, 'numberReturned': 0})


def con_get(fn):
    """Sostituisce V.get per la durata di una chiamata."""
    vero = V.get
    V.get = fn
    try:
        return V.pai(parcels(), to_xy)
    finally:
        V.get = vero


# GeoJSON standard: (lon, lat)
QUADRATO = [[LO, LA], [LO + 0.002, LA], [LO + 0.002, LA + 0.002], [LO, LA + 0.002], [LO, LA]]

print('\n[1] una frana P4 sotto la particella deve arrivare fino al verdetto')

def get_p4(url, timeout=None):
    return risposta(QUADRATO, cod=4) if 'frane' in url else VUOTA

fr, idr, ok = con_get(get_p4)
t('i 4 layer rispondono -> pai_ok', ok, grave=True)
t('la classe 4 e stata letta', 4 in fr and fr[4] is not None, str(list(fr)), grave=True)

print('\n[2] AA e P1 NON sono vincoli operativi (AA copre meta del Sannio)')

def get_aa(url, timeout=None):
    return risposta(QUADRATO, cod=0) if 'frane' in url else VUOTA

fr0, _, ok0 = con_get(get_aa)
t('AA (classe 0) viene letta come classe 0, non ignorata', 0 in fr0, str(list(fr0)))
s_aa, cl_aa, f_aa = E.score_parcel({'ha': 5, 'slope': 5, 'zps_pct': 0, 'zps_border_m': 9e9,
                                    'pai_fr': 0, 'pai_idr': 0})
t('con AA il terreno NON e bocciato', cl_aa != 'D', f'{cl_aa} {s_aa}', grave=True)
s_p4, cl_p4, _ = E.score_parcel({'ha': 5, 'slope': 5, 'zps_pct': 0, 'zps_border_m': 9e9,
                                 'pai_fr': 4, 'pai_idr': 0})
t('controprova: con P4 e bocciato', cl_p4 == 'D', f'{cl_p4} {s_p4}', grave=True)

print('\n[3] un layer che non risponde NON diventa "nessuna frana"')

def get_rotto(url, timeout=None):
    if 'idraulica_p2' in url:
        raise ConnectionError('Remote end closed connection without response')
    return VUOTA

_, _, ok_rotto = con_get(get_rotto)
t('basta un layer muto su quattro -> NON verificato', ok_rotto is False, grave=True)

def get_tutti_ok(url, timeout=None):
    return VUOTA

_, _, ok_tutti = con_get(get_tutti_ok)
t('controprova: quattro layer che rispondono vuoto -> verificato e pulito',
  ok_tutti is True, grave=True)

print('\n[4] una risposta in coordinate proiettate viene SCARTATA, non riproiettata a caso')

# le stesse coordinate in EPSG:3857 (metri): e' cio' che IdroGEO risponde senza srsName
METRI = [[1641362.3, 5062498.5], [1641562.3, 5062498.5],
         [1641562.3, 5062698.5], [1641362.3, 5062698.5], [1641362.3, 5062498.5]]

def get_3857(url, timeout=None):
    return risposta(METRI, cod=4, crs='EPSG:3857') if 'frane' in url else VUOTA

fr3857, _, _ = con_get(get_3857)
t('feature in metri: scartata, non piazzata dall altra parte del mondo',
  fr3857.get(4) is None, str(fr3857), grave=True)
t('la query dichiara srsName=EPSG:4326',
  "'srsName': 'EPSG:4326'" in open(os.path.join(
      os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
      'landscout', 'vincoli.py'), encoding='utf-8').read(), grave=True)

print('\n[5] il blocco esclude chi sta su una frana, e solo per quello')

p = [{'fg': 70, 'pla': 142, 'ha': 3.0, 'poly': anello(d=0.003)}]
occ = {'70_142': {'verdetto': 'LIBERA', 'pct': 0.0}}

A_ok = B.ammissibilita(p, {'70_142': {'pai_blocker': False, 'pai_fr': 0}}, occ)
t('AA/P1: la particella entra', len(A_ok['ammesse']) == 1, str(A_ok['scarti']), grave=True)

A_no = B.ammissibilita(p, {'70_142': {'pai_blocker': True, 'pai_fr': 4}}, occ)
t('P4: la particella esce', len(A_no['ammesse']) == 0, str(A_no['scarti']), grave=True)
t('e il motivo dice quale classe', any('P4' in k for k in A_no['scarti']),
  str(A_no['scarti']), grave=True)

A_nv = B.ammissibilita(p, {'70_142': {'pai_blocker': None, 'pai_fr': None,
                                      'pai_ok': False}}, occ)
t('PAI non verificato NON esclude (ma il flag viaggia a valle)',
  len(A_nv['ammesse']) == 1, str(A_nv['scarti']))
t('...e il blocco lo DICHIARA nel riepilogo',
  any('PAI' in x for x in A_nv['non_verificati']), str(A_nv['non_verificati']), grave=True)
t('controprova: con il PAI verificato non si inventa una lacuna',
  A_ok['non_verificati'] == [], str(A_ok['non_verificati']), grave=True)

print('\n[6] i campi arrivano al motore di punteggio')

f = V.to_score_fields({'pai_fr': 3, 'pai_idr': 0, 'pai_ok': True})
t('to_score_fields passa la classe frana', f['pai_fr'] == 3, str(f), grave=True)
f2 = V.to_score_fields({'pai_fr': None, 'pai_idr': None, 'pai_ok': False})
t('to_score_fields dichiara il PAI incompleto', f2.get('pai_incompleto') is True, str(f2),
  grave=True)
_, _, flags = E.score_parcel(dict({'ha': 5, 'slope': 5, 'zps_pct': 0,
                                   'zps_border_m': 9e9}, **f2))
t('e il motore lo scrive nei flag',
  any('PAI NON verificato' in x for x in flags), str(flags), grave=True)

print()
print('[T] l interruttore e a TEMPO, non permanente')

# ⚠️ 12/08/2026: l interruttore era permanente per l intero processo. Quel giorno
# `idrogeo.isprambiente.it` non ha risolto per qualche minuto e poi ha ripreso a
# rispondere in 2 secondi: con un interruttore permanente, un blip di DNS a inizio
# scansione avrebbe marcato NON VERIFICATE le frane di TUTTE le particelle per il
# resto del processo — e nessuno se ne sarebbe accorto, perche "non verificato" e
# un esito legittimo. Ora scade.
import time as _time
V.reset_interruttore_pai()
t('parte disinserito', V.stato_interruttore_pai() is None, grave=True)
V._IDROGEO_GIU = ('OSError sul layer frane', _time.time())
st = V.stato_interruttore_pai()
t('dopo lo scatto dichiara motivo e da quanto', st and 'OSError' in st[0] and st[1] >= 0,
  str(st), grave=True)
t('e la pausa e finita, non infinita', 0 < V.PAUSA_IDROGEO_S < 3600,
  str(V.PAUSA_IDROGEO_S), grave=True)
V._IDROGEO_GIU = ('vecchio guasto', _time.time() - V.PAUSA_IDROGEO_S - 1)
st2 = V.stato_interruttore_pai()
t('un guasto piu vecchio della pausa risulta scaduto',
  st2 and st2[1] > V.PAUSA_IDROGEO_S, str(st2), grave=True)
V.reset_interruttore_pai()
t('il reset lo azzera davvero', V.stato_interruttore_pai() is None, grave=True)


print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
