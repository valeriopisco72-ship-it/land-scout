# -*- coding: utf-8 -*-
"""QA teaser — la pagina che esce dallo studio.

E' l'unico output che finisce in mano a terzi, quindi i due errori da impedire
non sono estetici:
  1. **far uscire un nome.** Le controparti sono dati personali: un teaser gira
     per mail e finisce in cartelle che non controlli;
  2. **tacere le lacune.** Un developer che scopre da solo che il PAI non era
     stato guardato non pensa "manca un dato", pensa "questo materiale non e'
     affidabile" — e la seconda cosa costa piu' della prima.
Piu' il classico: riempire un buco con un numero plausibile invece di "n.d.".
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import teaser as TS
from landscout import trattativa as TR

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


D = {
    'comune': 'Morcone',
    'blocco': {'titolo': 'blocco 20,2 ha netti — 29 particelle', 'ha_netti': 20.19,
               'ha_lordi': 22.4, 'n': 29, 'n_acquisti': 16, 'ha_ancore': 5.39,
               'particelle': []},
    'bancabilita': {'mwp_stimati': [5.6, 8.9], 'd_se_m': 4100,
                    'punti_forti': ['coda FV vuota al nodo'],
                    'rischi': ['rischio ostaggio: una particella vale il 16% del blocco',
                               'quadro proprietario SCONOSCIUTO: nessuna visura caricata']},
    'installabile': {'ha_installabile': 11.3, 'quota_installabile': 0.56},
    'capacita_rete': {'criticita': {'livello': 3, 'etichetta': 'alta'}},
    'prezzo': {'offerta_eur_ha': 37500, 'totale_offerto_eur': 757125},
    'ammissibilita': {'non_verificati': ['12 particelle con PAI frane/idraulica NON verificato'],
                      'segnalazioni': ['chioma reale: -1,2 ha netti']},
    'controparti': {'n_controparti': 12},
}

print('\n[1] i numeri arrivano, e quelli che non ci sono restano n.d.')

t1 = TS.raccogli(D)
pag = TS.html_teaser(t1, data='10/08/2026')
t('gli ettari netti sono nel teaser', '20,2' in pag or '20.2' in pag, grave=True)
t('gli ettari INSTALLABILI ci sono (il numero che conta)', '11,3' in pag or '11.3' in pag,
  grave=True)
t('i MWp escono come banda, non come numero secco', '5,6–8,9' in pag or '5.6–8.9' in pag,
  grave=True)
t('la distanza dalla SE e in km', '4,1 km' in pag or '4.1 km' in pag)
t('il prezzo richiesto e riportato', '37.500' in pag)

senza = dict(D, installabile={}, bancabilita=dict(D['bancabilita'], mwp_stimati=None))
p2 = TS.html_teaser(TS.raccogli(senza))
t('senza dato: scrive n.d., non inventa un numero', 'n.d.' in p2, grave=True)
t('controprova: col dato non scrive n.d. sugli installabili',
  p2.count('n.d.') > pag.count('n.d.'), f'{p2.count("n.d.")} vs {pag.count("n.d.")}',
  grave=True)

print('\n[2] le lacune sono DENTRO il teaser, non in fondo a un allegato')

t('la sezione esiste', 'Cosa resta da verificare' in pag, grave=True)
t('il PAI non verificato compare', 'PAI frane' in pag, grave=True)
t('anche "quadro proprietario SCONOSCIUTO" e trattato come lacuna',
  'SCONOSCIUTO' in pag, grave=True)
t('e NON viene ripetuto anche fra i rischi',
  pag.count('SCONOSCIUTO') == 1, str(pag.count('SCONOSCIUTO')))

pulito = dict(D, ammissibilita={'non_verificati': [], 'segnalazioni': []},
              bancabilita=dict(D['bancabilita'], rischi=['rischio ostaggio: 16%']))
p3 = TS.html_teaser(TS.raccogli(pulito))
t('controprova: senza lacune lo dichiara invece di lasciare il vuoto',
  'Nessuna verifica sospesa' in p3, grave=True)

print('\n[3] nessun nome di controparte, mai')

CON_NOMI = dict(D, controparti={
    'n_controparti': 3,
    'controparti': [{'nome': 'ROSSI MARIO', 'cf': 'RSSMRA70A01F717X', 'ha_controllati': 6.0},
                    {'nome': 'BIANCHI ANNA', 'ha_controllati': 3.0}]})
p4 = TS.html_teaser(TS.raccogli(CON_NOMI))
t('il nome della controparte NON esce', 'ROSSI' not in p4.upper(), grave=True)
t('il codice fiscale NON esce', 'RSSMRA' not in p4.upper(), grave=True)
t('ma il NUMERO di controparti si', '>3<' in p4 or '3</div>' in p4, grave=True)

print('\n[4] con il registro trattativa: gli ettari sotto opzione')

blk = {'titolo': 'x', 'ha_ancore': 0.0,
       'particelle': [{'fg': 70, 'pla': 1, 'ha': 6.0, 'netti': 6.0, 'ancora': False},
                      {'fg': 70, 'pla': 2, 'ha': 4.0, 'netti': 4.0, 'ancora': False}]}
reg = TR.apri(blk, None, oggi='2026-01-01')
TR.aggiorna(reg, 'Fg70/1', stato='opzione', oggi='2026-02-01')
p5 = TS.html_teaser(TS.raccogli(D, reg))
t('gli ettari con opzione firmata compaiono', 'opzione firmata' in p5, grave=True)
t('e la percentuale e quella vera (60%)', '60%' in p5, grave=True)
t('controprova: senza registro la riga non compare', 'opzione firmata' not in pag)

print('\n[5] il file: autoportante e senza rete')

d = tempfile.mkdtemp()
p = os.path.join(d, 'blocco.json')
json.dump(D, open(p, 'w', encoding='utf-8'))
out, dati = TS.genera(p, data='10/08/2026')
testo = open(out, encoding='utf-8').read()
t('scrive teaser.html accanto al blocco', os.path.basename(out) == 'teaser.html')
t('nessuna risorsa esterna (niente http:// nel markup)',
  'http://' not in testo and 'https://' not in testo, grave=True)
t('nessuna immagine referenziata se i file non ci sono', '<img' not in testo)

open(os.path.join(d, 'forma.png'), 'wb').close()
out2, _ = TS.genera(p, os.path.join(d, 't2.html'))
t('controprova: se forma.png esiste, viene referenziata in relativo',
  'src="forma.png"' in open(out2, encoding='utf-8').read(), grave=True)
t('il disclaimer dichiara che non ci sono dati personali',
  'Nessun dato personale' in testo, grave=True)

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
