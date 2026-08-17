"""land-scout — QA ADVERSARIALE del modulo crinali (27/07/2026)

Il modulo nasce da un fatto: la Provincia di Benevento ha impugnato al TAR un
PAUR gia' rilasciato usando la fascia di rispetto dei crinali del PTCP. Il
rischio speculare del tool e' il quinto ripetersi dello schema "assenza di dato
letta come assenza di problema": un DEM che non risponde, o soglie troppo
strette, e il blocco esce "fuori fascia" quando non lo e'.

Questi test verificano che il modulo NON menta su tre cose: dove sta un crinale,
quando NON sa rispondere, e quanto il risultato dipenda dalle soglie.

Uso:  .venv/Scripts/python tests/qa_crinali.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from landscout import crinali  # noqa: E402

ESITI = []


def check(nome, ok, atteso, ottenuto, gravita='ALTA'):
    ESITI.append((nome, ok, gravita))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nome}")
    if not ok:
        print(f"         atteso:   {atteso}")
        print(f"         ottenuto: {ottenuto}")


def rett(lat0, lon0, dlat, dlon, fg='1', pla='1', ancora=False):
    poly = [[lat0, lon0], [lat0 + dlat, lon0], [lat0 + dlat, lon0 + dlon],
            [lat0, lon0 + dlon], [lat0, lon0]]
    m_lat, m_lon = 110540.0, 111320.0 * math.cos(math.radians(lat0))
    ha = (dlat * m_lat) * (dlon * m_lon) / 10000.0
    return {'fg': fg, 'pla': pla, 'poly': poly, 'ha': ha, 'netti': ha, 'ancora': ancora}


def griglia_sintetica(z, lat0=42.33, lon0=13.71, passo_m=90.0):
    """Impacchetta una matrice di quote come griglia gia' scaricata."""
    dlat = passo_m / 110540
    dlon = passo_m / (111320 * math.cos(math.radians(lat0)))
    lats = [lat0 + i * dlat for i in range(len(z))]
    lons = [lon0 + j * dlon for j in range(len(z[0]))]
    return {'lats': lats, 'lons': lons,
            'quote': [z[i][j] for i in range(len(z)) for j in range(len(z[0]))]}


print('=' * 74)
print('  QA CRINALI — il modulo deve sbagliare rumorosamente, non in silenzio')
print('=' * 74)

# ------------------------------------------------------- RILEVAMENTO CELLE
print('\n[1] MORFOLOGIA: cosa e\' un crinale e cosa non lo e\'')

N = 11
# dorsale rettilinea N-S: colonna centrale alta, fianchi che scendono
dorsale = [[100.0 - 8 * abs(j - 5) for j in range(N)] for _ in range(N)]
c = crinali._celle_crinale(dorsale, direzioni_min=2, prominenza=5.0)
colonne = {j for _, j in c}
check('una dorsale rettilinea viene rilevata',
      len(c) > 0, 'almeno una cella di crinale', len(c))
check('le celle stanno sulla colonna della cresta, non sui fianchi',
      colonne == {5}, 'solo colonna 5', sorted(colonne))

piano = [[100.0 for _ in range(N)] for _ in range(N)]
check('un pianoro NON e\' un crinale',
      crinali._celle_crinale(piano, 2, 5.0) == set(), 'nessuna cella',
      len(crinali._celle_crinale(piano, 2, 5.0)))

valle = [[60.0 + 8 * abs(j - 5) for j in range(N)] for _ in range(N)]
cv = crinali._celle_crinale(valle, 2, 5.0)
check('un impluvio (valle) NON viene scambiato per crinale',
      all(j != 5 for _, j in cv), 'nessuna cella sul fondovalle (colonna 5)',
      sorted({j for _, j in cv}))

# rumore di ampiezza inferiore alla prominenza richiesta
rumore = [[100.0 + ((i * 7 + j * 13) % 3) for j in range(N)] for i in range(N)]
check('il rumore del DEM sotto la prominenza minima non genera crinali',
      crinali._celle_crinale(rumore, 2, 5.0) == set(),
      'nessuna cella con prominenza 5 m su rumore di 2 m',
      len(crinali._celle_crinale(rumore, 2, 5.0)))
check('lo stesso rumore, con prominenza bassa, genera falsi positivi',
      len(crinali._celle_crinale(rumore, 2, 0.5)) > 0,
      'il test precedente dipende dalla soglia, non e\' una tautologia',
      len(crinali._celle_crinale(rumore, 2, 0.5)))

vetta = [[100.0 - 6 * max(abs(i - 5), abs(j - 5)) for j in range(N)] for i in range(N)]
check('una vetta e\' massimo locale in tutte e 4 le direzioni',
      (5, 5) in crinali._celle_crinale(vetta, 4, 5.0),
      'cella centrale rilevata anche col criterio piu\' stretto',
      sorted(crinali._celle_crinale(vetta, 4, 5.0)))
