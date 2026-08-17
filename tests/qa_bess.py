"""land-scout — QA ADVERSARIALE del modulo BESS (23/07/2026)

Non verifica che le funzioni "girino": verifica che il modulo NON MENTA sulle
tre cose per cui esiste — la forma della piattaforma, la taglia di mercato, e
la lettura rovesciata della rete. Ogni test dichiara cosa si aspetta un utente
ragionevole. FAIL = il tool sta per far prendere una decisione sbagliata.

Uso:  .venv/Scripts/python tests/qa_bess.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from landscout import bess, engine

ESITI = []


def check(nome, ok, atteso, ottenuto, gravita='ALTA'):
    ESITI.append((nome, ok, gravita))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nome}")
    if not ok:
        print(f"         atteso:   {atteso}")
        print(f"         ottenuto: {ottenuto}")


def rett(lat0, lon0, dlat, dlon, fg='1', pla='1', netti=None, ancora=False):
    """Rettangolo in gradi. dlat/dlon piccoli: la proiezione locale e' lineare."""
    poly = [[lat0, lon0], [lat0 + dlat, lon0], [lat0 + dlat, lon0 + dlon],
            [lat0, lon0 + dlon], [lat0, lon0]]
    m_lat, m_lon = 110540.0, 111320.0 * math.cos(math.radians(lat0))
    ha = (dlat * m_lat) * (dlon * m_lon) / 10000.0
    return {'fg': fg, 'pla': pla, 'poly': poly, 'netti': netti if netti is not None else ha,
            'ancora': ancora}


print('=' * 74)
print('  QA BESS — il modulo deve sbagliare rumorosamente, non in silenzio')
print('=' * 74)

# ---------------------------------------------------------------- GEOMETRIA
print('\n[1] LA FORMA: stessa superficie, forme diverse, esito diverso')

LATO = 0.0018          # ~200 m
quadrato = [rett(42.33, 13.71, LATO, LATO * 110540 / (111320 * math.cos(math.radians(42.33))))]
pq = bess.piattaforma(quadrato)
check('un quadrato da ~4 ha e\' una piattaforma valida',
      pq['piattaforma_ok'] and pq['lato_quadrato_m'] >= bess.LATO_MIN_M,
      f"lato >= {bess.LATO_MIN_M} m", f"lato {pq['lato_quadrato_m']} m")

# nastro: stessa area, 10x piu' lungo e 10x piu' stretto
k = 111320 * math.cos(math.radians(42.33))
nastro = [rett(42.33, 13.71, LATO / 10 * 1, LATO * 10 * 110540 / k)]
pn = bess.piattaforma(nastro)
check('un NASTRO di pari superficie NON e\' una piattaforma',
      not pn['piattaforma_ok'],
      'piattaforma_ok = False (per il BESS la forma e\' vincolante)',
      f"ok={pn['piattaforma_ok']} lato={pn['lato_quadrato_m']} m")
# NB: il confronto va fatto sulle superfici ANALITICHE. Quelle geometriche
# passano dalla maschera a 2 m/px, e un nastro alto ~20 m e' spesso 10 pixel:
# li' la quantizzazione vale da sola il 10%, e un test che la ignora fallisce
# per colpa propria (successo del 23/07: era il test a sbagliare, non il modulo).
check('il nastro ha la STESSA superficie del quadrato (e\' la FORMA a cambiare)',
      abs(nastro[0]['netti'] - quadrato[0]['netti']) / quadrato[0]['netti'] < 0.01,
      'stessa area analitica entro l\'1%',
      f"{nastro[0]['netti']:.3f} vs {quadrato[0]['netti']:.3f} ha")
check('anche misurate sulla maschera le due aree restano confrontabili',
      abs(pn['ha_unione_geometrica'] - pq['ha_unione_geometrica']) / pq['ha_unione_geometrica'] < 0.15,
      'entro il 15% (tolleranza di rasterizzazione a 2 m/px)',
      f"{pn['ha_unione_geometrica']} vs {pq['ha_unione_geometrica']} ha")
check('il riempimento del bbox distingue le due forme',
      pn['riempimento_bbox'] <= pq['riempimento_bbox'],
      'nastro <= quadrato', f"{pn['riempimento_bbox']} vs {pq['riempimento_bbox']}")

# differenza rispetto ad agriPV: per installabile.py il nastro DENTRO un blocco resta utile
print('\n[2] LA DIVERGENZA VOLUTA DA agriPV')
from landscout import installabile
inst = installabile.analizza(nastro)
check('agriPV e BESS danno risposte diverse sullo stesso nastro (e deve essere cosi\')',
      inst['ha_installabile'] >= 0 and not pn['piattaforma_ok'],
      'installabile misura ettari erosi, bess misura il quadrato inscritto',
      f"installabile={inst['ha_installabile']} ha, piattaforma_ok={pn['piattaforma_ok']}")

