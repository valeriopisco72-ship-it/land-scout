# -*- coding: utf-8 -*-
"""QA prossimita — la pendenza, e la fonte da cui viene.

Il 10/08/2026 e' entrato TINITALY (INGV, DEM nazionale a 10 m con la pendenza
gia' derivata) al posto di SRTM a 30 m campionato sui vertici. Su Fg70/142 a
Morcone la differenza non e' accademica: 10,8% dal vecchio dato canonico contro
13,6% medio e 17,4% massimo dal nuovo — cioe' si passa da "tranquillo" a
"attenzione, con punte oltre il limite".

Qui si prova che: il nodata non diventa mai 0%, una particella non coperta resta
NON verificata, e se il servizio tace si ripiega sull'altra fonte invece di
restituire un risultato vuoto che si legge come "nessun problema".
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import prossimita as PR

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


def part(fg=70, pla=142):
    return {'fg': fg, 'pla': pla,
            'poly': [(42.3392, 13.7446), (42.3399, 13.7446),
                     (42.3399, 13.7455), (42.3392, 13.7455)]}


print('\n[1] la pendenza dal layer a 10 m')

_vero = PR._tinitaly
try:
    PR._tinitaly = lambda la, lo, **k: 12.0
    r = PR.pendenza([part()])
    v = r['particelle']['70_142']
    t('la fonte dichiarata e TINITALY', 'TINITALY' in r['dataset'], r['dataset'], grave=True)
    t('la pendenza e quella del layer', v['pendenza_pct'] == 12.0, str(v))
    t('12% e "attenzione", non "oltre limite"',
      v['attenzione'] and not v['oltre_limite'], str(v), grave=True)

    PR._tinitaly = lambda la, lo, **k: 22.0
    v2 = PR.pendenza([part()])['particelle']['70_142']
    t('controprova: 22% supera il limite', v2['oltre_limite'], str(v2), grave=True)

    # media e massimo: su un fondo in pendenza il massimo e' cio' che costa
    val = iter([5.0, 5.0, 5.0, 5.0, 25.0])
    PR._tinitaly = lambda la, lo, **k: next(val)
    v3 = PR.pendenza([part()])['particelle']['70_142']
    t('media e massimo sono entrambi riportati',
      v3['pendenza_pct'] == 9.0 and v3['pendenza_max_pct'] == 25.0, str(v3), grave=True)

    print('\n[2] cio che il servizio non sa non diventa zero')

    PR._tinitaly = lambda la, lo, **k: None
    r4 = PR.pendenza_tinitaly([part()])
    v4 = r4['particelle']['70_142']
    t('nessun campione -> NON verificata, non 0%',
      v4['verificata'] is False and v4['pendenza_pct'] is None, str(v4), grave=True)
    t('e il conteggio lo dichiara', r4['n_non_verificate'] == 1, str(r4))
finally:
    PR._tinitaly = _vero

print('\n[3] il nodata del raster non passa per un valore')

import json
import urllib.parse
import urllib.request


class _Risposta:
    def __init__(self, testo):
        self.testo = testo

    def read(self):
        return self.testo.encode()


_urlopen = urllib.request.urlopen
try:
    for grezzo, atteso, nome in (
            ('GRAY_INDEX = -9999.0', None, 'nodata negativo'),
            ('GRAY_INDEX = 32767', None, 'nodata fuori scala'),
            ('Results for FeatureType: nothing', None, 'risposta senza valore'),
            ('GRAY_INDEX = 7.5', 7.5, 'valore buono')):
        urllib.request.urlopen = lambda *a, **k: _Risposta(grezzo)
        got = PR._tinitaly(42.34, 13.74)
        t(f'{nome} -> {atteso}', got == atteso, f'ottenuto {got}', grave=True)
finally:
    urllib.request.urlopen = _urlopen

print('\n[4] se TINITALY tace, si ripiega — non si restituisce il vuoto')

chiamato = {'opentopo': False}
_vt, _vq = PR._tinitaly, urllib.request.urlopen
try:
    PR._tinitaly = lambda la, lo, **k: None

    def _finto(req, *a, **k):
        chiamato['opentopo'] = True
        return _Risposta('{"results": [{"elevation": 400.0}, {"elevation": 405.0}, '
                         '{"elevation": 410.0}, {"elevation": 402.0}, {"elevation": 401.0}]}')
    urllib.request.urlopen = _finto
    r5 = PR.pendenza([part()], timeout=5)
    t('la seconda fonte viene interrogata', chiamato['opentopo'], grave=True)
    t('e la fonte usata e dichiarata (non piu TINITALY)',
      'TINITALY' not in r5['dataset'], r5['dataset'], grave=True)
finally:
    PR._tinitaly, urllib.request.urlopen = _vt, _vq

print('\n[5] un DEM che risponde a meta non e una pendenza misurata (28/09/2026)')

# Le quote si chiedono a blocchi di `punti_max` punti: una particella puo' stare a
# cavallo di due blocchi. Se il secondo fallisce le restano i punti del primo — magari
# tutti dal lato piano — e la pendenza calcolata su quelli usciva "verificata", con il
# dislivello sottostimato: un fondo al 20% poteva risultare al 3%.
chiamate = {'n': 0}


def _dem_a_meta(req, *a, **k):
    chiamate['n'] += 1
    url = req.full_url if hasattr(req, 'full_url') else str(req)
    n = urllib.parse.unquote(url.split('locations=')[1]).count('|') + 1
    if chiamate['n'] == 2:
        raise OSError('opentopodata: 429 Too Many Requests')
    return _Risposta(json.dumps({'results': [{'elevation': 400.0 + i} for i in range(n)]}))


def _dem_tutto(req, *a, **k):
    url = req.full_url if hasattr(req, 'full_url') else str(req)
    n = urllib.parse.unquote(url.split('locations=')[1]).count('|') + 1
    return _Risposta(json.dumps({'results': [{'elevation': 400.0 + i} for i in range(n)]}))


_vq, _vs = urllib.request.urlopen, PR.time.sleep
try:
    PR.time.sleep = lambda *_a, **_k: None
    urllib.request.urlopen = _dem_a_meta
    # part() ha 4 vertici + il centroide = 5 punti: con punti_max=4 la prima
    # particella sta per 4/5 nel primo blocco e per 1/5 nel secondo
    r6 = PR.pendenza([part(70, 1), part(70, 2)], fonte='opentopo', punti_max=4)
    v6 = r6['particelle']['70_1']
    t('particella a cavallo del blocco fallito: NON verificata',
      v6['verificata'] is False and v6.get('pendenza_pct') is None, str(v6), grave=True)
    urllib.request.urlopen = _dem_tutto
    r7 = PR.pendenza([part(70, 1), part(70, 2)], fonte='opentopo', punti_max=4)
    t('controprova: DEM completo -> verificata',
      r7['particelle']['70_1']['verificata'] is True, str(r7['particelle']['70_1']), grave=True)
finally:
    urllib.request.urlopen, PR.time.sleep = _vq, _vs

print('\n[6] un servizio appeso non ferma tutto: c e un budget di tempo TOTALE (28/09/2026)')

# Il timeout e' per richiesta: 5 campioni a particella, in fila. Con TINITALY appeso
# (risponde dopo il timeout, non rifiuta) dieci particelle costavano ~1.000 s prima
# ancora di provare l'altra fonte — e il dossier e' una pagina web.
orologio = {'t': 1000.0}
chiamate_t = {'n': 0}


def _tini_lento(la, lo, **k):
    chiamate_t['n'] += 1
    orologio['t'] += 6.0            # ogni richiesta "costa" 6 secondi
    return 5.0


_vt, _vtime = PR._tinitaly, PR.time.time
try:
    PR._tinitaly = _tini_lento
    PR.time.time = lambda: orologio['t']
    r8 = PR.pendenza_tinitaly([part(70, 1), part(70, 2), part(70, 3)], budget_s=10)
    t('budget esaurito: le chiamate si fermano (non 15)', chiamate_t['n'] <= 3,
      str(chiamate_t['n']), grave=True)
    t('e le particelle non misurate restano NON verificate, non 0% ne mezze',
      all(v['verificata'] is False for v in r8['particelle'].values()),
      str(r8['particelle']), grave=True)
    chiamate_t['n'] = 0
    r9 = PR.pendenza_tinitaly([part(70, 1), part(70, 2), part(70, 3)])
    t('controprova: senza budget si misura tutto', chiamate_t['n'] == 15 and
      r9['n_verificate'] == 3, f"{chiamate_t['n']} {r9['n_verificate']}", grave=True)
finally:
    PR._tinitaly, PR.time.time = _vt, _vtime

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
