# -*- coding: utf-8 -*-
"""QA portafoglio — l'invariante e' uno solo, e se salta si vende due volte.

Il modo di sbagliare qui non e' un blocco brutto: e' **la stessa particella in
due blocchi**. Non si vede guardando i numeri (gli ettari totali tornano, le
firme tornano), si vede quando due teaser diversi promettono lo stesso fondo a
due developer. Quindi: nessuna sovrapposizione, mai, nemmeno quando la costruzione
si interrompe a meta' o quando i portafogli vengono fusi.

Gli altri tre pericoli:
  · **il residuo taciuto** — "3 blocchi da 60 ha" letto come "il pool e' finito",
    mentre 300 ha sono rimasti fuori in isole scollegate;
  · **il blocco-residuo spacciato per sito** — un aggregato da 4 ha su un target
    di 25 non e' un sito, e va detto;
  · **le ancore perse per strada** — se la terra di famiglia deve starci tutta,
    questa non e' la funzione giusta, e il modulo lo deve dire invece di
    restituire un portafoglio che la lascia fuori.

Le geometrie sono sintetiche: una griglia di quadrati con corridoi vuoti, cosi'
le isole sono note per costruzione e i test non dipendono dalla rete.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import blocco as BL
from landscout import portafoglio as PF

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


LA0, LO0 = 42.30, 13.70
PASSO = 0.0020          # ~222 m di passo -> ~4,7 ha a quadrato
# lato quasi uguale al passo: il varco fra due quadrati vicini deve restare
# SOTTO la soglia di adiacenza (15 m), altrimenti la griglia non e' una griglia
# ma 30 particelle isolate — ed e' esattamente cio' che il test [3] verifica
# come premessa prima di fidarsi del resto.
def quadrato(r, c, lato=0.00195):
    la = LA0 + r * PASSO
    lo = LO0 + c * PASSO
    return [(la, lo), (la + lato, lo), (la + lato, lo + lato), (la, lo + lato)]


def griglia(righe, colonne, salta_colonna=None, fg='70'):
    """Griglia di particelle. `salta_colonna` lascia un corridoio vuoto: le due
    meta' diventano isole separate, cosa nota per costruzione."""
    P, n = [], 0
    for r in range(righe):
        for c in range(colonne):
            if salta_colonna is not None and c == salta_colonna:
                continue
            n += 1
            poly = quadrato(r, c)
            P.append({'fg': fg, 'pla': str(100 + n), 'poly': poly,
                      'ha': 4.0, 'netti': 4.0})
    return P


print('\n[1] due blocchi dallo stesso pool non condividono nemmeno una particella')

P = griglia(6, 6)
A = {'ammesse': P}
adj = BL.adiacenza(A)
R = PF.costruisci(A, adj, target_ha=20.0, n_max=3, comune='Prova', verbose=False)
t('sono usciti piu blocchi', R['n_blocchi'] >= 2, str(R['n_blocchi']), grave=True)
t('NESSUNA sovrapposizione', R['sovrapposizioni'] == {}, str(R['sovrapposizioni']),
  grave=True)
tutte = [f"{p['fg']}_{p['pla']}" for b in R['blocchi'] for p in b['particelle']]
t('e infatti le chiavi sono tutte distinte', len(tutte) == len(set(tutte)),
  f'{len(tutte)} vs {len(set(tutte))}', grave=True)
t('gli ettari nei blocchi non superano il pool',
  R['ha_in_blocchi'] <= R['ha_pool'] + 1e-6,
  f"{R['ha_in_blocchi']} > {R['ha_pool']}", grave=True)
t('ogni blocco raggiunge almeno il target',
  all(b['ha_netti'] >= 20.0 * 0.98 for b in R['blocchi']),
  str([b['ha_netti'] for b in R['blocchi']]))

print('\n[2] il residuo si dichiara: "3 blocchi" non vuol dire "pool finito"')

R2 = PF.costruisci(A, adj, target_ha=20.0, n_max=1, comune='Prova', verbose=False)
t('un blocco solo lascia residuo', R2['ha_residuo'] > 0, str(R2['ha_residuo']),
  grave=True)
t('la percentuale di pool usato e coerente',
  abs(R2['pct_pool_usato'] - 100 * R2['ha_in_blocchi'] / R2['ha_pool']) < 0.11,
  f"{R2['pct_pool_usato']}", grave=True)
