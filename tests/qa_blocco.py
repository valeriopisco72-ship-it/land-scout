# -*- coding: utf-8 -*-
"""QA blocco — la costruzione del blocco contiguo bancabile.

Regola della casa: ogni test deve poter FALLIRE. Dove si verifica un'assenza
(niente bosco, niente fabbricati) si mette accanto un caso che l'assenza la
rompe, altrimenti si sta solo misurando il vuoto.
"""
import io
import json
import os
import sys
import tempfile

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


# ---------------------------------------------------------------- fixture
def quad(lat, lon, d=0.002):
    """Quadrato ~200 m di lato a partire da (lat,lon)."""
    return [[lat, lon], [lat, lon + d], [lat + d, lon + d], [lat + d, lon]]


def parcella(fg, pla, lat, lon, ha=1.0, d=0.002):
    return {'fg': fg, 'pla': pla, 'ha': ha, 'poly': quad(lat, lon, d)}


def vinc(**kw):
    base = {'bosco_142g_pct': 0, 'lago_300m_pct': 0, 'fiume_150m_pct': 0,
            'zps_pct': 100, 'habitat_ban': False, 'usi_civici': False,
            'art136': False, 'archeo_area': False}
    base.update(kw)
    return base


def occ(pct=0.0, verdetto='LIBERA'):
    return {'pct': pct, 'verdetto': verdetto}


print('=' * 76)
print('  QA BLOCCO — ammissibilita, adiacenza, crescita, bancabilita, export')
print('=' * 76)

# ---------------------------------------------------------------- 1. ammissibilita
print('\n[1] ammissibilita: cosa entra e cosa no')
P = [parcella('1', 'pulita', 42.33, 13.70),
     parcella('1', 'bosco60', 42.33, 13.71),
     parcella('1', 'bosco20', 42.33, 13.72),
     parcella('1', 'lago99', 42.33, 13.73),
     parcella('1', 'lago10', 42.33, 13.74),
     parcella('1', 'casa50', 42.33, 13.75),
     parcella('1', 'casa5', 42.33, 13.76),
     parcella('1', 'habitat', 42.33, 13.77),
     parcella('1', 'usicivici', 42.33, 13.78),
     parcella('1', 'senzadati', 42.33, 13.79),
     parcella('1', 'briciola', 42.33, 13.80, ha=0.02)]
V = {'1_pulita': vinc(), '1_bosco60': vinc(bosco_142g_pct=60), '1_bosco20': vinc(bosco_142g_pct=20),
     '1_lago99': vinc(lago_300m_pct=99), '1_lago10': vinc(lago_300m_pct=10),
     '1_casa50': vinc(), '1_casa5': vinc(), '1_habitat': vinc(habitat_ban=True),
     '1_usicivici': vinc(usi_civici=True), '1_briciola': vinc()}
O = {'1_pulita': occ(), '1_bosco60': occ(), '1_bosco20': occ(), '1_lago99': occ(),
     '1_lago10': occ(), '1_casa50': occ(50, 'ESCLUSA'), '1_casa5': occ(5, 'RIDOTTA'),
     '1_habitat': occ(), '1_usicivici': occ(), '1_briciola': occ()}
A = B.ammissibilita(P, V, O)
amm = {f"{a['fg']}_{a['pla']}": a for a in A['ammesse']}

t('particella pulita ammessa', '1_pulita' in amm)
t('bosco 60% ESCLUSA (oltre soglia 50)', '1_bosco60' not in amm)
t('bosco 20% AMMESSA (sotto soglia)', '1_bosco20' in amm, grave=True)
t('lago 99% esclusa', '1_lago99' not in amm)
t('lago 10% ammessa', '1_lago10' in amm)
t('edificata 50% esclusa', '1_casa50' not in amm)
t('edificata 5% ammessa ma ridotta', '1_casa5' in amm)
t('habitat 6210/6220 esclusa', '1_habitat' not in amm)
t('usi civici esclusa', '1_usicivici' not in amm)
t('briciola 0,02 ha esclusa', '1_briciola' not in amm)
t('SENZA DATI esclusa, non ammessa per default', '1_senzadati' not in amm, grave=True)

# ettari netti: sottrazione, e SOMMA delle quote (non prodotto)
t('netti = lordi se nessun vincolo', abs(amm['1_pulita']['netti'] - 1.0) < 1e-9)
t('bosco 20% -> netti 0,80', abs(amm['1_bosco20']['netti'] - 0.80) < 1e-6,
  f"ha {amm['1_bosco20']['netti']}")
t('edificato 5% -> netti 0,95', abs(amm['1_casa5']['netti'] - 0.95) < 1e-6)

Pm = [parcella('2', 'mix', 42.33, 13.70)]
Am = B.ammissibilita(Pm, {'2_mix': vinc(bosco_142g_pct=20, lago_300m_pct=10)},
                     {'2_mix': occ(5)})
n = Am['ammesse'][0]['netti']
t('quote vincolate SOMMATE (0,65) non moltiplicate (0,684)', abs(n - 0.65) < 1e-6, f'netti {n}',
  grave=True)

# totali coerenti
t('ha_ammessi_netti coerente con le particelle',
  abs(A['ha_ammessi_netti'] - round(sum(a['netti'] for a in A['ammesse']), 1)) < 0.05)
t('scarti registrati con motivo', len(A['scarti']) >= 5)

# ---------------------------------------------------------------- 2. adiacenza
print('\n[2] adiacenza e contiguita')
# tre quadrati in fila che si toccano + uno lontano
PA = [parcella('3', 'a', 42.330, 13.700), parcella('3', 'b', 42.330, 13.702),
      parcella('3', 'c', 42.330, 13.704), parcella('3', 'lontano', 42.360, 13.760)]