check('il criterio stretto rileva MENO celle di quello largo',
      len(crinali._celle_crinale(dorsale, 4, 5.0)) <= len(crinali._celle_crinale(dorsale, 2, 5.0)),
      'monotonia sul numero di direzioni', None)

# ---------------------------------------------------------------- DEM BUCATO
print('\n[2] IL DEM CHE NON RISPONDE: mai letto come "nessun crinale"')

bucato = [[None for _ in range(N)] for _ in range(N)]
check('un DEM tutto vuoto non fa esplodere il rilevamento',
      crinali._celle_crinale(bucato, 2, 5.0) == set(), 'nessuna cella, nessuna eccezione', None)

meta = [[dorsale[i][j] if i < 3 else None for j in range(N)] for i in range(N)]
p = [rett(42.33, 13.71, 0.0009, 0.0009)]
r = crinali.fascia_crinali(p, griglia=griglia_sintetica(meta))
check('sopra il 50% di quote mancanti il modulo si dichiara NON VERIFICATO',
      r.get('verificato') is False, 'verificato=False', r.get('verificato'))
check('e spiega perche\', invece di restituire zero particelle in fascia',
      'DEM incompleto' in (r.get('motivo') or ''), 'motivo esplicito', r.get('motivo'))

# ------------------------------------------------------------- LINEARITA'
print('\n[3] IL FILTRO DI LINEARITA\': una linea di crinale e\' una LINEA')

lat0, lon0 = 42.33, 13.71
M = crinali._proj(lat0)
g = griglia_sintetica(dorsale, lat0, lon0)
z = [[g['quote'][i * N + j] for j in range(N)] for i in range(N)]
_, d_libero = crinali._dorsali(z, g['lats'], g['lons'], M, 2, 5.0, 1, 0.0)
_, d_lineare = crinali._dorsali(z, g['lats'], g['lons'], M, 2, 5.0, 3, 300.0)
check('la dorsale vera sopravvive al filtro di linearita\'',
      len(d_lineare) >= 1, 'almeno 1 dorsale', len(d_lineare))

# due dossi isolati, lontani tra loro e piccoli: non sono linee di crinale
dossi = [[100.0 for _ in range(N)] for _ in range(N)]
dossi[2][2] = 130.0
dossi[8][8] = 130.0
zg = griglia_sintetica(dossi, lat0, lon0)
zz = [[zg['quote'][i * N + j] for j in range(N)] for i in range(N)]
_, dd_libero = crinali._dorsali(zz, zg['lats'], zg['lons'], M, 2, 5.0, 1, 0.0)
_, dd_lineare = crinali._dorsali(zz, zg['lats'], zg['lons'], M, 2, 5.0, 3, 300.0)
check('due dossi isolati vengono contati come crinali SENZA il filtro',
      len(dd_libero) == 2, '2 componenti', len(dd_libero))
check('...e scartati CON il filtro di linearita\'',
      len(dd_lineare) == 0, '0 dorsali', len(dd_lineare))

# 8-connettivita': celle diagonali sono la stessa dorsale
diag = crinali._componenti({(1, 1), (2, 2), (3, 3)})
check('celle in diagonale formano una sola dorsale (8-connettivita\')',
      len(diag) == 1, '1 componente', len(diag))
staccate = crinali._componenti({(1, 1), (5, 5)})
check('celle lontane restano dorsali distinte',
      len(staccate) == 2, '2 componenti', len(staccate))

# ------------------------------------------------------------------ BUFFER
print('\n[4] LA FASCIA DEI 300 m: il bordo va nella direzione giusta')

gg = griglia_sintetica(dorsale, lat0, lon0)
# la cresta e' sulla colonna 5 => lon = lon0 + 5*dlon
dlon = 90.0 / (111320 * math.cos(math.radians(lat0)))
lon_cresta = lon0 + 5 * dlon


def particella_a_distanza(dm, fg='9'):
    """Quadratino piccolo il cui lato piu' vicino dista dm metri dalla cresta."""
    lo = lon_cresta + dm / (111320 * math.cos(math.radians(lat0)))
    return rett(lat0 + 5 * (90.0 / 110540), lo, 0.00002, 0.00002, fg=fg, pla=str(int(dm)))


vicina = crinali.fascia_crinali([particella_a_distanza(100)], griglia=gg)
lontana = crinali.fascia_crinali([particella_a_distanza(900)], griglia=gg)
check('una particella a 100 m dalla cresta e\' DENTRO la fascia',
      list(vicina['particelle'].values())[0]['entro_fascia'] is True,
      'entro_fascia=True', list(vicina['particelle'].values())[0])
