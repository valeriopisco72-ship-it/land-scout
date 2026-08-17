"""land-scout — QA PROFONDO (16/07/2026): caccia sistematica alle debolezze.

Non e' la batteria "regge agli input storti" (quella e' qa_adversarial.py). Qui si cercano
i difetti di SOSTANZA: incoerenze logiche, numeri che non tornano, affermazioni non
verificabili, monotonia della scala del valore, comportamento della cache, invarianti.

Filosofia: ogni test dichiara l'INVARIANTE che un utente ragionevole dà per scontato.
Se un invariante non regge, il tool mente — anche se non va in crash.

Uso:  .venv/Scripts/python tests/qa_profondo.py [--rete]
"""
import sys, json, math, itertools, io, contextlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

from landscout.valore import valore, p_auth, MOLT_OPZIONALITA
from landscout.recommend import recommend
from landscout.engine import score_parcel
from landscout.config import copertura, PROV_REGIONE, valida_coordinate, CoordinataNonValida, MWP_HA
from landscout import vam as VAM

ESITI = []
def check(nome, ok, atteso, ott, sez=''):
    ESITI.append((sez, nome, ok, atteso, ott))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nome}")
    if not ok:
        print(f"         invariante: {atteso}")
        print(f"         osservato : {ott}")

def sezione(t):
    print(f"\n{'='*74}\n {t}\n{'='*74}")

# ══════════════════════════════════════════════ A. MONOTONIA DELLA SCALA VALORE
sezione("A. SCALA DEL VALORE — gli invarianti che un proprietario dà per scontati")

for prov in ['RM', 'VT', None, 'BN']:
    v = valore(10.0, {}, tech='agriPV', prov=prov)
    g = {x['nome'].split('—')[0].strip(): x for x in v['gradini']}
    agr = next(x for x in v['gradini'] if 'agricolo' in x['nome'].lower())
    opz = next(x for x in v['gradini'] if 'opzionalit' in x['nome'].lower())
    et = prov or 'nessuna prov'
    check(f"[{et}] opzionalità ≥ agricolo (la scala non si inverte)",
          opz['range_eur'][0] >= agr['range_eur'][0] and opz['range_eur'][1] >= agr['range_eur'][1],
          "un 'premio' non può valere meno del 'pavimento': nessuno cede a X un campo che vale >X",
          f"agricolo={agr['range_eur']} opzionalità={opz['range_eur']}", 'A')

for prov in ['RM', 'BN']:
    v = valore(10.0, {}, tech='agriPV', prov=prov)
    for g in v['gradini']:
        if g['range_eur']:
            check(f"[{prov}] {g['nome'][:34]}: min ≤ max",
                  g['range_eur'][0] <= g['range_eur'][1],
                  "il minimo di un range non può superare il massimo",
                  str(g['range_eur']), 'A')

# linearità: raddoppiare gli ettari raddoppia il valore?
v1 = valore(10.0, {}, prov='RM'); v2 = valore(20.0, {}, prov='RM')
a1 = v1['gradini'][0]['range_eur'][1]; a2 = v2['gradini'][0]['range_eur'][1]
check("Raddoppiare gli ettari raddoppia il valore agricolo",
      abs(a2 - 2*a1) / max(a1, 1) < 0.02,
      "il pavimento agricolo è lineare negli ettari",
      f"10ha={a1:,} 20ha={a2:,} (atteso ~{2*a1:,})", 'A')

# p_auth monotona: più vincoli = meno probabilità
ordini = [({}, 'pulito'), ({'zps': True}, 'ZPS'), ({'sic': True}, 'SIC'),
          ({'usi_civici': True}, 'usi civici'), ({'habitat_ban': True}, 'divieto habitat')]
ps = [(p_auth(v)[0], n) for v, n in ordini]
check("p_auth è monotona: ogni vincolo in più non aumenta mai la probabilità",
      all(ps[i][0] >= ps[i+1][0] for i in range(len(ps)-1)),
      "pulito ≥ ZPS ≥ SIC ≥ usi civici ≥ divieto",
      ' > '.join(f'{n}={p}' for p, n in ps), 'A')

# vincoli cumulati: il peggiore deve vincere
v_multi = valore(10.0, {'zps': True, 'habitat_ban': True})
check("Vincoli cumulati: vince il più restrittivo",
      v_multi['p_auth'] == 0.0,
      "ZPS + divieto habitat -> deve valere 0.0 (il divieto), non 0.5 (la ZPS)",
      f"p_auth={v_multi['p_auth']}", 'A')