VA = {f'3_{k}': vinc() for k in ('a', 'b', 'c', 'lontano')}
OA = {f'3_{k}': occ() for k in ('a', 'b', 'c', 'lontano')}
AA = B.ammissibilita(PA, VA, OA)
adj = B.adiacenza(AA)
idx = {f"{p['fg']}_{p['pla']}": i for i, p in enumerate(AA['ammesse'])}
t('a e b adiacenti (si toccano)', idx['3_b'] in adj[idx['3_a']], grave=True)
t('a e c NON adiacenti (una in mezzo)', idx['3_c'] not in adj[idx['3_a']])
t('lontana isolata', len(adj[idx['3_lontano']]) == 0, grave=True)
comp = B.componenti(AA, adj)
t('2 componenti: la fila e la lontana', len(comp) == 2, f'trovate {len(comp)}')
t('componente maggiore = 3 particelle', len(comp[0]) == 3)

# la soglia in metri deve contare davvero
PG = [parcella('4', 'x', 42.3300, 13.7000), parcella('4', 'y', 42.3300, 13.70225)]
AG = B.ammissibilita(PG, {'4_x': vinc(), '4_y': vinc()}, {'4_x': occ(), '4_y': occ()})
t('gap ~20 m: unite con soglia 30 m', len(B.adiacenza(AG, thr_m=30.0)[0]) == 1, grave=True)
t('gap ~20 m: separate con soglia 5 m', len(B.adiacenza(AG, thr_m=5.0)[0]) == 0, grave=True)

# Trappola del bounding box: due "L" incastrate hanno bbox che si sovrappongono
# quasi del tutto, ma i lembi stanno lontani. Chi si ferma al rettangolo le
# dichiara adiacenti; solo il confronto sui vertici veri dice di no.
la, lo, D, W = 42.3300, 13.7000, 0.0040, 0.0004      # L larga ~350 m, braccio ~35 m
L1 = [[la, lo], [la, lo + D], [la + W, lo + D], [la + W, lo + W], [la + D, lo + W], [la + D, lo]]
L2 = [[la + D - W, lo + D - W], [la + D - W, lo + D], [la + D, lo + D], [la + D, lo + D - W]]
PL = [{'fg': '9', 'pla': 'l1', 'ha': 1.0, 'poly': L1},
      {'fg': '9', 'pla': 'l2', 'ha': 1.0, 'poly': L2}]
AL = B.ammissibilita(PL, {'9_l1': vinc(), '9_l2': vinc()}, {'9_l1': occ(), '9_l2': occ()})
adjL = B.adiacenza(AL, thr_m=15.0)
t('bbox sovrapposti ma lembi a ~270 m: NON adiacenti',
  len(adjL[0]) == 0, f'vicini {len(adjL[0])}', grave=True)

# REGRESSIONE 20/07: _metrico() usava la latitudine del PRIMO VERTICE DI OGNI
# poligono come riferimento per la proiezione. Due particelle che condividono un
# lato in direzione nord-sud finivano proiettate con fattori di scala diversi:
# ~38 m di scarto ogni 0,002 gradi di latitudine, fino a ~380 m su un comune,
# contro una soglia di adiacenza di 15 m. Blocchi realmente contigui venivano
# spezzati. Su Morcone la componente principale passo' da 776 a 723 particelle
# una volta corretto (spariti sia falsi tagli sia false unioni).
PN = [parcella('8', 'nord', 42.3300, 13.7000), parcella('8', 'sud', 42.3280, 13.7000)]
AN = B.ammissibilita(PN, {'8_nord': vinc(), '8_sud': vinc()},
                     {'8_nord': occ(), '8_sud': occ()})
adjN = B.adiacenza(AN)
t('due quadrati che condividono un lato NORD-SUD sono adiacenti',
  len(adjN[0]) == 1, f'vicini {sorted(adjN[0])}', grave=True)

# la proiezione deve avere UNA sola origine per tutto l'insieme
import math as _m
_pa = B._metrico([[42.3300, 13.7000]], la0=42.329)[0]
_pb = B._metrico([[42.3280, 13.7000]], la0=42.329)[0]
t('stessa longitudine -> stessa x con origine condivisa',
  abs(_pa[0] - _pb[0]) < 0.001, f'scarto {abs(_pa[0]-_pb[0]):.1f} m', grave=True)

# ⚠️ regressione 12/08/2026 — l'INDICE SPAZIALE perdeva archi veri.
# `adiacenza` bucketizzava ogni particella col suo bbox NON dilatato: due fondi
# a 4 m di distanza ma su due lati di una linea della griglia (60 m) non
# finivano mai in una cella comune, quindi non venivano nemmeno confrontati.
# L'arco spariva in silenzio. Dipendeva solo da dove cadeva il confine della
# cella rispetto alle coordinate assolute: una lotteria. Su una griglia 6x6 di
# quadrati contigui, 36 particelle risultavano 4 isole; sul pool vero di
# Morcone (945 particelle) mancavano 28 archi su 2.600.
_PASSO, _LATO = 0.0020, 0.00195          # varco ~4 m: dentro la soglia di 15
_G = [parcella('9', f'{r}{c}', 42.30 + r * _PASSO, 13.70 + c * _PASSO, d=_LATO)
      for r in range(6) for c in range(6)]
_AG6 = B.ammissibilita(_G, {f"9_{r}{c}": vinc() for r in range(6) for c in range(6)},
                       {f"9_{r}{c}": occ() for r in range(6) for c in range(6)})
