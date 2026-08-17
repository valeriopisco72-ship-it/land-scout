# -*- coding: utf-8 -*-
"""QA fuoco — aree percorse dal fuoco, e i due modi di sbagliare.

Il primo e' ovvio: non vedere un incendio che c'e'. Il secondo e' quello che
questo modulo rischia davvero: **far passare un esito negativo per un via
libera**. EFFIS vede da ~30 ettari in su ed e' un'osservazione satellitare; il
vincolo della L. 353/2000 nasce dal catasto incendi COMUNALE. "Nessun incendio
EFFIS" e "nessun incendio" non sono la stessa frase, e il modulo non deve mai
lasciar credere il contrario.

Offline: la rete la sostituisce una funzione finta, cosi' i test valgono anche
il giorno che il servizio e' giu'.
"""
import io
import os
import sys
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import engine as E
from landscout import fuoco as F

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


OGGI = date(2026, 8, 10)
P = [{'fg': '70', 'pla': '136', 'lat': 42.339, 'lon': 13.744},
     {'fg': '70', 'pla': '137', 'lat': 42.340, 'lon': 13.745}]


def finto(incendi_per_anno):
    """incendi_per_anno: {anno: [dict]} -> funzione compatibile con _gfi.

    La firma rispecchia quella vera: una sola chiamata per TUTTA la finestra."""
    def g(lat, lon, da, a, d=0.004, timeout=60):
        out = []
        for anno, righe in incendi_per_anno.items():
            out += [dict(x, anno=anno) for x in righe]
        return out
    return g


INC = {'id': '1', 'data': '2019-08-12 13:00:00', 'comune': 'Morcone',
       'provincia': 'Benevento', 'area_ha': 210.0, 'quota_agricola_pct': 31.0}

print('\n[1] un incendio nella finestra viene trovato, e con le date giuste')

R = F.storico(P, anni=15, oggi=OGGI, _gfi_fn=finto({2019: [INC]}))
v = R['particelle']['70_136']
t('percorsa dal fuoco', v['percorsa_fuoco'] is True, str(v), grave=True)
t('anno letto correttamente', v['ultimo_anno'] == 2019, str(v['ultimo_anno']))
t('divieto cambio destinazione 15 anni -> 2034',
  v['divieto_destinazione_fino'] == 2034, str(v), grave=True)
t('divieto edificazione 10 anni -> 2029',
  v['divieto_edificazione_fino'] == 2029, str(v), grave=True)
t('il rischio cita la legge e la scadenza',
  any('353/2000' in x and '2034' in x for x in F.rischi(R)), str(F.rischi(R)), grave=True)

print('\n[2] fuori finestra non deve comparire')

R2 = F.storico(P, anni=5, oggi=OGGI, _gfi_fn=finto({2019: [INC]}))
t('con finestra 5 anni il 2019 e fuori dagli anni esaminati',
  2019 not in R2['anni_esaminati'], str(R2['anni_esaminati']), grave=True)
t('e la particella risulta non colpita',
  R2['particelle']['70_136']['percorsa_fuoco'] is False, str(R2['particelle']['70_136']))
t('gli anni esaminati sono esattamente la finestra chiesta',
  R2['anni_esaminati'] == [2022, 2023, 2024, 2025, 2026], str(R2['anni_esaminati']))

print('\n[3] il servizio muto NON diventa "nessun incendio"')


def rotto(lat, lon, da, a, d=0.004, timeout=60):
    raise F.EffisNonDisponibile('servizio non raggiungibile')


R3 = F.storico(P, anni=3, oggi=OGGI, _gfi_fn=rotto)
v3 = R3['particelle']['70_136']
t('verificato = False', v3['verificato'] is False, str(v3), grave=True)
t('percorsa_fuoco = None, non False', v3['percorsa_fuoco'] is None, str(v3), grave=True)
t('gli anni muti sono elencati', R3['anni_non_verificati'] == [2024, 2025, 2026],
  str(R3['anni_non_verificati']))
t('e finisce nei rischi', any('NON verificato' in x for x in F.rischi(R3)),
  str(F.rischi(R3)), grave=True)


def mezzo(lat, lon, da, a, d=0.004, timeout=60):
    raise F.EffisNonDisponibile('finestra non interrogabile')


R4 = F.storico(P, anni=3, oggi=OGGI, _gfi_fn=mezzo)
t('finestra non interrogabile -> particella non verificata',
  R4['particelle']['70_136']['verificato'] is False, str(R4['particelle']['70_136']),
  grave=True)

print('\n[4] cio che il modulo non deve promettere')

R5 = F.storico(P, anni=3, oggi=OGGI, _gfi_fn=finto({}))
t('nessun incendio trovato -> verificato, ma...',
  R5['particelle']['70_136']['verificato'] and
  R5['particelle']['70_136']['percorsa_fuoco'] is False)
t('...il rischio dice comunque di chiedere il catasto incendi comunale',
  any('comunale' in x for x in F.rischi(R5)), str(F.rischi(R5)), grave=True)
t('la nota dichiara la soglia dei 30 ha', '30 ha' in R5['nota'], grave=True)
t('e che il perimetro giuridico e quello del Comune',
  'COMUNALE' in R5['nota'], grave=True)

print('\n[5] il collegamento con il punteggio')

A = {'ammesse': [{'fg': '70', 'pla': '136', 'ha': 2.0, 'netti': 2.0},
                 {'fg': '70', 'pla': '999', 'ha': 1.0, 'netti': 1.0}],
     'scarti': {}, 'ha_pool': 3.0, 'ha_ammessi_lordi': 3.0, 'ha_ammessi_netti': 3.0}
A2 = F.applica(A, R)
t('la particella colpita viene marcata',
  A2['ammesse'][0].get('percorsa_fuoco') is True, str(A2['ammesse'][0]), grave=True)
t('con l anno e la scadenza del divieto',
  A2['ammesse'][0].get('fuoco_anno') == 2019 and
  A2['ammesse'][0].get('fuoco_divieto_fino') == 2034, str(A2['ammesse'][0]))
t('una particella non valutata NON diventa pulita per omissione',
  'percorsa_fuoco' not in A2['ammesse'][1], str(A2['ammesse'][1]), grave=True)
t('applica non tocca gli ettari (decide ammissibilita, non questo modulo)',
  A2['ha_ammessi_netti'] == 3.0)
_, cl, fl = E.score_parcel({'ha': 5, 'slope': 5, 'zps_pct': 0, 'zps_border_m': 9e9,
                            'pai_fr': -1, 'pai_idr': 0, 'percorsa_fuoco': True})
t('engine tratta percorsa_fuoco come blocker', cl == 'D', f'{cl} {fl}', grave=True)

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
