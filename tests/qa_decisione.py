# -*- coding: utf-8 -*-
"""QA decisione — ordinare le verifiche senza inventare verdetti.

Questo modulo non misura niente: prende quello che gli altri hanno misurato e
decide **in che ordine guardare**. Percio' i modi di sbagliare sono diversi dal
solito, e sono tre:

1. **scambiare un indizio per un verdetto** — alla prima stesura il ponte dai
   rischi del blocco leggeva "rete congestionata" come "nessuna capacita" e
   faceva uscire un FERMO che nessuno aveva accertato. Una provincia
   congestionata alza la probabilita di un no: non lo sostituisce;
2. **il default comodo** — una domanda che non compare nel quadro deve valere
   NON VERIFICATA. Se valesse "a posto", il tool si convincerebbe da solo, e lo
   farebbe proprio quando tutto il resto va bene;
3. **l'ordine sbagliato** — un killer da mezz'ora deve stare davanti a un costo
   da otto ore. Se l'ordine e' per modulo o per gravita' percepita, il tool fa
   perdere le settimane che dovrebbe far risparmiare.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import decisione as DEC

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


print('\n[1] il default e NON VERIFICATO, mai "a posto"')

D = DEC.valuta({})
t('nessuna domanda risulta verificata',
  all(r['stato'] == 'non_verificato' for r in D['righe']),
  str({r['id']: r['stato'] for r in D['righe']}), grave=True)
t('il giudizio dice che ci sono killer aperti', D['giudizio'] == 'DA VERIFICARE',
  D['giudizio'], grave=True)
t('e conta quante ore servono per chiuderli', D['ore_per_chiudere_i_killer'] > 0,
  str(D['ore_per_chiudere_i_killer']), grave=True)
t('la nota dice esplicitamente che le ore sono stime',
  'STIME' in D['nota'], grave=True)
t('e che una domanda assente e NON verificata', 'NON verificata' in D['nota'],
  grave=True)

print('\n[2] l ordine: prima cio che puo chiudere la partita, poi il costo')

ids = [r['id'] for r in D['coda']]
killer = [r['id'] for r in DEC.CATALOGO if r['killer']]
pos_k = [ids.index(k) for k in killer if k in ids]
pos_nk = [ids.index(r['id']) for r in DEC.CATALOGO if not r['killer'] and r['id'] in ids]
t('tutti i killer stanno prima di tutti i non-killer',
  max(pos_k) < min(pos_nk), f'killer {pos_k} vs altri {pos_nk}', grave=True)
ore_k = [r['ore'] for r in D['coda'] if r['killer']]
t('e fra i killer si va dal piu economico al piu caro',
  ore_k == sorted(ore_k), str(ore_k), grave=True)
t('in cima c e l habitat: mezz ora, e puo azzerare tutto',
  D['coda'][0]['id'] == 'habitat', D['coda'][0]['id'], grave=True)
t('la rete, che costa 8 ore, NON e in cima pur essendo un killer',
  ids.index('rete') > ids.index('habitat'), str(ids), grave=True)

print('\n[3] verificato = fuori dalla coda; violato = in cima')

D2 = DEC.valuta({'habitat': 'verificato_ok', 'fuoco': 'verificato_ok'})
t('cio che e verificato esce dalla coda',
  not any(r['id'] in ('habitat', 'fuoco') for r in D2['coda']),
  str([r['id'] for r in D2['coda']]), grave=True)
t('e ora in cima c e area_protetta: il killer aperto piu economico rimasto (1 h)',
  D2['coda'][0]['id'] == 'area_protetta', D2['coda'][0]['id'], grave=True)
t('il titolo (2 h) viene subito dopo, non prima',
  [r['id'] for r in D2['coda']].index('titolo')
  > [r['id'] for r in D2['coda']].index('area_protetta'),
  str([r['id'] for r in D2['coda']]), grave=True)
t('le ore residue scendono',
  D2['ore_per_chiudere_i_killer'] < D['ore_per_chiudere_i_killer'],
  f"{D2['ore_per_chiudere_i_killer']} vs {D['ore_per_chiudere_i_killer']}", grave=True)

print('\n[4] un killer violato ferma tutto; un costo violato no')

D3 = DEC.valuta({'habitat': 'violato'})
t('killer violato -> FERMO', D3['giudizio'] == 'FERMO', D3['giudizio'], grave=True)
t('e il perche cita la conseguenza, non solo il nome',
  'destinazione d uso' in D3['perche'], D3['perche'], grave=True)
t('sta in cima alla coda', D3['coda'][0]['id'] == 'habitat', D3['coda'][0]['id'],
  grave=True)
t('e il riepilogo lo marca come esito gia negativo',
  'ESITO GIA NEGATIVO' in DEC.print_decisione(D3), grave=True)

D4 = DEC.valuta({'firme': 'violato'})
t('controprova: un NON-killer violato non ferma il progetto',
  D4['giudizio'] != 'FERMO', D4['giudizio'], grave=True)
t('e viene descritto come costo, non come fine',
  'pesa sul prezzo' in DEC.print_decisione(D4), grave=True)

D5 = DEC.valuta({r['id']: 'verificato_ok' for r in DEC.CATALOGO if r['killer']})
t('tutti i killer chiusi -> nessun killer aperto',
  D5['giudizio'] == 'NESSUN KILLER APERTO', D5['giudizio'], grave=True)
t('e le ore residue sono zero', D5['ore_per_chiudere_i_killer'] == 0, grave=True)

print('\n[5] un INDIZIO non diventa un verdetto')

# Il caso vero: il blocco 1 di Morcone dichiara "rete alta (livello 3/4): rete
# congestionata". E' un indizio sulla probabilita, non una risposta sulla coda.
RISCHI = ['rete alta (livello 3/4): rete congestionata: connessione onerosa o con attese lunghe',
          'quadro proprietario SCONOSCIUTO (nessuna visura): le controparti stanno fra 16 e 18',
          'frammentazione alta: 0.40 ha per controparte']
s, note = DEC.da_rischi(RISCHI)
t('la congestione NON marca la rete come violata', s.get('rete') != 'violato',
  str(s.get('rete')), grave=True)
t('ma lascia una nota che alza la priorita',
  'rete' in note and 'non e un no' in note['rete'], str(note), grave=True)
Dr = DEC.valuta(s, note=note)
t('e il giudizio complessivo NON e FERMO', Dr['giudizio'] != 'FERMO', Dr['giudizio'],
  grave=True)
t('la nota compare nel riepilogo accanto alla domanda',
  'alza la probabilita' in DEC.print_decisione(Dr), grave=True)
t('le visure mancanti lasciano il titolo NON verificato, non violato',
  s.get('titolo') == 'non_verificato', str(s.get('titolo')), grave=True)
t('la frammentazione invece e un fatto accertato', s.get('firme') == 'violato',
  str(s.get('firme')), grave=True)

print('\n[6] il ponte non inventa mai un "verificato"')

s2, n2 = DEC.da_rischi([])
t('nessun rischio -> nessuno stato dedotto', s2 == {}, str(s2), grave=True)
D6 = DEC.valuta(s2)
t('e tutto resta non verificato',
  all(r['stato'] == 'non_verificato' for r in D6['righe']), grave=True)
s3, _ = DEC.da_rischi(['tutto a posto, nessun problema rilevato'])
t('controprova: nemmeno una frase rassicurante produce un verificato_ok',
  'verificato_ok' not in s3.values(), str(s3), grave=True)
s4, _ = DEC.da_rischi(RISCHI, stato={'rete': 'verificato_ok'})
t('e uno stato gia noto non viene sovrascritto dal ponte',
  s4['rete'] == 'verificato_ok', str(s4['rete']), grave=True)

print('\n[7] la prossima mossa, e il rifiuto di inventarne una')

t('con killer aperti la prossima mossa e il primo della coda',
  'habitat' in (DEC.prossima_mossa(D) or '').lower()
  or '6210' in (DEC.prossima_mossa(D) or ''), DEC.prossima_mossa(D), grave=True)
t('e dichiara che puo chiudere la partita',
  'chiudere la partita' in (DEC.prossima_mossa(D) or ''), DEC.prossima_mossa(D),
  grave=True)
Dtutto = DEC.valuta({r['id']: 'verificato_ok' for r in DEC.CATALOGO})
t('a coda vuota non si inventa una mossa', DEC.prossima_mossa(Dtutto) is None,
  str(DEC.prossima_mossa(Dtutto)), grave=True)
t('un killer gia violato viene messo davanti a tutto, da leggere prima',
  'LEGGI PRIMA QUESTO' in (DEC.prossima_mossa(D3) or ''), DEC.prossima_mossa(D3),
  grave=True)

print('\n[8] uno stato inventato viene rifiutato')

try:
    DEC.valuta({'habitat': 'forse'})
    alzato = False
except ValueError:
    alzato = True
t('uno stato fuori dai tre ammessi alza', alzato, grave=True)
try:
    DEC._voce('inesistente')
    alzato2 = False
except KeyError:
    alzato2 = True
t('e una domanda inesistente alza', alzato2, grave=True)
t('ogni voce del catalogo dichiara la sua fonte',
  all(r.get('fonte') for r in DEC.CATALOGO),
  str([r['id'] for r in DEC.CATALOGO if not r.get('fonte')]), grave=True)
t('e dichiara la conseguenza se va male',
  all(r.get('se_vero') for r in DEC.CATALOGO), grave=True)

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