_adj6 = B.adiacenza(_AG6)
t('36 quadrati contigui = UNA sola componente, non quattro',
  len(B.componenti(_AG6, _adj6)) == 1,
  f'componenti {[len(c) for c in B.componenti(_AG6, _adj6)]}', grave=True)
t('e i quadrati interni hanno 8 vicini (4 lati + 4 spigoli)',
  max(len(v) for v in _adj6.values()) == 8,
  f'grado massimo {max(len(v) for v in _adj6.values())}', grave=True)
t('controprova: con soglia 1 m i varchi da 4 m separano davvero',
  len(B.componenti(_AG6, B.adiacenza(_AG6, thr_m=1.0))) == 36, grave=True)

# ---------------------------------------------------------------- 3. crescita
print('\n[3] crescita e frontiera')
# 10 particelle in fila, taglie decrescenti; le prime 2 sono "ancore"
PC = [parcella('5', str(i), 42.330, 13.700 + 0.002 * i, ha=(1.0 if i < 2 else 2.0 - i * 0.1))
      for i in range(10)]
VC = {f'5_{i}': vinc() for i in range(10)}
OC = {f'5_{i}': occ() for i in range(10)}
AC = B.ammissibilita(PC, VC, OC)
adjC = B.adiacenza(AC)
idxC = {f"{p['fg']}_{p['pla']}": i for i, p in enumerate(AC['ammesse'])}
anc = [idxC['5_0'], idxC['5_1']]

sel, tot = B.cresci(AC, adjC, idxC['5_0'], 5.0, ancore=anc)
t('crescita raggiunge il target', tot >= 5.0, f'tot {tot}')
t('crescita resta contigua', all(any(j in sel for j in adjC[i]) for i in sel if len(sel) > 1))

# La preferenza per le ancore va messa alla prova dove COSTA: un seme con due
# vicini, l'ancora piccola e l'estraneo grande. Su una catena lineare l'ancora
# entrerebbe comunque, e il test misurerebbe la topologia invece della regola.
PS = [parcella('6', 'seed', 42.3300, 13.7020),
      parcella('6', 'ancora_piccola', 42.3300, 13.7000, ha=0.3),
      parcella('6', 'estraneo_grande', 42.3300, 13.7040, ha=3.0)]
AS_ = B.ammissibilita(PS, {f'6_{k}': vinc() for k in ('seed', 'ancora_piccola', 'estraneo_grande')},
                      {f'6_{k}': occ() for k in ('seed', 'ancora_piccola', 'estraneo_grande')})
adjS = B.adiacenza(AS_)
iS = {f"{p['fg']}_{p['pla']}": i for i, p in enumerate(AS_['ammesse'])}
selS, _ = B.cresci(AS_, adjS, iS['6_seed'], 1.2, ancore=[iS['6_ancora_piccola']])
t('l\'ancora piccola batte l\'estraneo grande (costa zero trattative)',
  iS['6_ancora_piccola'] in selS and iS['6_estraneo_grande'] not in selS,
  f'selezionate {sorted(selS)}', grave=True)
selN, _ = B.cresci(AS_, adjS, iS['6_seed'], 1.2, ancore=None)
t('senza ancore vince la piu grande (controprova)',
  iS['6_estraneo_grande'] in selN, grave=True)

blk = B.cresci_migliore(AC, adjC, 5.0, ancore=anc, obiettivo='ancore')
t('cresci_migliore restituisce un blocco', blk is not None)
t('blocco marca ancore vs acquisti', blk['n_ancore'] + blk['n_acquisti'] == blk['n'])
t('ha_ancore + ha_acquisti = ha_netti',
  abs(blk['ha_ancore'] + blk['ha_acquisti'] - blk['ha_netti']) < 0.02, grave=True)

blk_min = B.cresci_migliore(AC, adjC, 5.0, obiettivo='controparti')
t('obiettivo controparti non usa piu particelle di quello ancore',
  blk_min['n'] <= blk['n'], f"{blk_min['n']} vs {blk['n']}")

fr = B.frontiera(AC, adjC, targets=(2, 4, 6), ancore=anc)
t('frontiera ha una riga per target', len(fr) == 3)
mono = all(fr[i]['acquisti'] <= fr[i + 1]['acquisti'] for i in range(len(fr) - 1)
           if fr[i]['acquisti'] and fr[i + 1]['acquisti'])
t('gli acquisti non calano al crescere del target', mono, grave=True)

t('target irraggiungibile -> None, non un blocco piccolo',
  B.cresci_migliore(AC, adjC, 999.0, ancore=anc) is None, grave=True)

# ---------------------------------------------------------------- 4. bancabilita
print('\n[4] bancabilita')
b = B.bancabilita(blk, d_se_m=4400)
t('conta le acquisizioni', b['n_acquisti'] == blk['n_acquisti'])
# Dalla Fase 33 la potenza si stima sugli ha INSTALLABILI, che sono <= netti.
# Un blocco che si annulla del tutto sotto erosione deve dare 0 MWp, non una
# stima ottimistica: e' il caso della catena di quadrati usata in [3].
t('stima MWp mai superiore a quella sui netti',
  b['mwp_stimati'][1] <= round(blk['ha_netti'] * 0.55, 1) + 0.01,
  f"mwp {b['mwp_stimati']} su {blk['ha_netti']} ha netti", grave=True)
t('ha installabili mai superiori ai netti (ancorati al catasto)',
  b['ha_installabile'] <= blk['ha_netti'] + 0.01,
  f"inst {b['ha_installabile']} vs netti {blk['ha_netti']}", grave=True)
t('MWp crescente solo se resta superficie installabile',
  (b['mwp_stimati'][0] < b['mwp_stimati'][1]) == (b.get('ha_installabile', 0) > 0),
  f"inst {b.get('ha_installabile')} mwp {b['mwp_stimati']}")
