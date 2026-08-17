# -*- coding: utf-8 -*-
"""QA idonee — il lato positivo: dove l'iter e' agevolato.

Il rischio qui non e' il crash, e' l'OTTIMISMO: dichiarare idonea una particella
che non lo e' fa perdere mesi a chi ci costruisce sopra un piano. Percio' quasi
ogni verifica ha la sua controprova nel verso opposto, e il caso "il servizio non
risponde" deve dare un errore, non un elenco vuoto che si legge come "nessuna
agevolazione".
"""
import io
import math
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import engine as E
from landscout import idonee as I

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


# geometria: a 42.35 di latitudine 0.001 gradi di lat ~= 111 m, di lon ~= 83 m
LA, LO = 42.350, 13.760


def quadrato(la, lo, lato_gradi=0.0005):
    return [(la, lo), (la + lato_gradi, lo), (la + lato_gradi, lo + lato_gradi),
            (la, lo + lato_gradi)]


def particella(fg, pla, la=LA, lo=LO):
    return {'fg': fg, 'pla': pla, 'ha': 2.0, 'netti': 2.0, 'poly': quadrato(la, lo)}


def innesco_finto(**per_tipo):
    base = {k: [] for k in I.TAG_INNESCO}
    base.update(per_tipo)
    return {'per_tipo': base, 'bbox': None,
            'trovati': {k: len(v) for k, v in base.items()}, 'nota': 'finto'}


def zona(tipo, la, lo, nome='Z', lato=0.002):
    return {tipo: [{'nome': nome, 'anello': quadrato(la, lo, lato), 'dismesso': False}]}


print('\n[1] la distanza dalla zona industriale (500 m, art. 20 c.8 lett. c-ter)')

# zona industriale che parte 0.002 gradi di longitudine a est (~166 m)
p = [particella(70, 100)]
R = I.valuta(p, innesco_finto(**zona('industriale', LA, LO + 0.0025)))
v = R['particelle']['70_100']
t('particella a ~170 m da zona industriale: CANDIDATA', v['candidata'], str(v), grave=True)
t('il criterio citato e la norma, non un aggettivo',
  any('c-ter' in c['norma'] for c in v['criteri']), str(v['criteri']))

# la stessa zona spostata a ~1,2 km: fuori
R2 = I.valuta(p, innesco_finto(**zona('industriale', LA, LO + 0.015)))
t('controprova: a ~1,2 km NON e candidata',
  not R2['particelle']['70_100']['candidata'],
  str(R2['particelle']['70_100']), grave=True)
t('la distanza misurata viene comunque dichiarata',
  R2['particelle']['70_100']['distanze_m'].get('industriale', 0) > 500,
  str(R2['particelle']['70_100']['distanze_m']))

# la soglia e' quella della norma, non una a caso
R3 = I.valuta(p, innesco_finto(**zona('industriale', LA, LO + 0.015)), d_industriale=2000.0)
t('con soglia piu larga la stessa particella entra (la soglia MORDE)',
  R3['particelle']['70_100']['candidata'], grave=True)


print('\n[2] cava e discarica: valgono se ci sei DENTRO, non se sono vicine')

R4 = I.valuta(p, innesco_finto(**zona('cava', LA - 0.0005, LO - 0.0005, lato=0.002)))
t('particella dentro una cava: candidata',
  R4['particelle']['70_100']['candidata'], str(R4['particelle']['70_100']), grave=True)
R5 = I.valuta(p, innesco_finto(**zona('cava', LA, LO + 0.003)))
t('controprova: una cava a 250 m NON rende idonea la particella',
  not R5['particelle']['70_100']['candidata'],
  str(R5['particelle']['70_100']), grave=True)


print('\n[3] Overpass muto: errore, non "nessuna agevolazione"')

_vero = I._overpass
try:
    def _rotto(q, timeout=120, tentativi=2):
        raise I.InnescoNonDisponibile('Overpass non raggiunto (prova)')
    I._overpass = _rotto
    try:
        I.innesco(p)
        alzato = False
    except I.InnescoNonDisponibile:
        alzato = True
    t('servizio muto -> InnescoNonDisponibile', alzato, grave=True)
finally:
    I._overpass = _vero

try:
    I.innesco([])
    alzato2 = False
except ValueError:
    alzato2 = True
t('elenco vuoto -> ValueError', alzato2)


print('\n[4] il collegamento con il punteggio (finora il campo non lo riempiva nessuno)')

A = {'ammesse': [particella(70, 100), particella(70, 101)],
     'scarti': {}, 'ha_pool': 4.0, 'ha_ammessi_lordi': 4.0, 'ha_ammessi_netti': 4.0}
R6 = I.valuta(A['ammesse'], innesco_finto(**zona('industriale', LA, LO + 0.0025)))
A2 = I.applica(A, R6)
t('applica scrive area_idonea sulle candidate',
  all(a.get('area_idonea') for a in A2['ammesse']), str(A2['ammesse'][0]), grave=True)
t('applica NON tocca gli ettari (e un bonus di iter, non di superficie)',
  A2['ha_ammessi_netti'] == 4.0 and all(a['netti'] == 2.0 for a in A2['ammesse']),
  grave=True)

base = {'ha': 5.0, 'slope': 5.0, 'zps_pct': 0.0, 'zps_border_m': 9e9,
        'd_se_m': 3000, 'd_150kv_m': 2000, 'pai_fr': -1, 'pai_idr': 0}
s_no, _, _ = E.score_parcel(dict(base))
s_si, _, f_si = E.score_parcel(dict(base, area_idonea=True))
t('area_idonea alza davvero il punteggio', s_si > s_no, f'{s_no} -> {s_si}', grave=True)
t("e lo dice nei flag", any('IDONEA' in x for x in f_si), str(f_si))


print('\n[5] cio che il modulo NON deve fare')

t('non dichiara mai una NON idoneita (dipende dalla legge regionale)',
  not any('area_non_idonea' in a for a in A2['ammesse']), grave=True)
t('la nota dice che sono CANDIDATE, non idonee',
  'CANDIDATE' in R6['nota'] and 'GSE' in R6['nota'], grave=True)
t('una particella non valutata non diventa idonea per omissione',
  I.applica({'ammesse': [particella(99, 999)]},
            {'particelle': {}, 'nota': 'x'})['ammesse'][0].get('area_idonea') is None,
  grave=True)


print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