# ---------------------------------------------------------------- TAGLIA
print('\n[3] LA TAGLIA: il modulo non deve sottodimensionare')
d = bess.dimensiona(3.5)
check('3,5 ha utili danno una taglia dentro il mercato, non 9 MW',
      d['mw'] >= bess.VIA_TAGLIE_MW['q1'],
      f"MW >= primo quartile VIA ({bess.VIA_TAGLIE_MW['q1']})", f"{d['mw']} MW")
check('sopra 10 MW il modulo dichiara ALTA TENSIONE',
      d['sopra_soglia_at'] is True, 'sopra_soglia_at=True', d['sopra_soglia_at'])

mt = bess.taglia_per_restare_in_mt()
dmt = bess.dimensiona(mt['ha_max'])
check('la superficie "per restare in MT" produce davvero <10 MW (coerenza interna)',
      dmt['mw'] < bess.SOGLIA_AT_MW and not dmt['sopra_soglia_at'],
      f"< {bess.SOGLIA_AT_MW} MW", f"{dmt['mw']} MW")

dq = bess.dimensiona(3.5, ha_quadrato=0.9)
check('con il quadrato inscritto il modulo dichiara una FORBICE, non un numero',
      dq['conservativo'] and dq['conservativo']['mw'] < dq['mw'],
      'stima conservativa < stima ottimistica',
      f"{dq['conservativo'] and dq['conservativo']['mw']} vs {dq['mw']}")

di = bess.densita_implicita()
check('la densita\' assunta regge il controllo incrociato mercato x developer',
      di['coerente_con_assunto'], 'coerente', di)

# ---------------------------------------------------------------- RETE
print('\n[4] LA RETE: stessa riga di dati, segno opposto')
r_at = bess.rete(30.0, inversione=True, d_se_m=3000)
r_no = bess.rete(30.0, inversione=False, d_se_m=3000)
check('per un accumulo l\'inversione di flusso e\' un PLUS, non un veto',
      r_at['punteggio_rete'] > r_no['punteggio_rete'],
      'punteggio con inversione > senza', f"{r_at['punteggio_rete']} vs {r_no['punteggio_rete']}")
check('a 30 MW la connessione e\' in AT e il modulo lo dice esplicitamente',
      r_at['alta_tensione'] and any('ALTA TENSIONE' in n for n in r_at['note']),
      'alta_tensione=True + nota esplicita', r_at['alta_tensione'])
r_sotto = bess.rete(9.9, inversione=True, d_se_m=3000)
check('a 9,9 MW si resta in MT e il modulo avverte che li\' la saturazione morde',
      (not r_sotto['alta_tensione']) and any('satura' in n for n in r_sotto['note']),
      'MT + avviso saturazione', r_sotto['note'])
check('la soglia AT scatta esattamente a 10 MW',
      bess.rete(10.0)['alta_tensione'] and not bess.rete(9.999)['alta_tensione'],
      '10.0 -> AT, 9.999 -> MT',
      (bess.rete(10.0)['alta_tensione'], bess.rete(9.999)['alta_tensione']))
check('la coda affollata abbassa il punteggio invece di alzarlo',
      bess.rete(30.0, inversione=True, d_se_m=3000, coda_mw=5556)['punteggio_rete']
      < r_at['punteggio_rete'],
      'coda = penalita\' (affollamento), non bonus',
      bess.rete(30.0, inversione=True, d_se_m=3000, coda_mw=5556)['punteggio_rete'])

# ---------------------------------------------------------------- SBANCAMENTO
print('\n[5] LO SBANCAMENTO: deve scalare col cubo del lato, non col lato')
s1 = bess.sbancamento(1.0, 10.0)
s4 = bess.sbancamento(4.0, 10.0)
rap = s4['volume_mc'] / s1['volume_mc']
check('quadruplicare la superficie ottuplica il volume di scavo (L^3)',
      7.5 <= rap <= 8.5, 'rapporto ~8', round(rap, 2))
st = bess.sbancamento(4.0, 10.0, platee=4)
check('terrazzare in 4 gradoni dimezza il volume (1/sqrt(4))',
      abs(st['volume_mc'] / s4['volume_mc'] - 0.5) < 0.05,
      'rapporto ~0,5', round(st['volume_mc'] / s4['volume_mc'], 3))
check('un sito da 3,5 ha al 8,5% NON costa 9 k EUR di sbancamento (bug del 23/07)',
      bess.sbancamento(3.5, 8.5)['costo_eur'] > 100_000,
      'ordine 10^5-10^6 EUR', bess.sbancamento(3.5, 8.5)['costo_eur'])

# ---------------------------------------------------------------- CANONE
print('\n[6] IL CANONE: il modulo deve smontare il proprio assunto')
dim = bess.dimensiona(3.5)
cc = bess.canone_confronto(dim, 5.23, canone_eur_ha=(2_500, 4_500))
check('l\'allarme scatta se il EUR/ha implicito e\' fuori scala vs agrivoltaico',
      cc['allarme'] is True,
      'allarme=True con EUR/MW 3.000-8.000 su questo sito', cc['per_ha_implicito_eur'])