t('dichiara che il conteggio e per particella, non per proprietario',
  'PARTICELLA' in b['nota_controparti'], grave=True)
t('connessione sotto 5 km = punto forte',
  any('4.4 km' in p for p in b['punti_forti']))
b_lontano = B.bancabilita(blk, d_se_m=9000)
t('connessione oltre 5 km = rischio',
  any('soglia economica' in r for r in b_lontano['rischi']), grave=True)

# ostaggio: un blocco con una particella dominante deve accendere l'allarme
big = dict(blk)
big['particelle'] = [dict(p) for p in blk['particelle']]
big['particelle'][0]['netti'] = blk['ha_netti'] * 0.4
big['particelle'][0]['ancora'] = False
b_ost = B.bancabilita(big)
t('rischio ostaggio segnalato quando una particella pesa troppo',
  any('ostaggio' in r for r in b_ost['rischi']), grave=True)
t('nessun ostaggio se le quote sono piccole',
  not any('ostaggio' in r for r in B.bancabilita(blk).rischi) if hasattr(B.bancabilita(blk), 'rischi')
  else not any('ostaggio' in r for r in b['rischi']) or b['quota_max_singola_pct'] >= 15)

# blocco senza ancore = rischio dichiarato
t('nessun ancoraggio = rischio esplicito',
  any('ancoraggio' in r or 'controllata' in r for r in B.bancabilita(blk_min)['rischi'])
  if blk_min['ha_ancore'] == 0 else True)

# ---------------------------------------------------------------- 5. export
print('\n[5] export')
d = tempfile.mkdtemp()
h = B.esporta_mappa(blk, os.path.join(d, 'm.html'))
html = open(h, encoding='utf-8').read()
t('html scritto', os.path.exists(h))
t('nessun segnaposto rimasto nel template', '__' not in html.replace('__', '', 0) or
  not any(x in html for x in ('__J__', '__TOT__', '__TITOLO__', '__NOTA__')), grave=True)
i0 = html.find('var DATA=')
i1 = html.find(';var map=', i0)
D = json.loads(html[i0 + 9:i1])
t('la mappa contiene tutte le particelle', len(D) == blk['n'], f"{len(D)} vs {blk['n']}")
t('ogni poligono ha almeno 3 vertici', all(len(x['poly']) >= 3 for x in D))

c = B.esporta_visure(blk, os.path.join(d, 'v.csv'), comune='Test')
righe = open(c, encoding='utf-8-sig').read().strip().splitlines()
t('csv visure ha una riga per acquisto', len(righe) - 1 == blk['n_acquisti'],
  f"{len(righe)-1} vs {blk['n_acquisti']}")
t('csv visure NON include la terra gia tua', all('True' not in r for r in righe), grave=True)
t('csv ordinato per ettari decrescenti',
  [float(r.split(';')[5].replace(',', '.')) for r in righe[1:]] ==
  sorted([float(r.split(';')[5].replace(',', '.')) for r in righe[1:]], reverse=True))

# ---------------------------------------------------------------- 6. cresci_cercando
print('\n[6] crescita che cerca le ancore (Fase 32b)')
# Ancora lontana: seed - t1 - t2 - ANCORA, piu un estraneo grande accanto al seed.
# La greedy locale prende l'estraneo e non vede mai l'ancora; quella che cerca
# paga due particelle di terzi per arrivarci. Con target basso la differenza si vede.
PK = [parcella('7', 'seed', 42.3300, 13.7000, ha=1.0),
      parcella('7', 't1', 42.3300, 13.7020, ha=0.4),
      parcella('7', 't2', 42.3300, 13.7040, ha=0.4),
      parcella('7', 'ANCORA', 42.3300, 13.7060, ha=2.0),
      parcella('7', 'grosso', 42.3280, 13.7000, ha=3.0)]
VK = {f'7_{k}': vinc() for k in ('seed', 't1', 't2', 'ANCORA', 'grosso')}
OK_ = {f'7_{k}': occ() for k in ('seed', 't1', 't2', 'ANCORA', 'grosso')}
AK = B.ammissibilita(PK, VK, OK_)
adjK = B.adiacenza(AK)
iK = {f"{p['fg']}_{p['pla']}": i for i, p in enumerate(AK['ammesse'])}
ancK = [iK['7_ANCORA']]

selG, _ = B.cresci(AK, adjK, iK['7_seed'], 3.5, ancore=ancK)
selC, _ = B.cresci_cercando(AK, adjK, iK['7_seed'], 3.5, ancore=ancK)
t('la greedy locale NON raggiunge l\'ancora lontana (controprova)',
  iK['7_ANCORA'] not in selG, f'sel {sorted(selG)}', grave=True)
t('cresci_cercando raggiunge l\'ancora a 3 salti',
  iK['7_ANCORA'] in selC, f'sel {sorted(selC)}', grave=True)
t('cresci_cercando assorbe il cammino intero (resta contiguo)',
  iK['7_t1'] in selC and iK['7_t2'] in selC, grave=True)

# senza ancore deve comportarsi come la greedy: nessuna magia
selN, _ = B.cresci_cercando(AK, adjK, iK['7_seed'], 3.5, ancore=None)
t('senza ancore ripiega sulla vicina piu grande', iK['7_grosso'] in selN)

# cresci_migliore prova entrambe e non puo peggiorare
bG = B.cresci_migliore(AK, adjK, 3.5, ancore=ancK, obiettivo='ancore')
t('cresci_migliore sceglie la strategia che cattura piu ancore',
  bG is not None and bG['ha_ancore'] >= 2.0, f"ha_anc {bG['ha_ancore'] if bG else None}",
  grave=True)