t('ettari in blocchi + residuo = pool',
  abs(R2['ha_in_blocchi'] + R2['ha_residuo'] - R2['ha_pool']) < 0.05,
  f"{R2['ha_in_blocchi']} + {R2['ha_residuo']} vs {R2['ha_pool']}", grave=True)
t('sotto il 50% di pool usato compare l avviso',
  any('del pool e finito nei blocchi' in a for a in R2['avvisi']), str(R2['avvisi']),
  grave=True)
t('e dice in quante isole', R2['residuo_isole'] != [], str(R2['residuo_isole']))
t('il motivo di stop e esplicito', 'blocchi richiesti' in R2['motivo_stop'],
  R2['motivo_stop'])

print('\n[3] le isole scollegate restano scollegate')

# corridoio vuoto in colonna 3: 6x3 a sinistra (72 ha) e 6x2 a destra (48 ha)
PI = griglia(6, 6, salta_colonna=3)
AI = {'ammesse': PI}
adjI = BL.adiacenza(AI)
comp = BL.componenti(AI, adjI)
t('la griglia sintetica ha davvero due isole', len(comp) == 2, str([len(c) for c in comp]),
  grave=True)
RI = PF.costruisci(AI, adjI, target_ha=20.0, n_max=4, comune='Isole', verbose=False)
t('nessuna sovrapposizione anche a cavallo delle isole', RI['sovrapposizioni'] == {},
  str(RI['sovrapposizioni']), grave=True)
for b in RI['blocchi']:
    ids = {f"{p['fg']}_{p['pla']}" for p in b['particelle']}
    dentro = [any(f"{PI[i]['fg']}_{PI[i]['pla']}" in ids for i in c) for c in comp]
    t(f"il blocco {b['sito']} sta in UNA sola isola", sum(dentro) == 1, str(dentro),
      grave=True)

print('\n[4] un aggregato da residuo non e un sito, e viene detto')

R4 = PF.costruisci(A, adj, target_ha=20.0, n_max=99, comune='Prova', verbose=False)
t('la costruzione si ferma da sola', R4['n_blocchi'] < 99, str(R4['n_blocchi']),
  grave=True)
t('e dice perche', 'frammentato' in R4['motivo_stop'] or 'esaurito' in R4['motivo_stop'],
  R4['motivo_stop'], grave=True)
t('nessun blocco scende sotto la quota minima',
  all(b['ha_netti'] >= 20.0 * PF.QUOTA_MIN for b in R4['blocchi']),
  str([b['ha_netti'] for b in R4['blocchi']]), grave=True)
sotto = [b for b in R4['blocchi'] if b.get('sotto_target')]
t('se un blocco e sotto target lo dichiara',
  (not sotto) or any('sotto il target' in a for a in R4['avvisi']),
  str(R4['avvisi']), grave=True)

print('\n[5] le ancore fuori dai blocchi si dichiarano, non si nascondono')

# ancora isolata: una particella lontanissima, che nessun blocco puo raggiungere
PA = griglia(5, 5) + [{'fg': '99', 'pla': '1', 'ha': 4.0, 'netti': 4.0,
                       'poly': quadrato(80, 80)}]
AA = {'ammesse': PA}
adjA = BL.adiacenza(AA)
lontana = len(PA) - 1
RA = PF.costruisci(AA, adjA, target_ha=20.0, n_max=2, ancore=[0, 1, lontana],
                   comune='Ancore', verbose=False)
t("l'ancora irraggiungibile risulta FUORI", '99_1' in RA['ancore_fuori'],
  str(RA['ancore_fuori']), grave=True)
t('e c e un avviso che rimanda a copri_ancore',
  any('copri_ancore' in a for a in RA['avvisi']), str(RA['avvisi']), grave=True)
t('le ancore raggiungibili sono invece dentro',
  RA['ha_ancore_in_blocchi'] > 0, str(RA['ha_ancore_in_blocchi']))
RB = PF.costruisci(A, adj, target_ha=20.0, n_max=2, comune='Prova', verbose=False)
t('controprova: senza ancore non si inventa un avviso ancore',
  not any('copri_ancore' in a for a in RB['avvisi']), str(RB['avvisi']), grave=True)

print('\n[6] si prova piu di un ordine, e si dichiara quale ha vinto')

t('le prove sono riportate tutte', len(R['prove']) == len(PF.ORDINI), str(R['prove']),
  grave=True)
