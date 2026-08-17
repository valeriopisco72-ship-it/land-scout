# -*- coding: utf-8 -*-
"""QA prezzo — quanto offrire, e a chi.

Il rischio qui non e' un errore di calcolo: e' un PARAMETRO INVENTATO che
produce un verdetto falso. La prima versione fissava a mano la quota di valore
RTB destinata alla terra e concludeva "il deal non regge" — su un numero che
non veniva da nessuna fonte. Questi test difendono il verso del ragionamento.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from landscout import prezzo as P

OK = FAIL = 0
GRAVI = []


def t(nome, cond, dett='', grave=False):
    global OK, FAIL
    if cond:
        OK += 1
        print(f'  ok   {nome}')
    else:
        FAIL += 1
        print(f'  FAIL {nome} {dett}')
        if grave:
            GRAVI.append(nome)


BLK = {'ha_acquisti': 10.0, 'ha_installabile': 10.0, 'particelle': [
    {'fg': '1', 'pla': 'mia', 'netti': 5.0, 'ancora': True},
    {'fg': '1', 'pla': 'a', 'netti': 6.0, 'ancora': False},
    {'fg': '1', 'pla': 'b', 'netti': 4.0, 'ancora': False},
]}

print('=' * 76)
print('  QA PREZZO — pavimento, offerta, sostenibilita, uniformita')
print('=' * 76)

# ------------------------------------------------------------------ 1. scala
print('\n[1] la scala dei valori deve essere monotona')
pl = P.piano(BLK, prov='BN', mwp=5.0)
t('pavimento < minimo credibile',
  pl['pavimento']['eur_ha'] < pl['minimo_credibile_eur_ha'], grave=True)
t('minimo credibile <= offerta',
  pl['minimo_credibile_eur_ha'] <= pl['offerta_eur_ha'], grave=True)
t("nessuno cede sotto il valore agricolo: l'offerta lo supera sempre",
  pl['offerta_eur_ha'] > pl['pavimento']['eur_ha'], grave=True)

# provincia senza VAM: pavimento non verificato, e va DETTO
pv = P.pavimento_eur_ha('ZZ')
t('provincia senza VAM -> pavimento non verificato',
  pv['verificato'] is False and pv['eur_ha'] is None, grave=True)
plz = P.piano(BLK, prov='ZZ', mwp=5.0)
t('senza pavimento il piano avvisa invece di inventare',
  any('NON verificato' in a for a in plz['avvisi']), grave=True)
t('senza pavimento ricade sul mercato, non su zero',
  plz['offerta_eur_ha'] == plz['mercato_eur_ha'], grave=True)

# ------------------------------------------------------------------ 2. densita
print('\n[2] sostenibilita: il verso del ragionamento')
# Stesso prezzo per ettaro, densita' diverse: la quota di RTB assorbita deve
# scendere quando la densita' sale. E' il cuore del modulo — se questo fallisce,
# il modello sta dicendo che la terra costa troppo invece che il progetto rende poco.
s_bassa = P.sostenibilita(37_500, 0.35)
s_alta = P.sostenibilita(37_500, 0.75)
t('a parita di prezzo, piu MWp/ha = quota di RTB minore',
  s_alta['quota_rtb'] < s_bassa['quota_rtb'],
  f"{s_bassa['quota_rtb']} vs {s_alta['quota_rtb']}", grave=True)
t('densita bassa fa scattare l allarme', s_bassa['allarme'], grave=True)

# ⚠ Scoperta da questo stesso test: a 37.500 EUR/ha l'allarme scatta anche a
# 0,75 MWp/ha (45%), cioe' alla densita' tipica del FV a terra. Non e' un bug —
# e' il messaggio: a QUEL prezzo della terra, la quota di RTB resta alta per
# qualunque densita' realistica. La controprova va quindi fatta abbassando il
# prezzo, che e' l'altra leva vera.
t('a parita di densita, un prezzo piu basso spegne l allarme (controprova)',
  not P.sostenibilita(12_000, 0.75)['allarme'],
  f"{P.sostenibilita(12_000, 0.75)}", grave=True)
t('a 37.500 EUR/ha l allarme scatta anche a densita da FV a terra',
  s_alta['allarme'], 'e questo E il risultato, non un difetto')
t('senza densita non si inventa una quota',
  P.sostenibilita(37_500, None) is None, grave=True)

# il messaggio deve puntare alla DENSITA, non al prezzo della terra
pl2 = P.piano(BLK, prov='BN', mwp=3.5)     # 0,35 MWp/ha su 10 ha installabili
t('l avviso incolpa la densita, non il prezzo della terra',
  any('DENSITA' in a for a in pl2['avvisi']), f"{pl2['avvisi']}", grave=True)

# ------------------------------------------------------------------ 3. canone
print('\n[3] canone e prezzo non vanno confusi')
c = P.canone_equivalente(37_500)
t('il canone annuo e molto minore del prezzo',
  c['canone_annuo_eur_ha'] < 37_500 / 10, f"{c['canone_annuo_eur_ha']}")
t('30 anni al 6% -> fattore ~13,76',
  abs(37_500 / c['canone_annuo_eur_ha'] - 13.76) < 0.1,
  f"fattore {37_500/c['canone_annuo_eur_ha']:.2f}")
t('canone di un prezzo maggiore e maggiore',
  P.canone_equivalente(50_000)['canone_annuo_eur_ha'] > c['canone_annuo_eur_ha'])

# ------------------------------------------------------------------ 4. a chi
print('\n[4] si prezza solo cio che NON e gia tuo')
CTR = {'controparti': [
    {'nome': 'IO STESSO', 'ha_controllati': 5.0, 'n_particelle': 1,
     'quota_blocco_pct': 33.0, 'solo_diritti_deboli': False,
     'dettaglio': [{'fg': '1', 'pla': 'mia', 'ha_quota': 5.0}]},
    {'nome': 'VICINO GRANDE', 'ha_controllati': 6.0, 'n_particelle': 1,
     'quota_blocco_pct': 40.0, 'solo_diritti_deboli': False,
     'dettaglio': [{'fg': '1', 'pla': 'a', 'ha_quota': 6.0}]},
    {'nome': 'VICINO PICCOLO', 'ha_controllati': 4.0, 'n_particelle': 1,
     'quota_blocco_pct': 27.0, 'solo_diritti_deboli': False,
     'dettaglio': [{'fg': '1', 'pla': 'b', 'ha_quota': 4.0}]},
]}
pc = P.piano(BLK, controparti=CTR, prov='BN', mwp=5.0)
nomi = [r['chi'] for r in pc['righe']]
t('la terra gia tua NON entra nel piano di offerta',
  'IO STESSO' not in nomi, f'{nomi}', grave=True)
t('i vicini ci sono tutti', set(nomi) == {'VICINO GRANDE', 'VICINO PICCOLO'}, f'{nomi}')
t('esborso = offerta x ettari DA ACQUISIRE',
  abs(pc['totale_offerto_eur'] - pc['offerta_eur_ha'] * 10.0) < 2,
  f"{pc['totale_offerto_eur']}", grave=True)
t('il pivotale e segnalato', any(r['pivotale'] for r in pc['righe']), grave=True)
t('senza visure il piano e per particella e lo dichiara',
  'particella' in P.piano(BLK, prov='BN', mwp=5.0)['per'], grave=True)

# ------------------------------------------------------------------ 5. uniformita
print('\n[5] uniformita del prezzo')
eur_ha = {round(r['offerta_eur'] / r['ha']) for r in pc['righe'] if r['ha']}
t('lo stesso EUR/ha per tutti, pivotale incluso', len(eur_ha) == 1, f'{eur_ha}', grave=True)
t('la regola e scritta nell output, non solo nel codice',
  'ORDINE delle telefonate' in pc['regola_uniformita'], grave=True)
t('la leva si usa sull ordine: il pivotale e in cima alla lista',
  pc['righe'][0]['pivotale'], grave=True)

print('\n[T] il TETTO: quanto il progetto puo pagare in tutto')
# `piano` diceva quanto offrire partendo dal basso (VAM x opzionalita) e non
# diceva mai quanto il progetto regge in totale: quel conto stava in offerta.py,
# scritto la stessa sera e rimasto senza chiamanti. Ora sono composti.
pt = P.piano(BLK, prov='BN', mwp=5.0)
t('il piano porta con se il monte suolo sostenibile',
  pt.get('tetto') and pt['tetto']['monte_suolo_eur'][1] > 0, str(pt.get('tetto')), grave=True)
t('il tetto sconta il rischio autorizzativo (p_auth)', pt['tetto']['p_auth'] < 1.0)
pt3 = P.piano(BLK, prov='BN', mwp=5.0, criticita=4)
t('una provincia satura ABBASSA il tetto',
  pt3['tetto']['monte_suolo_eur'][1] < pt['tetto']['monte_suolo_eur'][1],
  f"{pt3['tetto']['monte_suolo_eur']} vs {pt['tetto']['monte_suolo_eur']}", grave=True)
t('e il motivo dello sconto e scritto',
  any('satur' in m for m in pt3['tetto']['motivi_sconto']), str(pt3['tetto']['motivi_sconto']))
caro = P.piano(BLK, prov='BN', mwp=5.0, eur_ha=500_000)
t('un prezzo sopra il monte suolo produce un AVVISO, non un silenzio',
  any('SUPERA il monte suolo' in a for a in caro['avvisi']), str(caro['avvisi']), grave=True)
# controprova: lo stesso prezzo su un progetto abbastanza grande da sostenerlo.
# Sul blocco di prova a 5 MWp l'avviso scatta ED E' GIUSTO — 375.000 EUR di terra
# non stanno in piedi su 5 MWp — quindi la controprova va fatta alzando la taglia,
# non abbassando il prezzo: e' proprio il punto del modulo.
grande = P.piano(BLK, prov='BN', mwp=60.0)
t('controprova: con un progetto capiente lo stesso prezzo NON allarma',
  not any('SUPERA il monte suolo' in a for a in grande['avvisi']), str(grande['avvisi']),
  grave=True)
t('gli avvisi restano leggibili (niente virgole trasformate in punti)',
  all('EUR. gia' not in a for a in caro['avvisi']), str(caro['avvisi'])[:120], grave=True)
t('senza MWp non si inventa un tetto', P.piano(BLK, prov='BN')['tetto'] is None, grave=True)

print('\n' + '=' * 76)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 76)
sys.exit(1 if GRAVI else 0)