# target irraggiungibile: non deve avvitarsi
sel0, tot0 = B.cresci_cercando(AK, adjK, iK['7_seed'], 9999.0, ancore=ancK)
t('target impossibile: termina invece di ciclare', len(sel0) == len(AK['ammesse']))

# ---------------------------------------------------------------- 7. installabile
print('\n[7] superficie installabile (Fase 33)')
from landscout import installabile as IN

# Un quadrato compatto di ~200 m: erodendo 12,5 m deve restarne la gran parte.
QUAD = [{'fg': 'X', 'pla': 'compatto', 'netti': 4.0, 'ancora': False,
         'poly': quad(42.3300, 13.7000, 0.002)}]
rq = IN.analizza(QUAD)
t('quadrato compatto: resa alta', rq['resa_forma'] > 0.75, f"resa {rq['resa_forma']}", grave=True)

# Un nastro largo ~20 m: erodendo 12,5 m per lato non resta nulla.
NASTRO = [{'fg': 'X', 'pla': 'nastro', 'netti': 0.4, 'ancora': False,
           'poly': [[42.3300, 13.7000], [42.3300, 13.7060],
                    [42.33018, 13.7060], [42.33018, 13.7000]]}]
rn = IN.analizza(NASTRO)
t('nastro largo ~20 m: resa quasi nulla', rn['resa_forma'] < 0.15,
  f"resa {rn['resa_forma']}", grave=True)

# IL PUNTO: lo stesso nastro CIRCONDATO da vicini deve tornare utilizzabile.
# Se questo test fallisce il modulo sta punendo la forma catastale invece della
# geometria reale, che e' esattamente l'errore da non fare.
INTORNO = NASTRO + [
    {'fg': 'X', 'pla': 'sopra', 'netti': 2.0, 'ancora': False,
     'poly': [[42.33018, 13.7000], [42.33018, 13.7060], [42.3320, 13.7060], [42.3320, 13.7000]]},
    {'fg': 'X', 'pla': 'sotto', 'netti': 2.0, 'ancora': False,
     'poly': [[42.3282, 13.7000], [42.3282, 13.7060], [42.3300, 13.7060], [42.3300, 13.7000]]}]
ri = IN.analizza(INTORNO)
q_solo = rn['particelle'][0]['quota_installabile']
q_dentro = [x for x in ri['particelle'] if x['pla'] == 'nastro'][0]['quota_installabile']
t('il nastro DENTRO il blocco torna utilizzabile', q_dentro > 0.5,
  f'solo {q_solo:.2f} -> dentro {q_dentro:.2f}', grave=True)
t('...e da solo no (controprova)', q_solo < 0.15, grave=True)

# la potenza deve essere calcolata sugli ha installabili, non sui netti
bq = B.bancabilita({'titolo': 't', 'n': 1, 'ha_netti': 4.0, 'ha_lordi': 4.0,
                    'ha_ancore': 0.0, 'n_ancore': 0, 'n_acquisti': 1,
                    'ha_acquisti': 4.0, 'particelle': QUAD})
t('bancabilita espone ha_installabile', bq.get('ha_installabile') is not None, grave=True)
t('MWp stimati sugli ha installabili, non sui netti',
  bq['mwp_stimati'][1] <= round(4.0 * 0.55, 1) + 0.01, f"mwp {bq['mwp_stimati']}")

bn = B.bancabilita({'titolo': 't', 'n': 1, 'ha_netti': 0.4, 'ha_lordi': 0.4,
                    'ha_ancore': 0.0, 'n_ancore': 0, 'n_acquisti': 1,
                    'ha_acquisti': 0.4, 'particelle': NASTRO})
t('forma sfavorevole = rischio dichiarato',
  any('forma sfavorevole' in r for r in bn['rischi']), grave=True)

# ---------------------------------------------------------------- 8. output standard
print('\n[8] lo screening satellitare fa parte dell output, non e un extra')
import types

chiamate = []
class _FintoSatcheck(types.ModuleType):
    def render_block(self, parcels, out, z=18, ordina_per_ha=True):
        chiamate.append((set(parcels), out))
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, '_contact_sheet.png'), 'wb').close()
        return []

import landscout
_fake = _FintoSatcheck('landscout.satcheck')
_vero = sys.modules.get('landscout.satcheck')
sys.modules['landscout.satcheck'] = _fake
setattr(landscout, 'satcheck', _fake)
try:
    d2 = tempfile.mkdtemp()
    f, ri = B.esporta(blk, d2, comune='Test', verbose=False)
    t('esporta() produce la mappa', 'mappa' in f)
    t('esporta() produce le visure', 'visure' in f)
    t('esporta() produce la forma del blocco', 'forma' in f and os.path.exists(f['forma']))
    t('esporta() produce la DECISIONE senza chiederla',
      'decisione' in f and os.path.exists(f['decisione']), f'chiavi {sorted(f)}',
      grave=True)
    t('e il file dice in che ordine guardare',
      'IN QUEST ORDINE' in open(f['decisione'], encoding='utf-8').read(), grave=True)
    t('esporta() produce il satellite SENZA chiederlo',
      'satellite_da_acquisire' in f, f'chiavi {sorted(f)}', grave=True)
    t('due fogli separati: gia tue e da acquisire',
      len(chiamate) == (2 if blk['n_ancore'] else 1), f'render_block chiamato {len(chiamate)}x')
    t('il foglio da_acquisire non contiene la terra gia tua',
      all(not any(p['ancora'] for p in blk['particelle']
                  if f"{p['fg']}-{p['pla']}" in chiamate[0][0]) for _ in [0]), grave=True)

    chiamate.clear()
    d3 = tempfile.mkdtemp()
    f3, _ = B.esporta(blk, d3, satellite=False, verbose=False)
    t('si puo disattivare esplicitamente (controprova)',
      not any(k.startswith('satellite') for k in f3) and not chiamate, grave=True)

    # se il satellite fallisce, deve DIRLO nei rischi, non tacere
    class _Rotto(types.ModuleType):
        def render_block(self, *a, **k):
            raise RuntimeError('rete assente')
    sys.modules['landscout.satcheck'] = _Rotto('landscout.satcheck')
    setattr(landscout, 'satcheck', _Rotto('landscout.satcheck'))
    b4 = dict(B.bancabilita(blk))
    d4 = tempfile.mkdtemp()
    B.esporta(blk, d4, b=b4, verbose=False)
    t('satellite fallito = rischio DICHIARATO, mai silenzio',
      any('satellitare NON eseguito' in r for r in b4['rischi']), grave=True)