t("l'ordine scelto e uno di quelli provati",
  R['ordine_scelto'] in {p['ordine'] for p in R['prove']}, str(R['ordine_scelto']),
  grave=True)
t('e ha il valore migliore fra le prove',
  R['ha_in_blocchi'] >= max(p['ha'] for p in R['prove']) - 1e-6,
  f"{R['ha_in_blocchi']} vs {[p['ha'] for p in R['prove']]}", grave=True)

print('\n[7] la classifica ordina, e mostra i numeri con cui ordina')

Re = PF.classifica(R4, 'ettari')
t('per ettari e decrescente',
  all(Re['blocchi'][i]['ha_netti'] >= Re['blocchi'][i + 1]['ha_netti']
      for i in range(len(Re['blocchi']) - 1)),
  str([b['ha_netti'] for b in Re['blocchi']]), grave=True)
Rf = PF.classifica(R4, 'firme')
t('per firme ordina su ha/firma',
  all(Rf['blocchi'][i]['ha_per_firma'] >= Rf['blocchi'][i + 1]['ha_per_firma']
      for i in range(len(Rf['blocchi']) - 1)),
  str([b['ha_per_firma'] for b in Rf['blocchi']]), grave=True)
t('ogni blocco porta ha/firma e quota tua',
  all('ha_per_firma' in b and 'quota_tua_pct' in b for b in Rf['blocchi']), grave=True)
t('i nomi dei siti restano unici dopo il riordino',
  len({b['sito'] for b in Rf['blocchi']}) == len(Rf['blocchi']),
  str([b['sito'] for b in Rf['blocchi']]), grave=True)
t('la nota dichiara che rete e prezzo non sono nel punteggio',
  'NON conosce rete' in R['nota'], grave=True)

print()
print('[6-bis] la rete: la domanda che il developer fa per prima')

# fetch finto: niente rete nei test. Una SE a ~1 km dal blocco 1 e una linea AT.
def _finto_fetch(q):
    return {'elements': [
        {'type': 'node', 'id': 1, 'lat': 42.3095, 'lon': 13.7005,
         'tags': {'power': 'substation'}},
        {'type': 'way', 'id': 2, 'tags': {'power': 'line', 'voltage': '150000'},
         'geometry': [{'lat': 42.2990, 'lon': 13.6990}, {'lat': 42.2990, 'lon': 13.7200}]},
    ]}


from landscout import rete as RT
Rr = PF.costruisci(A, adj, target_ha=20.0, n_max=3, comune='Rete', verbose=False)
gruppi = {b['sito']: [(q[0], q[1]) for p in b['particelle'] for q in p['poly']]
          for b in Rr['blocchi']}
D = RT.distanze_multi(gruppi, _fetch=_finto_fetch)
t('una sola chiamata copre tutti i gruppi', len(D) == len(gruppi), str(len(D)),
  grave=True)
t('e ogni gruppo ha la sua distanza, non la stessa',
  len({v['d_se_m'] for v in D.values()}) > 1, str({k: v['d_se_m'] for k, v in D.items()}))
t('la linea AT viene riconosciuta a 150 kV',
  all(v['linea_kv'] == 150 for v in D.values()), str(D), grave=True)

PF.arricchisci_rete(Rr, verbose=False, _distanze=D)
t('i blocchi portano la distanza dalla SE',
  all(b['d_se_m'] is not None for b in Rr['blocchi']), grave=True)
t('e sono dichiarati verificati',
  all(b['rete_verificata'] for b in Rr['blocchi']), grave=True)
Rr = PF.classifica(Rr, 'rete')
t('ordinati per rete: il piu vicino per primo',
  all(Rr['blocchi'][i]['d_se_m'] <= Rr['blocchi'][i + 1]['d_se_m']
      for i in range(len(Rr['blocchi']) - 1)),
  str([b['d_se_m'] for b in Rr['blocchi']]), grave=True)
t('la stampa mostra la colonna della rete', 'SE km' in PF.print_portafoglio(Rr),
  grave=True)

# Overpass muto: NON deve produrre distanze, e NON deve sembrare "vicino"
Rm = PF.costruisci(A, adj, target_ha=20.0, n_max=2, comune='Muta', verbose=False)
Dm = RT.distanze_multi({b['sito']: [(41.3, 14.7)] for b in Rm['blocchi']},
                       _fetch=lambda q: None)
t('rete muta: nessun gruppo risulta verificato',
  not any(v.get('verificato') for v in Dm.values()), str(Dm), grave=True)