# il RTB ponderato non può superare il RTB lordo
v = valore(10.0, {'zps': True}, prov='RM')
rtb = next((g for g in v['gradini'] if 'RTB' in g['nome']), None)
if rtb:
    check("RTB ponderato ≤ RTB lordo",
          rtb['range_eur_ponderato'][1] <= rtb['range_eur'][1],
          "ponderare per p_auth<1 non può aumentare il valore",
          f"lordo={rtb['range_eur']} ponderato={rtb['range_eur_ponderato']}", 'A')

# ══════════════════════════════════════════════ B. VAM
sezione("B. VAM — il dato nuovo regge?")

st = VAM.stato()
check("Il registro VAM dichiara la sua copertura reale",
      st['n'] < st['totale_province'] and 'copertura_pct' in st,
      "il tool deve sapere e dire quante province ha davvero",
      f"{st['n']}/{st['totale_province']} = {st['copertura_pct']}%", 'B')

# ⚠ prima qui era hard-coded 'BN'; poi BN e' stato caricato (18/07) e il test e' diventato
# stale. Ora si sceglie a runtime una provincia NON caricata: il test resta valido comunque.
_caricate = set(VAM.stato()['province_caricate'])
_senza = next(p for p in ['MI', 'TO', 'GE', 'AO', 'BO', 'PD', 'NA'] if p not in _caricate)
check("Provincia senza VAM -> None (nessun ripiego nazionale silenzioso)",
      VAM.vam(_senza, 'seminativo') is None,
      "None = 'non lo so', il chiamante deve dichiararlo",
      f"{_senza} -> {VAM.vam(_senza, 'seminativo')}", 'B')

check("Provincia inesistente -> None, non crash",
      VAM.vam('ZZ') is None and VAM.vam('') is None and VAM.vam(None) is None,
      "sigle assurde non devono esplodere",
      "ok", 'B')

rm = VAM.vam('RM'); vt = VAM.vam('VT')
check("Province diverse -> VAM diversi (il dato è davvero per provincia)",
      rm and vt and rm['eur_ha'] != vt['eur_ha'],
      "RM e VT devono avere valori distinti",
      f"RM={rm['eur_ha'] if rm else None} VT={vt['eur_ha'] if vt else None}", 'B')

check("Il VAM caricato è marcato come pavimento amministrativo, non come mercato",
      rm and 'esproprio' in rm['nota'].lower() and '181/2011' in rm['nota'],
      "usarlo come valore di mercato ripeterebbe il bug originale: va dichiarato",
      (rm['nota'][:60] if rm else 'n/d'), 'B')

check("Coltura inesistente -> None",
      VAM.vam('RM', 'vigneto_marziano') is None,
      "una coltura non caricata non deve tornare un numero",
      str(VAM.vam('RM', 'vigneto_marziano')), 'B')

# il valore col VAM deve DIFFERIRE dal valore senza
v_rm = valore(10.0, {}, prov='RM'); v_no = valore(10.0, {}, prov=None)
check("Il VAM cambia davvero il risultato (non è decorativo)",
      v_rm['gradini'][0]['range_eur'] != v_no['gradini'][0]['range_eur'],
      "con VAM caricato il pavimento deve cambiare rispetto alla banda nazionale",
      f"RM={v_rm['gradini'][0]['range_eur']} vs nazionale={v_no['gradini'][0]['range_eur']}", 'B')

check("Con VAM la 'base' è dichiarata come tale",
      v_rm.get('base_agricola') == 'vam' and v_no.get('base_agricola') == 'nazionale',
      "il consumatore deve poter sapere su cosa poggia il numero",
      f"RM={v_rm.get('base_agricola')} nazionale={v_no.get('base_agricola')}", 'B')

# parser: numeri italiani
from landscout.vam import _num, _slug_coltura, _e_intestazione_ra
NUM = [('12.300', 12300.0), ('1.234,50', 1234.5), ('', None), ('-', None), ('0', None),
       ('  45.000  ', 45000.0), ('abc', None), (None, None), ('€ 12.300', 12300.0)]
for inp, att in NUM:
    got = _num(inp)
    check(f"_num({inp!r}) -> {att!r}", got == att, f"formato italiano: {att!r}", repr(got), 'B')

COL = [('Seminativo', 'seminativo'), ('Sem. Irriguo', 'seminativo_irriguo'),
       ('Seminativo irriguo', 'seminativo_irriguo'), ('  PRATO  ', 'prato'),
       ('Vigneto DOC', None), ('', None),
       # colture DIVERSE che non devono finire nel secchio del seminativo nudo
       ('Sem. Arborato', None), ('Sem. Arb. Irr.', None), ('Prato Arb.', None),
       ('Pascolo cespugliato', None), ('Seminativo arborato irriguo', None)]
