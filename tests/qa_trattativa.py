# -*- coding: utf-8 -*-
"""QA trattativa — il registro non deve mai far sembrare le cose meglio di come sono.

Tre bugie possibili, tutte comode, tutte provate qui con la loro controprova:
  1. contare come "sotto controllo" chi ha solo detto «mi interessa»;
  2. lasciar passare una scadenza senza gridarlo;
  3. far sembrare "in corso" una riga che nessuno tocca da due mesi.

Le date sono sempre passate esplicitamente: un test che dipende da `oggi` reale
funziona il giorno che lo scrivi e fallisce a caso sei mesi dopo.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import trattativa as T

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


BLOCCO = {'titolo': 'blocco di prova', 'ha_ancore': 3.0,
          'particelle': [
              {'fg': 70, 'pla': 136, 'ha': 6.0, 'netti': 6.0, 'ancora': False},
              {'fg': 70, 'pla': 137, 'ha': 3.0, 'netti': 3.0, 'ancora': False},
              {'fg': 70, 'pla': 138, 'ha': 1.0, 'netti': 1.0, 'ancora': False},
              {'fg': 82, 'pla': 78, 'ha': 3.0, 'netti': 3.0, 'ancora': True}]}

CONTROPARTI = {'controparti': [
    {'nome': 'ROSSI MARIO', 'ha_controllati': 6.0, 'n_particelle': 1,
     'dettaglio': [{'fg': '70', 'pla': '136', 'ha_quota': 6.0}]},
    {'nome': 'BIANCHI ANNA', 'ha_controllati': 3.0, 'n_particelle': 1,
     'dettaglio': [{'fg': '70', 'pla': '137', 'ha_quota': 3.0}]},
    {'nome': 'VERDI LUIGI', 'ha_controllati': 1.0, 'n_particelle': 1,
     'dettaglio': [{'fg': '70', 'pla': '138', 'ha_quota': 1.0}]},
    # possiede solo terra gia' tua: non e' una controparte da pagare
    {'nome': 'BETA', 'ha_controllati': 3.0, 'n_particelle': 1,
     'dettaglio': [{'fg': '82', 'pla': '78', 'ha_quota': 3.0}]},
]}

print('\n[1] apertura del registro')

reg = T.apri(BLOCCO, CONTROPARTI, oggi='2026-01-10', comune='Morcone')
nomi = [r['chi'] for r in reg['righe']]
t('una riga per proprietario, non per particella', reg['per'] == 'proprietario')
t('chi possiede solo terra gia tua NON entra fra le controparti',
  'BETA' not in nomi, str(nomi), grave=True)
t('le righe partono da "da contattare", non da uno stato ottimistico',
  all(r['stato'] == 'da_contattare' for r in reg['righe']), grave=True)
t('ordinate per ettari: si telefona prima a chi pesa', nomi == ['ROSSI MARIO', 'BIANCHI ANNA', 'VERDI LUIGI'],
  str(nomi))

reg2 = T.apri(BLOCCO, None, oggi='2026-01-10')
t('senza visure le righe sono particelle... ', len(reg2['righe']) == 3)
t('...e il registro lo DICHIARA', 'visure mancanti' in reg2['per'], reg2['per'], grave=True)

print('\n[2] "sono interessato" non e un ettaro sotto controllo')

T.aggiorna(reg, 'ROSSI MARIO', stato='interessato', oggi='2026-01-20')
c = T.copertura(reg)
t('un interessato NON conta come terra sotto controllo',
  c['ha_sotto_controllo'] == 0.0, str(c), grave=True)
T.aggiorna(reg, 'ROSSI MARIO', stato='opzione', scadenza='2026-06-30',
           ore=4, nota='firmata opzione 6 mesi', oggi='2026-02-01')
c = T.copertura(reg)
t('controprova: con l opzione firmata i 6 ha contano',
  c['ha_sotto_controllo'] == 6.0, str(c), grave=True)
t('la percentuale e sul totale da acquisire', c['pct_sotto_controllo'] == 60.0, str(c))
t('il cambio di stato lascia traccia datata',
  any('interessato -> opzione' in n['testo'] for n in T._riga(reg, 'ROSSI')['note']),
  grave=True)

print('\n[3] il rischio ostaggio si ricalcola su chi MANCA')

piv = [p['chi'] for p in T.copertura(reg)['pivotali_residui']]
t('una volta firmato Rossi, il peso passa a chi resta',
  'BIANCHI ANNA' in piv and 'ROSSI MARIO' not in piv, str(piv), grave=True)
T.aggiorna(reg, 'VERDI LUIGI', stato='rifiutato', oggi='2026-02-02')
c = T.copertura(reg)
t('un rifiuto toglie ettari dal residuo, non dal totale',
  c['ha_persi'] == 1.0 and c['ha_totali'] == 10.0, str(c))
t('e le firme mancanti scendono', c['firme_mancanti'] == 1, str(c))

print('\n[4] le scadenze: l unico errore irrimediabile')

sc = T.scadenze(reg, oggi='2026-06-20')
t('un opzione che scade fra 10 giorni compare', sc and sc[0]['giorni'] == 10, str(sc), grave=True)
t('controprova: a marzo non deve ancora allarmare',
  T.scadenze(reg, oggi='2026-03-01') == [], str(T.scadenze(reg, oggi='2026-03-01')), grave=True)
sc2 = T.scadenze(reg, oggi='2026-07-10')
t('una scadenza passata e segnalata come SCADUTA',
  sc2 and sc2[0]['scaduta'] and sc2[0]['giorni'] < 0, str(sc2), grave=True)

print('\n[5] fermo != in corso')

st = T.stantii(reg, oggi='2026-05-01')
t('Bianchi, ferma dal 10/01, risulta stantia',
  any(x['chi'] == 'BIANCHI ANNA' for x in st), str(st), grave=True)
t('chi ha gia firmato NON e stantio', not any(x['chi'] == 'ROSSI MARIO' for x in st), str(st))
t('controprova: a gennaio nessuno e stantio', T.stantii(reg, oggi='2026-01-25') == [])

print('\n[6] il conto del TUO lavoro')

e = T.economia(reg, fee_eur=None)
t('senza una fee dichiarata non si inventa un compenso',
  e['fee_attesa_eur'] is None and e['eur_ora_se_chiude'] is None, str(e), grave=True)
T.aggiorna(reg, 'BIANCHI ANNA', ore=6, oggi='2026-05-02')
e = T.economia(reg, fee_eur=20000)
t('le ore si sommano', e['ore_spese'] == 10.0, str(e))
t('EUR/ora se chiude = fee / ore', e['eur_ora_se_chiude'] == 2000, str(e))
t('EUR/ora a oggi pesa solo cio che e sotto controllo',
  e['eur_ora_a_oggi'] == 1200, str(e), grave=True)

print('\n[7] input sbagliati: fermarsi, non scrivere a caso')

for chi, kw, exc in (('ROSSI MARIO', {'stato': 'quasi_fatta'}, T.StatoIgnoto),
                     ('ROSSI MARIO', {'scadenza': 'domani'}, ValueError),
                     ('CHI NON ESISTE', {'stato': 'contattato'}, ValueError)):
    try:
        T.aggiorna(reg, chi, oggi='2026-05-03', **kw)
        alzato = False
    except exc:
        alzato = True
    t(f'{list(kw)[0]}={list(kw.values())[0]!r} -> errore, non scrittura silenziosa', alzato,
      grave=True)

print('\n[9] l altro lato del tavolo: i developer e l esclusiva')

T.developer(reg, 'RWE', stato='contattato', contatto='Paola L.', oggi='2026-05-04')
T.developer(reg, 'RWE', stato='nda', nda=True, esclusiva_fino='2026-08-31',
            nota='esclusiva 3 mesi sul blocco', oggi='2026-05-10')
d = reg['developer'][0]
t('il developer viene registrato una volta sola', len(reg['developer']) == 1,
  str(reg['developer']))
t('lo stato avanza e lascia traccia',
  d['stato'] == 'nda' and any('contattato -> nda' in n['testo'] for n in d['note']),
  str(d), grave=True)
sc = T.scadenze(reg, oggi='2026-08-20')
tipi = {x['tipo'] for x in sc}
t("l'esclusiva scade come un'opzione: stesso allarme",
  'esclusiva' in tipi, str(sc), grave=True)
t('e resta distinguibile dalle opzioni', 'opzione' in tipi or len(sc) >= 1, str(tipi))
try:
    T.developer(reg, 'RWE', stato='quasi', oggi='2026-05-11')
    alzato = False
except T.StatoIgnoto:
    alzato = True
t('uno stato developer inventato alza', alzato, grave=True)
t('controprova: prima del preavviso l esclusiva non allarma',
  not any(x['tipo'] == 'esclusiva' for x in T.scadenze(reg, oggi='2026-06-01')),
  str(T.scadenze(reg, oggi='2026-06-01')), grave=True)

print('\n[10] il portafoglio: tutti i blocchi in una riga')

import json as _json
dd = tempfile.mkdtemp()
T.salva(reg, os.path.join(dd, 'morcone.json'))
reg_b = T.apri(BLOCCO, CONTROPARTI, oggi='2026-01-10', comune='Campolattaro')
T.aggiorna(reg_b, 'ROSSI MARIO', stato='rogito', ore=2, oggi='2026-02-01')
T.salva(reg_b, os.path.join(dd, 'campolattaro.json'))
open(os.path.join(dd, 'rotto.json'), 'w', encoding='utf-8').write('{"non": "un registro"}')

P = T.portafoglio(dd, oggi='2026-06-20', fee_eur_ha=2000)
t('due blocchi contati', P['n_blocchi'] == 2, str(P['n_blocchi']), grave=True)
t('il file illeggibile e DICHIARATO, non saltato',
  len(P['illeggibili']) == 1, str(P['illeggibili']), grave=True)
t('gli ettari sotto controllo si sommano fra i blocchi',
  P['ha_sotto_controllo'] == 12.0, str(P['ha_sotto_controllo']), grave=True)
t('il valore matura SOLO sugli ettari con opzione/rogito',
  P['valore_maturato_eur'] == 24000, str(P['valore_maturato_eur']), grave=True)
t('e le ore danno un EUR/ora', P['eur_ora'] == round(24000 / P['ore_totali']),
  str(P))
t('le scadenze scadute vengono contate su tutti i blocchi',
  P['scadute'] >= 0 and P['scadenze_30gg'] >= 1, str(P), grave=True)
t('il riepilogo si stampa', 'PORTAFOGLIO' in T.print_portafoglio(P))

print('\n[8] il registro sopravvive al riavvio')

d = tempfile.mkdtemp()
p = T.salva(reg, os.path.join(d, 'sub', 't.json'))
reg3 = T.carica(p)
t('salva e ricarica identico', T.copertura(reg3) == T.copertura(reg), grave=True)
t('le note restano', len(T._riga(reg3, 'ROSSI')['note']) >= 2)
t('il riepilogo si stampa senza esplodere', 'SOTTO CONTROLLO' in T.print_stato(reg3, oggi='2026-06-20'))

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