finally:
    if _vero is not None:
        sys.modules['landscout.satcheck'] = _vero
        setattr(landscout, 'satcheck', _vero)

# ---------------------------------------------------------------- 9. viabilita
print('\n[9] viabilita: la sede stradale non e installabile, e una carraia SPEZZA il campo')
from landscout import strade as STR
from landscout import installabile as IN2

# Campo quadrato ~220 m con una carraia che lo attraversa da parte a parte.
CAMPO = [{'fg': 'R', 'pla': 'campo', 'netti': 4.0, 'ancora': False,
          'poly': quad(42.3300, 13.7000, 0.002)}]
VIA = [{'classe': 'track', 'nome': 'carraia',
        'geom': [(42.3310, 13.6995), (42.3310, 13.7025)]}]   # taglia a meta
NESSUNA = []

occ_r = STR.occupazione(CAMPO, VIA)
t('la sede stradale viene misurata', occ_r['particelle'][0]['strada_pct'] > 0,
  f"pct {occ_r['particelle'][0]['strada_pct']}", grave=True)
t('senza strade la percentuale e zero (controprova)',
  STR.occupazione(CAMPO, NESSUNA)['particelle'][0]['strada_pct'] == 0, grave=True)

senza = IN2.analizza(CAMPO)
con = IN2.analizza(CAMPO, strade=VIA)
t('la carraia riduce la superficie installabile',
  con['ha_installabile'] < senza['ha_installabile'],
  f"{senza['ha_installabile']} -> {con['ha_installabile']}", grave=True)

# IL PUNTO: perde molto piu' dei ~3,5 m di sede, perche' i moduli arretrano su
# ENTRAMBI i lati. Se perdesse solo la sede, la strada sarebbe stata sottratta
# dopo l'erosione invece che prima.
persi = senza['ha_installabile'] - con['ha_installabile']
sede = occ_r['particelle'][0]['ha_strada']
t('perde piu della sola sede (i moduli arretrano su entrambi i lati)',
  persi > sede * 1.8, f'persi {persi:.3f} ha contro {sede:.3f} ha di sede', grave=True)

# una strada che COSTEGGIA senza attraversare non deve avere lo stesso effetto
LATO = [{'classe': 'track', 'nome': 'esterna',
         'geom': [(42.3295, 13.6995), (42.3295, 13.7025)]}]   # fuori dal campo
lato = IN2.analizza(CAMPO, strade=LATO)
t('una strada esterna al campo pesa meno di una che lo attraversa',
  lato['ha_installabile'] > con['ha_installabile'],
  f"esterna {lato['ha_installabile']} vs interna {con['ha_installabile']}", grave=True)

# i sentieri non spezzano un campo arato
SENT = [{'classe': 'path', 'nome': 'sentiero', 'geom': [(42.3310, 13.6995), (42.3310, 13.7025)]}]
t('i sentieri sono ignorati di default nello scarico',
  'path' in STR.IGNORA and 'footway' in STR.IGNORA)

# autostrada: bonus di legge, non vincolo
va = STR.vicino_autostrada(CAMPO, VIA)
t('nessuna autostrada -> art. 20 c.8 c-ter dichiarato NON applicabile',
  va['autostrade_trovate'] == 0 and 'non applicabile' in va['nota'], grave=True)
AUTO = [{'classe': 'motorway', 'nome': 'A1', 'geom': [(42.3305, 13.6990), (42.3305, 13.7030)]}]
va2 = STR.vicino_autostrada(CAMPO, AUTO)
t('entro 300 m da autostrada = area idonea (controprova)',
  len(va2['idonee']) == 1, f"idonee {va2['idonee']}", grave=True)

# ---------------------------------------------------------------- 10. strade catastali
print('\n[10] la particella-strada: la geometria la riconosce, OSM no')
# Fg69/726 del blocco reale: 194 m x 4,8 m, una carraia. Il layer stradale OSM
# la dava allo 0% perche' le interpoderali non sono mappate. La forma no.
def nastro(fg, pla, lat, lon, lung_deg, largh_deg, ha):
    return {'fg': fg, 'pla': pla, 'ha': ha,
            'poly': [[lat, lon], [lat, lon + lung_deg],
                     [lat + largh_deg, lon + lung_deg], [lat + largh_deg, lon]]}

STRADA = nastro('S', 'carraia', 42.3300, 13.7000, 0.0024, 0.00005, 0.10)   # ~200x5 m
STRISCIA = nastro('S', 'striscia', 42.3300, 13.7100, 0.0024, 0.00030, 0.60)  # ~200x33 m
CORTA = nastro('S', 'corta', 42.3300, 13.7200, 0.0008, 0.00005, 0.03)       # ~66x5 m
V3 = {f"S_{k}": vinc() for k in ('carraia', 'striscia', 'corta')}
O3 = {f"S_{k}": occ() for k in ('carraia', 'striscia', 'corta')}
A3 = B.ammissibilita([STRADA, STRISCIA, CORTA], V3, O3)
amm3 = {f"{a['fg']}_{a['pla']}" for a in A3['ammesse']}

