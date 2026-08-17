# -*- coding: utf-8 -*-
"""QA visure — da particelle a controparti reali.

Tre bug veri trovati sulle visure di Morcone, tutti nella direzione peggiore
(sottostimare le controparti o gonfiare gli ettari). Qui restano bloccati.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from landscout import visure as V

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


print('=' * 76)
print('  QA VISURE — parsing, intestazioni condivise, quote, deduplica')
print('=' * 76)

# ------------------------------------------------------------------ 1. parsing
print('\n[1] parsing di una visura sintetica')
VIS = """
Immobile di catasto terreni - n.1
Dati identificativi: Comune di MORCONE (F717 ) (BN)
Foglio 70 Particella 100
Superficie: 10.000 m2
Intestazione attuale dell'immobile n. 1 - totale righe intestati: 1
1. ROSSI Mario (CF RSSMRA70A01F717A) Nato a MORCONE (BN) il 01/01/1970 Diritto di: Proprieta'
per 1000/1000
Immobile di catasto terreni - n.2
Dati identificativi: Comune di MORCONE (F717 ) (BN)
Foglio 70 Particella 101
Superficie: 20.000 m2
Immobile di catasto terreni - n.3
Dati identificativi: Comune di MORCONE (F717 ) (BN)
Foglio 70 Particella 102
Superficie: 30.000 m2
Intestazione attuale degli immobili dal n. 2 al n. 3 - totale righe intestati: 2
1. BIANCHI Anna (CF BNCNNA60A41F717B) Nata a MORCONE (BN) il 01/01/1960 Diritto di: Proprieta'
per 500/1000
2. VERDI Luigi (CF VRDLGU55A01F717C) Nato a MORCONE (BN) il 01/01/1955 Diritto di: Proprieta'
per 500/1000
"""
p = os.path.join(os.environ.get('TEMP', '/tmp'), '_qa_visura.txt')
open(p, 'w', encoding='utf-8').write(VIS)
im = V.leggi(p)

t('legge tutti gli immobili', len(im) == 3, f'trovati {len(im)}')
t('estrae foglio e particella', (im[0]['fg'], im[0]['pla']) == ('70', '100'))
t('estrae il codice comune', im[0]['cod_comune'] == 'F717')
t('estrae la superficie', im[0]['mq'] == 10000, f"mq {im[0]['mq']}")
t('estrae nome e CF', im[0]['intestatari'][0]['cf'] == 'RSSMRA70A01F717A')
t('estrae il diritto anche se va a capo',
  im[0]['intestatari'][0]['diritto'] and 'PROPRIETA' in im[0]['intestatari'][0]['diritto'],
  f"diritto {im[0]['intestatari'][0]['diritto']}", grave=True)
t('estrae la quota', im[0]['intestatari'][0]['quota'] == '1000/1000')

# BUG 1 — intestazione condivisa su un INTERVALLO: la visura la scrive una volta
# sola per piu' immobili. Attribuirla al solo blocco in cui compare lascia gli
# altri senza proprietario, e un proprietario che sparisce SOTTOSTIMA le
# controparti: l'errore va nella direzione peggiore.
t('intestazione "dal n.2 al n.3" applicata a ENTRAMBI gli immobili',
  len(im[1]['intestatari']) == 2 and len(im[2]['intestatari']) == 2,
  f"n2={len(im[1]['intestatari'])} n3={len(im[2]['intestatari'])}", grave=True)
t('nessun immobile resta senza intestatari',
  all(x['intestatari'] for x in im), grave=True)

# ------------------------------------------------------------------ 2. quote
print('\n[2] quote: dominicali vs godimento')
t('proprieta e dominicale', V._classe_diritto("Proprieta'") == 'dominicale')
t('nuda proprieta e dominicale (non godimento)',
  V._classe_diritto('NUDA PROPRIETA') == 'dominicale', grave=True)
t('usufrutto e godimento', V._classe_diritto('USUFRUTTO') == 'godimento')
t('enfiteusi e dominicale', V._classe_diritto('ENFITEUSI') == 'dominicale')
t('diritto ignoto non viene spacciato per dominicale',
  V._classe_diritto('PINCO PALLO') == 'ignoto', grave=True)

# BUG 2 — su una stessa particella coesistono diritti DIVERSI (nuda proprieta'
# + usufrutto): le quote sommano a piu' di 1. Sommarle tutte gonfia gli ettari.
BLK = {'particelle': [
    {'fg': '70', 'pla': '200', 'netti': 10.0, 'ancora': False},
]}
DOPPIO = [{'tipo': 'terreni', 'cod_comune': 'F717', 'comune': 'MORCONE',
           'fg': '70', 'pla': '200', 'mq': 100000, 'fonte': 'x',
           'intestatari': [
               {'nome': 'NUDO PROPRIETARIO', 'cf': 'AAA', 'diritto': 'NUDA PROPRIETA',
                'quota': '1000/1000', 'quota_frazione': 1.0, 'persona_giuridica': False},
               {'nome': 'USUFRUTTUARIO', 'cf': 'BBB', 'diritto': 'USUFRUTTO',
                'quota': '1000/1000', 'quota_frazione': 1.0, 'persona_giuridica': False}]}]
C = V.aggrega(DOPPIO, blocco=BLK)
t('nuda proprieta + usufrutto NON raddoppiano gli ettari',
  abs(C['ha_totali'] - 10.0) < 0.01, f"ha {C['ha_totali']}", grave=True)
t('l usufruttuario resta controparte, con zero ettari',
  C['n_controparti'] == 2 and any(x['ha_controllati'] == 0 for x in C['controparti']),
  f"controparti {[(x['nome'], x['ha_controllati']) for x in C['controparti']]}", grave=True)
t('chi ha solo diritti deboli e segnalato',
  any(x['solo_diritti_deboli'] for x in C['controparti']), grave=True)

# comproprieta' normale: le quote si sommano all'intero e gli ettari si dividono
META = [{'tipo': 'terreni', 'cod_comune': 'F717', 'comune': 'MORCONE',
         'fg': '70', 'pla': '200', 'mq': 100000, 'fonte': 'x',
         'intestatari': [
             {'nome': 'A', 'cf': 'A1', 'diritto': "PROPRIETA'", 'quota': '500/1000',
              'quota_frazione': 0.5, 'persona_giuridica': False},
             {'nome': 'B', 'cf': 'B1', 'diritto': "PROPRIETA'", 'quota': '500/1000',
              'quota_frazione': 0.5, 'persona_giuridica': False}]}]
C2 = V.aggrega(META, blocco=BLK)
t('due comproprietari al 50% fanno 5 ha ciascuno',
  all(abs(x['ha_controllati'] - 5.0) < 0.01 for x in C2['controparti']),
  f"{[(x['nome'], x['ha_controllati']) for x in C2['controparti']]}", grave=True)

# ------------------------------------------------------------------ 3. dedup
print('\n[3] deduplica: la particella cointestata compare in PIU visure')
# BUG 3 — due coniugi hanno fondi in comune: la stessa particella arriva da
# due visure diverse e gli ettari venivano contati due volte (+1,12 ha su Morcone).
DUE = META + [dict(META[0])]           # stessa particella, due volte
C3 = V.aggrega(DUE, blocco=BLK)
t('la stessa particella da due visure non raddoppia gli ettari',
  abs(C3['ha_totali'] - 10.0) < 0.01, f"ha {C3['ha_totali']}", grave=True)
t('i duplicati vengono contati e dichiarati',
  C3['immobili_duplicati_uniti'] == 1, f"dup {C3['immobili_duplicati_uniti']}")
t('senza duplicati il contatore resta a zero (controprova)',
  V.aggrega(META, blocco=BLK)['immobili_duplicati_uniti'] == 0, grave=True)

# ------------------------------------------------------------------ 4. copertura
print('\n[4] copertura: quello che manca va detto')
BLK2 = {'particelle': [{'fg': '70', 'pla': '200', 'netti': 10.0, 'ancora': False},
                       {'fg': '70', 'pla': '999', 'netti': 5.0, 'ancora': False}]}
C4 = V.aggrega(META, blocco=BLK2)
t('dichiara le particelle ancora senza visura',
  C4['particelle_mancanti'] == [('70', '999')], f"{C4['particelle_mancanti']}", grave=True)
t('non si dichiara completo se manca qualcosa', C4['completo'] is False, grave=True)
t('si dichiara completo quando c e tutto (controprova)',
  V.aggrega(META, blocco=BLK)['completo'] is True, grave=True)

b = {'n_acquisti': 2, 'rischi': [], 'punti_forti': [],
     'nota_controparti': 'per particella'}
b2 = V.applica_a_bancabilita(b, C4)
t('la bancabilita passa al conteggio per PROPRIETARIO',
  b2['n_controparti_reali'] == 2 and 'REALI' in b2['nota_controparti'], grave=True)
t('copertura parziale = rischio dichiarato',
  any('INCOMPLETO' in r for r in b2['rischi']), grave=True)

# ------------------------------------------------------------------ 5. titolo
print('\n[5] enfiteusi: due titolari, e va detto')
ENF = [{'tipo': 'terreni', 'cod_comune': 'F717', 'comune': 'MORCONE',
        'fg': '70', 'pla': '200', 'mq': 100000, 'fonte': 'x',
        'intestatari': [
            {'nome': 'ENTE', 'cf': 'E1', 'diritto': 'DIRITTO DEL CONCEDENTE',
             'quota': '1000/1000', 'quota_frazione': 1.0, 'persona_giuridica': True},
            {'nome': 'COLTIVATORE', 'cf': 'C1', 'diritto': 'ENFITEUSI',
             'quota': '1/1', 'quota_frazione': 1.0, 'persona_giuridica': False}]}]
C5 = V.aggrega(ENF, blocco=BLK)
t('enfiteusi/livello segnalata fra i titoli da chiarire',
  len(C5['titoli_da_sanare']) == 1, f"{C5['titoli_da_sanare']}", grave=True)
t('la proprieta piena NON finisce fra i titoli da chiarire (controprova)',
  len(V.aggrega(META, blocco=BLK)['titoli_da_sanare']) == 0, grave=True)
b3 = V.applica_a_bancabilita({'n_acquisti': 1, 'rischi': [], 'punti_forti': []}, C5)
t('il titolo da chiarire diventa un rischio di bancabilita',
  any('titolo da chiarire' in r for r in b3['rischi']), grave=True)

# ------------------------------------------------------------------ 6. reale
print('\n[6] visure REALI di Morcone (se presenti)')
REALE = os.environ.get('LANDSCOUT_VISURA_PDF', '')  # PDF locale, non incluso
if os.path.exists(REALE):
    imr = V.leggi(REALE)
    ter = [x for x in imr if x['tipo'] == 'terreni']
    fab = [x for x in imr if x['tipo'] == 'fabbricati']
    # la visura dichiara in testa: terreni 30, fabbricati 12
    t('conta i terreni come dichiarato dalla visura (30)', len(ter) == 30, f'{len(ter)}',
      grave=True)
    t('conta i fabbricati come dichiarato dalla visura (12)', len(fab) == 12, f'{len(fab)}',
      grave=True)
    t('nessun immobile reale senza intestatari',
      all(x['intestatari'] for x in imr),
      f"vuoti {[(x['fg'], x['pla']) for x in imr if not x['intestatari']][:5]}", grave=True)
else:
    print('  (saltato: visure reali non disponibili su questa macchina)')

print('\n' + '=' * 76)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 76)
sys.exit(1 if GRAVI else 0)
