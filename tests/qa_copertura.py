# -*- coding: utf-8 -*-
"""QA copertura — il blocco che contiene TUTTA la terra di famiglia.

`cresci_migliore` risponde alla domanda del developer ("dammi N ettari
contigui"); questa risponde a quella del proprietario ("voglio vendere la MIA
terra"). Su Morcone la differenza e' misurata: il blocco da 35 ha piu' facile da
comporre conteneva 2,50 ha di famiglia su 9,88 disponibili.

I modi di sbagliare, tutti provati con la controprova:
  1. lasciare fuori un'ancora e non dirlo;
  2. costruire un ponte assurdo — dieci particelle di estranei per collegare
     mezzo ettaro — invece di ammettere che servono due blocchi;
  3. spezzare in due quando bastava una particella per unire.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import blocco as B

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


def A_da(netti):
    """Particelle finte: gli indici sono quelli della lista."""
    return {'ammesse': [{'fg': 1, 'pla': i, 'ha': h, 'netti': h, 'poly': [(41.0, 14.0)] * 4}
                        for i, h in enumerate(netti)],
            'scarti': {}, 'ha_pool': sum(netti),
            'ha_ammessi_lordi': sum(netti), 'ha_ammessi_netti': sum(netti)}


def catena(n):
    """0-1-2-...-n: adiacenza a catena."""
    return {i: {j for j in (i - 1, i + 1) if 0 <= j < n} for i in range(n)}


print('\n[1] due ancore vicine: un blocco solo, col ponte minimo')

# 0(anc) - 1 - 2(anc) : una sola particella di terzi fa da ponte
A = A_da([2.0, 0.5, 3.0])
R = B.copri_ancore(A, catena(3), [0, 2])
t('un blocco solo', R['n_blocchi'] == 1, str(R['n_blocchi']), grave=True)
b = R['blocchi'][0]
t('contiene ENTRAMBE le ancore', b['n_ancore'] == 2, str(b), grave=True)
t('e la particella di ponte', b['n'] == 3, str(b['n']))
t('il ponte e dichiarato', b['ponte_particelle'] == 1, str(b['ponte_particelle']))
t('gli ettari tuoi sono solo quelli delle ancore', b['ha_ancore'] == 5.0, str(b))
t('nessuna ancora resta scoperta',
  R['ancore_coperte'] == R['ancore_totali'] == 2, str(R), grave=True)

print('\n[2] ancore lontane: meglio due blocchi che un ponte assurdo')

# 0(anc) - 1 - 2 - 3 - 4 - 5(anc): cinque particelle di terzi per unirle
A2 = A_da([2.0, 0.3, 0.3, 0.3, 0.3, 2.0])
R2 = B.copri_ancore(A2, catena(6), [0, 5], max_ponte=2)
t('con max_ponte=2 si spezza in due blocchi', R2['n_blocchi'] == 2, str(R2['n_blocchi']),
  grave=True)
t('ma TUTTE le ancore restano coperte', R2['ancore_coperte'] == 2, str(R2), grave=True)
t('e il motivo della separazione e scritto',
  any('ponte' in x for x in R2['note']), str(R2['note']), grave=True)
R3 = B.copri_ancore(A2, catena(6), [0, 5], max_ponte=None)
t('controprova: senza tetto al ponte si unisce', R3['n_blocchi'] == 1, str(R3['n_blocchi']),
  grave=True)
t('e il ponte costa 4 particelle di terzi',
  R3['blocchi'][0]['ponte_particelle'] == 4, str(R3['blocchi'][0]['ponte_particelle']))

print('\n[3] il cammino sceglie il MINOR NUMERO DI FIRME, non i metri')

# 0(anc) e 3(anc); due strade: 0-1-3 (una particella di terzi) oppure
# 0-2a-2b-3 (due). Deve scegliere la prima anche se la seconda ha piu ettari.
A4 = A_da([2.0, 0.1, 5.0, 5.0, 2.0])
adj4 = {0: {1, 2}, 1: {0, 4}, 2: {0, 3}, 3: {2, 4}, 4: {1, 3}}
R4 = B.copri_ancore(A4, adj4, [0, 4])
b4 = R4['blocchi'][0]
t('collega con una sola particella di terzi', b4['ponte_particelle'] == 1,
  str(b4['ponte_particelle']), grave=True)
t('e sceglie quella piccola: contano le firme, non gli ettari',
  b4['n'] == 3, str(b4['n']), grave=True)

print('\n[4] ancore in componenti diverse: due blocchi, per forza')

A5 = A_da([2.0, 1.0, 3.0, 1.0])
adj5 = {0: {1}, 1: {0}, 2: {3}, 3: {2}}      # due isole
R5 = B.copri_ancore(A5, adj5, [0, 2])
t('due componenti -> due blocchi', R5['n_blocchi'] == 2, str(R5['n_blocchi']), grave=True)
t('entrambe le ancore coperte', R5['ancore_coperte'] == 2, str(R5), grave=True)
t('il blocco piu grande viene per primo',
  R5['blocchi'][0]['ha_netti'] >= R5['blocchi'][1]['ha_netti'], str(R5['blocchi']))

print('\n[5] casi degeneri')

A6 = A_da([2.0, 1.0])
R6 = B.copri_ancore(A6, catena(2), [0])
t('una sola ancora: un blocco con quella e basta',
  R6['n_blocchi'] == 1 and R6['blocchi'][0]['n'] == 1, str(R6['blocchi'][0]), grave=True)
t('nessun ponte inventato', R6['ponti'] == 0, str(R6['ponti']))
try:
    B.copri_ancore(A6, catena(2), [])
    alzato = False
except ValueError:
    alzato = True
t('senza ancore alza: la funzione non ha senso senza terra propria', alzato, grave=True)

print('\n[6] quello che distingue questa funzione da cresci_migliore')

# quattro ancore piccole sparse + una grande estranea attaccata a una sola:
# cresci_migliore andrebbe sulla grande, copri_ancore deve prenderle tutte e quattro
A7 = A_da([0.5, 0.5, 0.5, 0.5, 20.0])
adj7 = {0: {1}, 1: {0, 2}, 2: {1, 3}, 3: {2, 4}, 4: {3}}
R7 = B.copri_ancore(A7, adj7, [0, 1, 2, 3])
b7 = R7['blocchi'][0]
t('prende tutte e quattro le ancore', b7['n_ancore'] == 4, str(b7), grave=True)
t('e NON si porta dietro la particella grande di estranei',
  b7['n'] == 4 and b7['n_acquisti'] == 0, str(b7), grave=True)
sel, tot = B.cresci(A7, adj7, 3, 20.0, ancore={0, 1, 2, 3})
t('controprova: cresci() a target ettari ci va invece dentro',
  4 in sel, str(sel), grave=True)
t('il riepilogo si stampa', 'COPERTURA' in B.print_copertura(R7))

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