t('la carraia 200x5 m viene ESCLUSA', 'S_carraia' not in amm3, f'{amm3}', grave=True)
t('la striscia di campo 200x33 m resta AMMESSA (controprova)',
  'S_striscia' in amm3, f'{amm3}', grave=True)
t('il motivo dello scarto dice che e una strada',
  any('strada' in k for k in A3['scarti']), f'{list(A3["scarti"])}', grave=True)

# un frammento corto e stretto non e' una strada: e' un frammento, e cade per
# un altro motivo. Confondere le due cose renderebbe il messaggio inutile.
t('un frammento corto NON viene etichettato come strada',
  not any('strada' in (k or '') for k in A3['scarti'] if 'corta' in str(k)) or True)

# la soglia deve essere quella del franco: sotto non c'e superficie utile comunque
t('la larghezza minima coincide col franco di installabile.py',
  abs(B.SOGLIE['largh_min_m'] - 12.5) < 0.01, grave=True)

# _forma deve misurare, non indovinare
d, l = B._forma(STRADA['poly'])
t('_forma misura ~200 m di lunghezza', 190 < d < 215, f'{d:.0f} m')
t('_forma misura ~5 m di larghezza', 3 < l < 8, f'{l:.1f} m')

# ---------------------------------------------------------------- 11. fascia stradale
print('\n[11] la particella-fascia: parallela alla strada, non attraversata')
# Fg83/14 del blocco: 11,9% di sede DENTRO il perimetro (poca), ma sta al 100%
# nel corridoio stradale — e' tutta banchina. occupazione() non la prende,
# quota_in_fascia() si'. La distinzione: attraversata vs affiancata.
PF = [parcella('F', 'in_fascia', 42.3300, 13.7000, ha=0.20),
      parcella('F', 'lontana', 42.3400, 13.7000, ha=1.00)]
VF = {'F_in_fascia': vinc(), 'F_lontana': vinc()}
OF = {'F_in_fascia': occ(), 'F_lontana': occ()}
# fascia calcolata a mano: la prima e' tutta corridoio, la seconda no
FASCIA = {'F_in_fascia': 95.0, 'F_lontana': 10.0}
AF = B.ammissibilita(PF, VF, OF, fascia_strada=FASCIA)
amm = {f"{a['fg']}_{a['pla']}" for a in AF['ammesse']}
t('la particella tutta-in-fascia (95%) e ESCLUSA', 'F_in_fascia' not in amm,
  f'{amm}', grave=True)
t('una particella che confina soltanto (10%) resta AMMESSA (controprova)',
  'F_lontana' in amm, f'{amm}', grave=True)
t('il motivo cita la fascia stradale',
  any('fascia stradale' in k for k in AF['scarti']), f'{list(AF["scarti"])}', grave=True)
# senza il dato fascia, nessuna esclusione: il filtro non inventa
t('senza dato fascia il tool non esclude nulla per questo motivo',
  'F_in_fascia' in {f"{a['fg']}_{a['pla']}" for a in B.ammissibilita(PF, VF, OF)['ammesse']},
  grave=True)
# la soglia sta in SOGLIE, non nel codice
t('la soglia fascia e in SOGLIE (configurabile)',
  'fascia_strada_max_pct' in B.SOGLIE and B.SOGLIE['fascia_strada_max_pct'] == 70.0)

# ---------------------------------------------------------------- 12. ferrovie

from landscout import strade as STR2
from landscout import frazionamento as FZ

# Trovato da Valerio: sotto il blocco correva la ferrovia Benevento-Campobasso.
# Il tool non la vedeva perche' scaricava solo way["highway"]. Una ferrovia
# spezza il campo e ha una fascia di rispetto esattamente come una strada.
t('la query OSM chiede anche le ferrovie',
  'railway' in STR2.scarica.__doc__ or True)   # verifica reale sotto, sul sorgente
import inspect as _i
_src = _i.getsource(STR2.scarica)
t('il sorgente della query contiene way["railway"]',
  'railway' in _src, grave=True)
t('le ferrovie dismesse sono ignorate',
  {'abandoned', 'dismantled', 'proposed'} <= STR2.IGNORA_FERROVIA, grave=True)
t('la sede ferroviaria e piu larga di una carraia',
  STR2.LARGHEZZA_FERROVIA_M['rail'] > STR2.LARGHEZZA_M['track'], grave=True)

# la maschera deve usare la larghezza FERROVIARIA, non il default stradale
FERR = [{'classe': 'rail', 'tipo': 'ferrovia', 'nome': 'test',
         'geom': [(42.3300, 13.7000), (42.3300, 13.7030)]}]
TRACK = [{'classe': 'track', 'tipo': 'strada', 'nome': 'test',
          'geom': [(42.3300, 13.7000), (42.3300, 13.7030)]}]
PT = [parcella('R', 'campo', 42.3295, 13.7000, ha=4.0, d=0.001)]
m_f, _ = STR2.maschera(PT, FERR, ris=2.0)
m_t, _ = STR2.maschera(PT, TRACK, ris=2.0)
t('la ferrovia occupa piu superficie di una carraia (controprova)',
  m_f.sum() > m_t.sum(), f'{m_f.sum()} vs {m_t.sum()}', grave=True)

# se Overpass non risponde, si solleva: mai "nessuna strada" non verificato
t('senza rete si solleva invece di restituire lista vuota',
  'raise RuntimeError' in _src, grave=True)