check('una particella a 900 m dalla cresta e\' FUORI',
      list(lontana['particelle'].values())[0]['entro_fascia'] is False,
      'entro_fascia=False', list(lontana['particelle'].values())[0])
check('la distanza misurata cresce con la distanza vera',
      list(lontana['particelle'].values())[0]['d_crinale_m'] >
      list(vicina['particelle'].values())[0]['d_crinale_m'],
      'monotonia della distanza', None)

stretto = crinali.fascia_crinali([particella_a_distanza(100)], griglia=gg, buffer_m=50.0)
check('con buffer 50 m la stessa particella a 100 m esce dalla fascia',
      list(stretto['particelle'].values())[0]['entro_fascia'] is False,
      'il buffer e\' davvero un parametro, non un valore cablato',
      list(stretto['particelle'].values())[0])

# ------------------------------------------------------------- SENSIBILITA'
print('\n[5] IL MODULO DICHIARA QUANTO NON SA')

molte = [particella_a_distanza(d, fg=str(i)) for i, d in enumerate((50, 200, 400, 800))]
rs = crinali.fascia_crinali(molte, griglia=gg)
check('il risultato include la banda di sensibilita\' alle soglie',
      isinstance(rs.get('sensibilita'), list) and len(rs['sensibilita']) >= 5,
      'almeno 5 configurazioni provate', len(rs.get('sensibilita') or []))
check('la banda dichiara minimo e massimo, non solo il default',
      rs.get('banda_pct') and rs['banda_pct'][0] <= rs['banda_pct'][1],
      'banda [min, max] coerente', rs.get('banda_pct'))
pct = {s['etichetta']: s['pct_ha_entro'] for s in rs['sensibilita']}
check('la configurazione senza filtro di linearita\' non segnala MENO della stretta',
      (pct.get('nessun filtro di linearita (limite superiore)') or 0) >=
      (pct.get('stretta (limite inferiore)') or 0),
      'monotonia della banda', pct)
check('la nota rimanda alla tavola ufficiale del PTCP, non spaccia il DEM per il piano',
      'A 2.2e' in rs['nota'] and 'PUC' in rs['nota'],
      'nota cita tavola A 2.2e e il PUC comunale', rs['nota'][:80])
check('il buffer di default e\' quello della norma (300 m per lato)',
      crinali.BUFFER_CRINALE_M == 300.0, '300.0', crinali.BUFFER_CRINALE_M)

# ------------------------------------------------------------------ INPUT
print('\n[6] INPUT DEGENERI')

try:
    crinali.fascia_crinali([], griglia=gg)
    ok_vuoto = False
except ValueError:
    ok_vuoto = True
check('lista di particelle vuota solleva ValueError, non ritorna "tutto pulito"',
      ok_vuoto, 'ValueError', 'nessuna eccezione')

r_agg = crinali.fascia_crinali(molte, griglia=gg)
somma = sum(v['ha'] for v in r_agg['particelle'].values())
check('gli ettari totali riportati coincidono con la somma delle particelle',
      abs(r_agg['ha_totali'] - round(somma, 2)) < 0.02,
      f'{round(somma, 2)}', r_agg['ha_totali'])
check('ogni particella riporta anche la distanza dalla dorsale PRINCIPALE',
      all('d_principale_m' in v and 'entro_fascia_principale' in v
          for v in r_agg['particelle'].values()),
      'campi principale presenti', list(list(r_agg['particelle'].values())[0]))

# particella di dimensione realistica (~1 ha): con i quadratini da 3 m² gli
# ettari arrotondati a 2 decimali valgono 0.0 e il test misurerebbe solo
# l'arrotondamento invece dell'aggregazione.
fam = [rett(lat0 + 5 * (90.0 / 110540), lon_cresta + 0.001, 0.0009, 0.0012,
            fg='7', pla='1', ancora=True)]
r_fam = crinali.fascia_crinali(fam, griglia=gg)
check('la quota di terra di FAMIGLIA e\' contata a parte da quella totale',
      r_fam['ha_famiglia'] > 0 and r_fam['ha_famiglia'] <= r_fam['ha_totali'],
      'ha_famiglia valorizzato e <= totale',
      (r_fam['ha_famiglia'], r_fam['ha_totali']))

print('\n' + '=' * 74)
tot = len(ESITI)
fail = [e for e in ESITI if not e[1]]
print(f"  {tot - len(fail)}/{tot} PASS")
if fail:
    print('  FALLITI:')
    for n, _, gr in fail:
        print(f"    [{gr}] {n}")
print('=' * 74)
sys.exit(1 if fail else 0)