PF.arricchisci_rete(Rm, verbose=False, _distanze=Dm)
t('i blocchi restano rete_verificata=False',
  not any(b['rete_verificata'] for b in Rm['blocchi']), grave=True)
t('e un avviso dice che NON e "vicino", e che non si sa',
  any('non significa vicini' in a for a in Rm['avvisi']), str(Rm['avvisi']), grave=True)
Rm = PF.classifica(Rm, 'rete')
t('ordinando per rete i non misurati NON finiscono davanti',
  all(b.get('d_se_m') is None for b in Rm['blocchi']), grave=True)

# blocco oltre i 3 km: avviso
Dlont = {b['sito']: {'verificato': True, 'd_se_m': 8200, 'd_linea_m': 7000,
                     'linea_kv': 150} for b in Rm['blocchi']}
Rl = PF.costruisci(A, adj, target_ha=20.0, n_max=2, comune='Muta', verbose=False)
PF.arricchisci_rete(Rl, verbose=False, _distanze=Dlont)
t('oltre il raggio scatta l avviso sul cavidotto',
  any('cavidotto' in a for a in Rl['avvisi']), str(Rl['avvisi']), grave=True)
Dvic = {b['sito']: {'verificato': True, 'd_se_m': 900, 'd_linea_m': 400,
                    'linea_kv': 150} for b in Rm['blocchi']}
Rv = PF.costruisci(A, adj, target_ha=20.0, n_max=2, comune='Muta', verbose=False)
PF.arricchisci_rete(Rv, verbose=False, _distanze=Dvic)
t('controprova: a 900 m nessun avviso di distanza',
  not any('cavidotto' in a for a in Rv['avvisi']), str(Rv['avvisi']), grave=True)

print()
print('[5-ter] una DIRETTIVA e un vincolo, non una preferenza')

# Il difetto che Valerio ha segnalato il 12/08: si dice "la terra di famiglia
# deve esserci TUTTA" e il tool restituisce blocchi che ne lasciano fuori un
# pezzo, con un avviso in coda. Un avviso in coda a un risultato sbagliato e'
# peggio di un errore: il risultato si usa lo stesso, l'avviso si legge dopo.
try:
    PF.costruisci(AA, adjA, target_ha=20.0, n_max=2, ancore=[0, 1, lontana],
                  comune='Ancore', verbose=False, ancore_obbligatorie=True)
    alzata = False
except PF.DirettivaNonRispettata as e:
    alzata = True
    msg = str(e)
t('con ancore_obbligatorie NON restituisce un risultato parziale', alzata, grave=True)
t("e l'errore dice QUALI ancore restano fuori", alzata and '99_1' in msg,
  msg if alzata else '', grave=True)
t('e indica le tre strade per uscirne',
  alzata and 'copri_ancore' in msg and 'n_max' in msg and 'target_ha' in msg,
  msg if alzata else '', grave=True)
t('senza il flag invece esce un risultato con avviso (comportamento precedente)',
  any('copri_ancore' in a for a in
      PF.costruisci(AA, adjA, target_ha=20.0, n_max=2, ancore=[0, 1, lontana],
                    comune='Ancore', verbose=False)['avvisi']), grave=True)
try:
    Rok2 = PF.costruisci(A, adj, target_ha=20.0, n_max=3, ancore=[0, 1],
                         comune='Prova', verbose=False, ancore_obbligatorie=True)
    passata = True
except PF.DirettivaNonRispettata:
    passata = False
t('controprova: se le ancore ci stanno tutte, non alza nulla', passata, grave=True)
t('e lo registra nel risultato', passata and Rok2['ancore_obbligatorie'] is True,
  grave=True)
try:
    PF.costruisci(A, adj, target_ha=20.0, n_max=2, comune='Prova', verbose=False,
                  ancore_obbligatorie=True)
    alzata2 = False
except PF.DirettivaNonRispettata:
    alzata2 = True
t('e la direttiva senza ancore alza subito: non si finge di rispettarla',
  alzata2, grave=True)

print()
print('[7-bis] un blocco che costa quaranta firme viene detto, non nascosto')

# 44 particelle da 0,5 ha in fila: 22 ha veri, ma una controparte ogni 5.000 mq.
PF40 = [{'fg': '77', 'pla': str(i), 'ha': 0.5, 'netti': 0.5,
         'poly': quadrato(0, i)} for i in range(44)]