for inp, att in COL:
    got = _slug_coltura(inp)
    check(f"_slug_coltura({inp!r}) -> {att!r}", got == att,
          "match ESATTO: arborato/irriguo sono colture diverse, non varianti del seminativo",
          repr(got), 'B')

# ---- il test piu' forte: l'estratto coincide con la riga grezza del PDF? ----
# E' l'unico che avrebbe preso il bug delle sovrascritture silenziose (il range di Roma
# usciva 11.900-52.000 con dentro valori di 'Sem. Irriguo' e 'Sem. Arborato').
GROUND = [('data/raw/vam/VAM-RM-2024.pdf', 'RM', 'Seminativo', 'seminativo'),
          ('data/raw/vam/VAM-VT-2023.pdf', 'VT', 'Seminativo', 'seminativo')]
for pdf_path, prov, etichetta, slug in GROUND:
    p = Path(__file__).resolve().parent.parent / pdf_path
    if not p.exists():
        check(f"[{prov}] ground-truth vs PDF", False, "PDF di riferimento presente", f'manca {pdf_path}', 'B')
        continue
    try:
        import pdfplumber
        with pdfplumber.open(p) as pdf:
            tab = pdf.pages[0].extract_tables()[0]
            riga = next(r for r in tab if str(r[0]).strip().lower() == etichetta.lower())
        veri = sorted(int(str(c).replace('.', '')) for c in riga[1:] if c and str(c).strip())
        reg = json.loads((Path(__file__).resolve().parent.parent /
                          'data/raw/vam/vam.json').read_text(encoding='utf-8'))
        est = sorted(int(v) for v in reg[prov]['colture'][slug].values())
        check(f"[{prov}] l'estratto '{slug}' coincide ESATTAMENTE con la riga '{etichetta}' del PDF",
              veri == est,
              "nessun valore di altre righe deve essere finito in questo secchio",
              f"PDF={veri}  estratto={est}", 'B')
    except Exception as e:
        check(f"[{prov}] ground-truth vs PDF", False, "confronto eseguibile", f'{type(e).__name__}: {e}', 'B')

RA = [('Regione Agraria\nN° 1', 1), ('REGIONE\nAGRARIA N°1', 1), ('Regione Agraria N°\n1 6', 16),
      ('TIPO DI COLTURA', None), ('', None)]
for inp, att in RA:
    got = _e_intestazione_ra(inp)
    check(f"_e_intestazione_ra({inp[:22]!r}) -> {att!r}", got == att,
          "header diversi per provincia, stesso significato", repr(got), 'B')

# ══════════════════════════════════════════════ C. COERENZA FRA MODULI
sezione("C. COERENZA FRA MODULI — i numeri si parlano?")

# MWp: valore.py e resa.py devono usare la stessa densità
from landscout import resa as RESA
v = valore(10.0, {}, tech='agriPV', prov='RM')
rtb = next((g for g in v['gradini'] if 'RTB' in g['nome']), None)
mw_da_valore = None
if rtb:
    import re as _re
    m = _re.search(r'\(([\d.]+)–([\d.]+) MW\)', rtb['nome'])
    if m: mw_da_valore = (float(m.group(1)), float(m.group(2)))
attesa = (10.0 * MWP_HA['agriPV'][0], 10.0 * MWP_HA['agriPV'][1])
check("La taglia MW in valore.py usa MWP_HA di config (fonte unica)",
      mw_da_valore and abs(mw_da_valore[0]-attesa[0]) < 0.1 and abs(mw_da_valore[1]-attesa[1]) < 0.1,
      f"10 ha agriPV -> {attesa} MW secondo config.MWP_HA",
      f"valore.py dice {mw_da_valore}", 'C')

# recommend e valore devono concordare sul divieto
p_ban = {'ha': 5, 'slope': 5, 'zps_pct': 100, 'habitat_ban': True, 'd_se_m': 1000, 'd_150kv_m': 500}
r = recommend(p_ban, {})
v_ban = valore(5, {'habitat_ban': True})
check("recommend e valore concordano: divieto habitat -> niente solare, premio azzerato",
      r.get('top') != 'PV' and v_ban['p_auth'] == 0.0,
      "se il FV è vietato, nessuno dei due moduli deve proporlo/valorizzarlo",
      f"recommend.top={r.get('top')} valore.p_auth={v_ban['p_auth']}", 'C')