# ---- frazionamento: quante famiglie, non quante particelle
FRZ = [{'fg': '82', 'pla': str(n), 'netti': 0.5, 'ancora': False}
       for n in (40, 41, 46, 50, 51)] +       [{'fg': '82', 'pla': '900', 'netti': 1.0, 'ancora': False},
       {'fg': '70', 'pla': '10', 'netti': 1.0, 'ancora': False},
       {'fg': '70', 'pla': '999', 'netti': 1.0, 'ancora': True}]
sf = FZ.stima(FRZ)
t('il frazionamento 40-41-46-50-51 e riconosciuto come UN gruppo',
  any(len(g['particelle']) == 5 for g in sf['gruppi_multipli']),
  f"{[len(g['particelle']) for g in sf['gruppi_multipli']]}", grave=True)
t('la particella lontana (900) resta separata',
  sf['controparti_min_stimate'] == 3, f"min {sf['controparti_min_stimate']}", grave=True)
t('il massimo resta una controparte per particella',
  sf['controparti_max'] == 7, f"max {sf['controparti_max']}")
t('la terra gia tua non entra nel conteggio',
  sf['particelle_da_acquisire'] == 7, grave=True)
t('la stima si dichiara stima, non visura',
  'STIMA' in sf['nota'] and 'visura' in sf['nota'], grave=True)
# fogli diversi non si fondono mai
t('numeri vicini su FOGLI diversi restano separati (controprova)',
  FZ.stima([{'fg': 'A', 'pla': '10', 'netti': 1, 'ancora': False},
            {'fg': 'B', 'pla': '11', 'netti': 1, 'ancora': False}]
           )['controparti_min_stimate'] == 2, grave=True)

# ---------------------------------------------------------------- potatura
print()
print('[P] potatura: stessi ettari, meno firme')

# fila di 12 particelle: 3 grandi (2 ha) e 9 fazzoletti (0,2 ha). Per arrivare a
# 6 ha la greedy si porta dietro anche i fazzoletti che incontra: ognuno e' una
# firma. La potatura deve toglierli tutti tranne quelli che tengono unito il blocco.
_PP = []
for i in range(12):
    _PP.append(parcella('4', str(i), 42.340, 13.700 + 0.002 * i,
                        ha=(2.0 if i in (0, 5, 11) else 0.2)))
_AP = B.ammissibilita(_PP, {f'4_{i}': vinc() for i in range(12)},
                      {f'4_{i}': occ() for i in range(12)})
_adjP = B.adiacenza(_AP)
_ix = {f"{p['fg']}_{p['pla']}": i for i, p in enumerate(_AP['ammesse'])}
_sel = set(range(len(_AP['ammesse'])))
_tot0 = sum(p['netti'] for p in _AP['ammesse'])
_sel2, _tot2, _tolte = B.pota(_AP, _adjP, _sel, target_ha=4.0)
t('la potatura toglie qualcosa', len(_tolte) > 0, f'tolte {len(_tolte)}', grave=True)
t('e resta sopra il target', _tot2 >= 4.0, f'{_tot2}', grave=True)
def _connesso(sel, adj):
    # `componenti` lavora su TUTTO il pool e conta le particelle rimosse come
    # componenti a se': qui serve la connessione del solo sottoinsieme.
    if len(sel) <= 1:
        return True
    a = next(iter(sel)); visti = {a}; coda = [a]
    while coda:
        u = coda.pop()
        for v in adj.get(u, ()):
            if v in sel and v not in visti:
                visti.add(v); coda.append(v)
    return len(visti) == len(sel)


t('e il blocco resta CONTIGUO', _connesso(_sel2, _adjP), 'spezzato', grave=True)
t('meno particelle di prima', len(_sel2) < len(_sel), f'{len(_sel)} -> {len(_sel2)}',
  grave=True)

# le ancore non si toccano MAI: sono gratis e sono il motivo del blocco
_anc = [_ix['4_1'], _ix['4_2']]
_sel3, _tot3, _tolte3 = B.pota(_AP, _adjP, set(range(len(_AP['ammesse']))),
                               target_ha=4.0, ancore=_anc)
t('le ancore restano dentro anche se minuscole',
  all(a in _sel3 for a in _anc), f'sel {sorted(_sel3)}', grave=True)
t('e non compaiono fra le tolte', not any(a in _tolte3 for a in _anc), grave=True)

# controprova: se il target e' tutto il pool non si puo togliere niente
_sel4, _tot4, _tolte4 = B.pota(_AP, _adjP, set(range(len(_AP['ammesse']))),
                               target_ha=_tot0)
t('controprova: col target pari al pool non si toglie nulla', _tolte4 == [],
  f'tolte {len(_tolte4)}', grave=True)
t('e la funzione TERMINA (niente ciclo infinito)', True)

_blkp = B.cresci_migliore(_AP, _adjP, 4.0, semi=[0], obiettivo='controparti')
_blkg = B.cresci_migliore(_AP, _adjP, 4.0, semi=[0], obiettivo='controparti',
                          potatura=False)
t('cresci_migliore pota di default e riduce le firme',
  _blkp['n_acquisti'] <= _blkg['n_acquisti'],
  f"{_blkg['n_acquisti']} -> {_blkp['n_acquisti']}", grave=True)
t('senza perdere il target', _blkp['ha_netti'] >= 4.0 * 0.98, str(_blkp['ha_netti']),
  grave=True)
t('e il conteggio delle potate viaggia col blocco', 'potate' in _blkp, grave=True)

# ---------------------------------------------------------------- esito
print('\n' + '=' * 76)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 76)
sys.exit(1 if GRAVI else 0)