A40 = {'ammesse': PF40}
R7 = PF.costruisci(A40, BL.adiacenza(A40), target_ha=20.0, n_max=1,
                   comune='Caro', verbose=False)
t('il blocco esiste', R7['n_blocchi'] == 1, str(R7['n_blocchi']), grave=True)
t('ma ha/firma e sotto la soglia',
  R7['blocchi'][0]['ha_per_firma'] < PF.HA_PER_FIRMA_MIN,
  str(R7['blocchi'][0]['ha_per_firma']), grave=True)
t('e c e un avviso sul costo di aggregazione',
  any('controparti per ettaro' in a for a in R7['avvisi']), str(R7['avvisi']),
  grave=True)
t("l'avviso dichiara che la soglia e STIMATA",
  any('STIMATA' in a for a in R7['avvisi']), str(R7['avvisi']), grave=True)
t('ma il blocco NON viene scartato: resta nel portafoglio',
  R7['ha_in_blocchi'] >= 20.0, str(R7['ha_in_blocchi']), grave=True)
Rok = PF.costruisci(A, adj, target_ha=20.0, n_max=1, comune='Prova', verbose=False)
t('controprova: con particelle grandi non scatta nessun avviso di costo',
  not any('controparti per ettaro' in a for a in Rok['avvisi']), str(Rok['avvisi']),
  grave=True)

print('\n[8] unire portafogli diversi: la sovrapposizione si DICHIARA')

X = PF.costruisci(A, adj, target_ha=20.0, n_max=2, comune='Uno', verbose=False)
Y = PF.costruisci(A, adj, target_ha=20.0, n_max=2, comune='Due', verbose=False)
U = PF.unisci([X, Y], comune='Unito')
t('i blocchi si sommano', U['n_blocchi'] == X['n_blocchi'] + Y['n_blocchi'],
  str(U['n_blocchi']), grave=True)
t('la sovrapposizione fra portafogli viene trovata', U['sovrapposizioni'] != {},
  str(len(U['sovrapposizioni'])), grave=True)
t('e finisce negli avvisi in chiaro',
  any('portafogli diversi' in a for a in U['avvisi']), str(U['avvisi']), grave=True)
t('ma NON viene risolta di nascosto',
  U['ha_in_blocchi'] == round(X['ha_in_blocchi'] + Y['ha_in_blocchi'], 2),
  f"{U['ha_in_blocchi']}", grave=True)
Z = PF.unisci([X], comune='Solo')
t('controprova: un portafoglio solo non ha sovrapposizioni', Z['sovrapposizioni'] == {},
  str(Z['sovrapposizioni']), grave=True)

print('\n[9] pool vuoto e pool minuscolo: niente eccezioni, niente numeri finti')

V = PF.costruisci({'ammesse': []}, target_ha=20.0, n_max=3, verbose=False)
t('pool vuoto: zero blocchi', V['n_blocchi'] == 0, str(V['n_blocchi']), grave=True)
t('e zero, non NaN, sulle percentuali', V['pct_pool_usato'] == 0.0,
  str(V['pct_pool_usato']), grave=True)
t('con motivo esplicito', 'esaurito' in V['motivo_stop'], V['motivo_stop'])
PM = griglia(1, 2)
RM = PF.costruisci({'ammesse': PM}, target_ha=50.0, n_max=3, verbose=False)
t('pool troppo piccolo per il target: nessun blocco inventato', RM['n_blocchi'] == 0,
  str(RM['n_blocchi']), grave=True)
t('e il residuo e tutto il pool', abs(RM['ha_residuo'] - RM['ha_pool']) < 0.05,
  f"{RM['ha_residuo']} vs {RM['ha_pool']}", grave=True)

print('\n[10] salva e ricarica senza perdere niente')

p = os.path.join(tempfile.mkdtemp(), 'pf.json')
PF.salva(R, p)
R9 = PF.carica(p)
t('il file torna uguale', R9['n_blocchi'] == R['n_blocchi']
  and R9['ha_in_blocchi'] == R['ha_in_blocchi'], grave=True)
t('e le particelle ci sono ancora',
  sum(len(b['particelle']) for b in R9['blocchi'])
  == sum(len(b['particelle']) for b in R['blocchi']), grave=True)
t('il riepilogo si stampa', 'PORTAFOGLIO' in PF.print_portafoglio(R9))
t('e mostra il residuo', 'residuo' in PF.print_portafoglio(R2))

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