# ══════════════════════════════════════════════ D. INVARIANTI DI SCORING
sezione("D. SCORING — monotonia e sensatezza")

base = {'ha': 5.0, 'slope': 8.0, 'zps_pct': 0, 'zps_border_m': 9e9,
        'habitat_ban': False, 'in_sic': False, 'd_se_m': 3000, 'd_150kv_m': 2000}
s_base, _, _ = score_parcel(dict(base), 'agriPV')
s_zps, _, _ = score_parcel(dict(base, zps_pct=100, zps_border_m=-1), 'agriPV')
check("Score: stare in ZPS non può migliorare il punteggio",
      s_zps <= s_base, "un vincolo non aggiunge valore", f"pulito={s_base} zps={s_zps}", 'D')

s_ripido, _, _ = score_parcel(dict(base, slope=28.0), 'agriPV')
check("Score: più pendenza non può migliorare il punteggio",
      s_ripido <= s_base, "28% di pendenza è peggio di 8%", f"8%={s_base} 28%={s_ripido}", 'D')

s_lontano, _, _ = score_parcel(dict(base, d_se_m=20000), 'BESS')
s_vicino, _, _ = score_parcel(dict(base, d_se_m=100), 'BESS')
check("Score BESS: più vicino alla stazione = punteggio ≥",
      s_vicino >= s_lontano, "la vicinanza alla SE è il driver del BESS",
      f"100m={s_vicino} 20km={s_lontano}", 'D')

# monotonia fine su una griglia
viol = []
for a, b in itertools.pairwise([0, 5, 8, 12, 15, 20, 25, 30, 40]):
    sa, _, _ = score_parcel(dict(base, slope=a), 'agriPV')
    sb, _, _ = score_parcel(dict(base, slope=b), 'agriPV')
    if sb > sa: viol.append(f'slope {a}%({sa}) -> {b}%({sb})')
check("Score: monotono su tutta la griglia di pendenza 0→40%",
      not viol, "aumentare la pendenza non deve mai far salire lo score",
      '; '.join(viol) or 'ok', 'D')

viol2 = []
for a, b in itertools.pairwise([0, 100, 500, 1000, 3000, 6000, 12000, 30000]):
    sa, _, _ = score_parcel(dict(base, d_se_m=a), 'BESS')
    sb, _, _ = score_parcel(dict(base, d_se_m=b), 'BESS')
    if sb > sa: viol2.append(f'{a}m({sa}) -> {b}m({sb})')
check("Score BESS: monotono su tutta la griglia di distanza SE 0→30km",
      not viol2, "allontanarsi dalla stazione non deve mai far salire lo score",
      '; '.join(viol2) or 'ok', 'D')

# ══════════════════════════════════════════════ E. COPERTURA / ONESTÀ
sezione("E. ONESTÀ — il tool sa cosa NON sa?")

for prov in ['BN', 'MI', 'AO', 'BZ']:
    c = copertura(prov)
    check(f"[{prov}] la copertura dichiara i layer mancanti",
          'sitap_mancanti' in c and 'habitat_fonte' in c,
          "ogni provincia deve sapere dire cosa non può verificare",
          f"regione={c['regione']} sitap={c['sitap']} mancanti={len(c.get('sitap_mancanti') or [])}", 'E')

tot = len(PROV_REGIONE)
con_sitap = sum(1 for p in PROV_REGIONE if copertura(p)['sitap'])
con_hab = sum(1 for p in PROV_REGIONE if copertura(p)['habitat_regionale'])
print(f"\n  Copertura reale: SITAP {con_sitap}/{tot} province · habitat regionale {con_hab}/{tot} · "
      f"VAM {st['n']}/{tot}")
check("Nessuna provincia si dichiara pienamente coperta se non lo è",
      con_hab < tot and st['n'] < tot,
      "il tool non deve mai millantare copertura totale",
      f"habitat regionale {con_hab}/{tot}, VAM {st['n']}/{tot}", 'E')

# ══════════════════════════════════════════════ REPORT
print("\n" + "=" * 74)
n_fail = sum(1 for *_, ok, _, _ in [(s, n, o, a, g) for s, n, o, a, g in ESITI] if not ok)
n_fail = sum(1 for e in ESITI if not e[2])
print(f"  RISULTATO: {len(ESITI)-n_fail}/{len(ESITI)} pass   ·   {n_fail} FAIL")
print("=" * 74)
for sez, nome, ok, att, ott in ESITI:
    if not ok:
        print(f"  ✗ [{sez}] {nome}\n      atteso: {att}\n      reale : {ott}")
sys.exit(1 if n_fail else 0)