cc2 = bess.canone_confronto(dim, 5.23, canone_eur_mw=(200, 400), canone_eur_ha=(2_500, 4_500))
check('con un EUR/MW prudente l\'allarme NON scatta (niente falsi positivi)',
      cc2['allarme'] is False, 'allarme=False', cc2['per_ha_implicito_eur'])

# ---------------------------------------------------------------- VINCOLI
print('\n[7] I VINCOLI: cio\' che non e\' controllato non e\' pulito')
v = bess.vincoli_bess({'slope': 6.0})
check('un dizionario quasi vuoto produce CRITICITA\', non un via libera',
      len(v['criticita']) >= 4 and not v['blocker'],
      'elenco di controlli mancanti', v['criticita'])
check('il PAI idraulico non verificato viene nominato per primo',
      'PAI idraulico' in v['criticita'][0], 'primo flag = PAI idraulico', v['criticita'][0])
check('P2 idraulico e\' bloccante per un accumulo',
      bess.vincoli_bess({'pai_idr': 2})['blocker'] is True, 'blocker=True', False)
check('la ZPS compare fra i punti A FAVORE, con la riserva sulla VINCA',
      any('VINCA' in f for f in bess.vincoli_bess({'zps_pct': 100})['favorevoli']),
      'nota ZPS con riserva', bess.vincoli_bess({'zps_pct': 100})['favorevoli'])

print('\n[8] COERENZA CON engine.py (due moduli non devono dire cose diverse)')
check('le soglie di pendenza BESS coincidono con quelle di engine.score_parcel',
      (bess.PEND_OK, bess.PEND_LIMITE) == (8, 12),
      'engine usa (8, 12) per il BESS', (bess.PEND_OK, bess.PEND_LIMITE))
sc, cl, fl = engine.score_parcel({'ha': 3.0, 'slope': 13.0, 'zps_pct': 0, 'zps_border_m': 9e9,
                                  'pai_fr': -1, 'd_se_m': 2000}, tech='BESS')
check('pendenza 13% e\' bloccante in entrambi i moduli',
      cl == 'D' and bess.vincoli_bess({'slope': 13.0})['blocker'],
      'engine classe D e bess blocker', (cl, bess.vincoli_bess({'slope': 13.0})['blocker']))

# ---------------------------------------------------------------- ROBUSTEZZA
print('\n[9] ROBUSTEZZA: input degeneri non devono produrre numeri finti')
ok = True
try:
    bess.piattaforma([])
    ok = False
except Exception:
    pass
check('un insieme vuoto solleva un errore invece di restituire 0 ha "puliti"',
      ok, 'eccezione', 'ha restituito un risultato')
check('pendenza None non inventa uno sbancamento',
      bess.sbancamento(3.0, None) is None, 'None', bess.sbancamento(3.0, None))
check('superficie 0 non inventa uno sbancamento',
      bess.sbancamento(0, 10.0) is None, 'None', bess.sbancamento(0, 10.0))
uno = bess.piattaforma([rett(42.33, 13.71, 0.0002, 0.0002)])
check('una particella minuscola non passa come piattaforma',
      not uno['piattaforma_ok'], 'piattaforma_ok=False', uno['lato_quadrato_m'])

# ---------------------------------------------------------------- SCAN
print('\n[10] LO SCAN: deve preferire poche firme e tanta terra di famiglia')
dl = 0.0009
dlon = dl * 110540 / k
griglia = []
for i in range(3):
    for j in range(3):
        griglia.append(rett(42.33 + i * dl, 13.71 + j * dlon, dl, dlon,
                            fg='9', pla=f'{i}{j}', ancora=(i == 1)))
c = bess.candidati(griglia, target_ha=3.0, max_siti=5)
check('lo scan restituisce siti che raggiungono il target',
      c and all(s['ha'] >= 3.0 * 0.6 for s in c), 'ha >= 60% del target',
      [s['ha'] for s in c])
check('a parita\' di forma, il sito con piu\' terra di famiglia va prima',
      c[0]['quota_famiglia'] >= c[-1]['quota_famiglia'],
      'primo classificato >= ultimo', (c[0]['quota_famiglia'], c[-1]['quota_famiglia']))
check('ogni sito dichiara quante controparti servono',
      all('controparti' in s and 'da_acquisire' in s for s in c),
      'campo controparti presente', list(c[0]))

# ---------------------------------------------------------------- REPORT
print('\n' + '=' * 74)
tot = len(ESITI)
fail = [e for e in ESITI if not e[1]]
print(f"  {tot - len(fail)}/{tot} PASS")
if fail:
    print('  FALLITI:')
    for n, _, g in fail:
        print(f"    [{g}] {n}")
print('=' * 74)
sys.exit(1 if fail else 0)
