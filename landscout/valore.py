"""land-scout — VALORE (v0.2, 16/07/2026): quanto puo' valere questa terra, e quanto NON lo sappiamo.

## Perche' questo modulo e' stato riscritto da zero

La v0.1 faceva letteralmente questo:

    EUR_HA_TERRA = {'secco': 20_000, 'target_postvinca': 50_000, 'apertura': 60_000}
    val = {k: round(v * tot_ha / 1000) * 1000 for k, v in EUR_HA_TERRA.items()}

Tre costanti prese dalla trattativa Morcone di luglio 2026, moltiplicate per gli ettari.
Conseguenze, tutte confermate in QA:
  - un terreno in Puglia valeva ESATTAMENTE quanto uno a Morcone a parita' di ettari:
    il valore non era funzione ne' del luogo, ne' dei vincoli, ne' della resa, ne' della rete;
  - "apertura" era una POSIZIONE NEGOZIALE di un singolo deal (per giunta poi
    giudicata non difendibile) spacciata come valore di mercato nazionale;
  - un terreno con divieto assoluto valeva quanto uno pulito.

## Il principio nuovo

**Nessun numero senza una fonte, e nessun numero che non si muova con gli input.**
Dove il dato non c'e', si scrive `None` e si dice perche' — non si mette una costante.
Un "non lo so" esplicito vale piu' di una cifra precisa e inventata: chi legge puo'
andarlo a cercare, mentre una cifra falsa la usa e ci sbatte contro (cfr. il teaser
"area libera da vincoli" che e' costato un developer).

## La catena del valore (ogni gradino ha una fonte diversa)

  1. AGRICOLO      quanto vale come campo. Fonte vera = VAM (Valori Agricoli Medi,
                   pubblicati per provincia+coltura dall'Agenzia delle Entrate).
                   NON ANCORA CARICATI -> qui si dichiara la banda nazionale e si
                   segnala che varia ~10x per provincia. E' un lavoro di data-sourcing.
  2. OPZIONALITA'  premio per "terra che un developer puo' usare". Esiste solo se il
                   progetto e' plausibile: se c'e' un divieto, questo gradino sparisce.
  3. RTB PROGETTO  quanto vale il PROGETTO autorizzato (€/MWp). ATTENZIONE: e' valore
                   del developer, non del proprietario. Serve come tetto, non come ask.
  4. P_AUTH        probabilita' grossolana che l'iter passi, dai vincoli trovati.
                   Modula i gradini 2 e 3. E' una banda, non un numero fine.

CLI:
  .venv/Scripts/python -m landscout.valore --ha 12.28 --tech agriPV --zps
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

from landscout.config import MWP_HA
from landscout.vam import vam as vam_prov

# ---------------------------------------------------------------- fonti dichiarate
# Ogni banda porta con se' la sua provenienza: se non sai dire da dove viene, non ci va.
FONTI = {
    'agricolo_nazionale': ('⚠ banda NAZIONALE grezza — VAM non caricato per questa provincia. '
                           'Il valore vero varia fino a 5x fra province (verificato: seminativo '
                           'Roma 11.900–52.000 €/ha vs Viterbo 12.450–19.950). Ordine di '
                           'grandezza, non un prezzo.'),
    'opzionalita': 'mercato terra con opzionalita\' rinnovabile, ricerca lug-2026',
    'rtb_pv': 'FV Ready-To-Build 72–150 k€/MWp (pv-magazine / nTeaser, apr-2026)',
    'rtb_bess': 'BESS Ready-To-Build 15–48 k€/MW (pv-magazine / nTeaser, apr-2026)',
}

EUR_HA_AGRICOLO = (10_000, 25_000)      # nazionale, varia ~5x per provincia e coltura
EUR_MWP_RTB = (72_000, 150_000)         # progetto FV autorizzato
EUR_MW_RTB_BESS = (15_000, 48_000)      # progetto BESS autorizzato

# ⚠ L'opzionalita' e' un MOLTIPLICATORE sul valore agricolo, non una banda assoluta.
# Bug trovato appena sono entrati i VAM veri (16/07): con la banda assoluta 25-45 k€/ha,
# a Roma il "pavimento" agricolo (fino a 52 k€/ha da VAM) finiva SOPRA il "premio"
# rinnovabile (45 k€/ha) -> scala non monotona, cioe' un assurdo: nessuno cede a 45 un
# terreno che come campo ne vale 52. La banda 25-45 k€/ha veniva dalla ricerca su Morcone,
# dove l'agricolo sta sui 10-20 k€/ha: era quindi un moltiplicatore ~2x travestito da
# costante. Espresso come moltiplicatore, il gradino e' coerente ovunque per costruzione.
MOLT_OPZIONALITA = (1.5, 2.5)           # quanto paga un developer sopra il valore agricolo


def p_auth(vincoli):
    """Probabilita' GROSSOLANA che l'iter autorizzativo passi, dai vincoli trovati.

    Volutamente a bande larghe: una stima fine richiede lo studio di sito (per Morcone
    sono servite settimane di overlay + un precedente VINCA + un decreto BURC letto riga
    per riga, e comunque il numero e' passato da 0,65 a 0,50-0,55 dopo UNA mail).
    Qui serve solo a non trattare un terreno bloccato come uno pulito.
    """
    if vincoli.get('habitat_ban'):
        return 0.0, ('divieto di modifica della destinazione d\'uso su habitat 6210/6220 '
                     '(DGR Campania 617/2024): non esiste il progetto solare, e nemmeno '
                     'quello di accumulo')
    if vincoli.get('usi_civici'):
        return 0.15, 'usi civici: il titolo non e\' liberamente disponibile finche\' non e\' affrancato'
    if vincoli.get('sic'):
        return 0.35, 'dentro SIC/ZSC: incidenza diretta su habitat e specie Direttiva Habitat'
    if vincoli.get('zps'):
        return 0.50, ('dentro ZPS: nessuna preclusione automatica ma iter ordinario con VINCA '
                      '(banda 0,4–0,6 — il valore vero dipende dallo studio di sito)')
    return 0.75, 'fuori Natura 2000: iter ordinario senza VINCA'


def _banda(lo, hi, q):
    return (int(round(lo * q / 1000) * 1000), int(round(hi * q / 1000) * 1000))


def _gradino_agricolo(tot_ha, prov):
    """Il pavimento agricolo: VAM provinciale se caricato, altrimenti banda nazionale
    DICHIARATA come tale. Nessun ripiego silenzioso: era esattamente il bug originale."""
    v = vam_prov(prov, 'seminativo') if prov else None
    if not v:
        return {
            'nome': 'Valore agricolo (pavimento)',
            'range_eur': _banda(*EUR_HA_AGRICOLO, tot_ha),
            'eur_ha': EUR_HA_AGRICOLO,
            'fonte': FONTI['agricolo_nazionale'],
            'base': 'nazionale',
            'nota': ('quanto vale come campo. Per questa provincia il VAM ufficiale non e\' '
                     'caricato: carica il PDF dell\'Agenzia delle Entrate con '
                     '`python -m landscout.vam --carica <pdf> --prov XX --anno AAAA`'),
        }
    lo, hi = v['eur_ha']
    return {
        'nome': f'Valore agricolo — VAM {v["prov"]} {v["anno"]} (seminativo)',
        'range_eur': _banda(lo, hi, tot_ha),
        'eur_ha': (lo, hi),
        'fonte': f'VAM ufficiale Commissione Provinciale Espropri · {v["fonte"]} · '
                 f'{v["n_ra"]} regioni agrarie',
        'base': 'vam',
        'anno': v['anno'],
        'nota': ('⚠ il VAM e\' un valore AMMINISTRATIVO di esproprio, sistematicamente SOTTO il '
                 'mercato (Corte Cost. 181/2011 lo ha bocciato come criterio unico proprio per '
                 'questo): leggilo come PAVIMENTO, il venale reale sta sopra. Il range copre '
                 'tutte le regioni agrarie della provincia — per il valore puntuale serve sapere '
                 'in quale regione agraria cade il terreno.'),
    }


def valore(tot_ha, vincoli=None, tech='agriPV', copertura=None, prov=None):
    """Ritorna la catena del valore. Ogni voce: {range|None, fonte, nota}.

    tot_ha  : ettari totali
    vincoli : {'zps','sic','habitat_ban','usi_civici', ...} (da vincoli.feasibility)
    tech    : 'agriPV' | 'PV' | 'BESS'
    prov    : sigla provincia -> abilita il VAM ufficiale al posto della banda nazionale
    """
    vincoli = vincoli or {}
    cov = copertura or {}
    prov = prov or cov.get('prov')
    try:
        tot_ha = float(tot_ha)
    except (TypeError, ValueError):
        tot_ha = 0.0
    if not (tot_ha > 0):
        return {'errore': 'superficie non valida: servono ettari > 0', 'tot_ha': tot_ha}

    p, perche_p = p_auth(vincoli)
    out = {'tot_ha': round(tot_ha, 2), 'tech': tech, 'p_auth': p, 'p_auth_perche': perche_p,
           'gradini': [], 'avvisi': [], 'confidenza': 'bassa'}

    # --- 1. agricolo: sempre presente, e' il pavimento
    g_agr = _gradino_agricolo(tot_ha, prov)
    out['gradini'].append(g_agr)
    out['base_agricola'] = g_agr['base']
    if g_agr['base'] == 'nazionale':
        out['avvisi'].append(
            f'VAM ufficiale NON caricato per {prov or "questa provincia"}: il pavimento agricolo '
            'e\' una banda nazionale, da leggere come ordine di grandezza. Fra province reali il '
            'seminativo varia fino a 5x — quindi qui l\'errore possibile e\' grande.')

    # --- 2. opzionalita': esiste solo se il progetto e' plausibile
    if p <= 0.0:
        out['gradini'].append({
            'nome': 'Premio opzionalita\' rinnovabile',
            'range_eur': None,
            'fonte': FONTI['opzionalita'],
            'nota': f'AZZERATO: {perche_p}. Qui la terra vale il suo valore agricolo, nient\'altro.',
        })
        out['sintesi'] = ('Nessun premio rinnovabile: il vincolo trovato esclude il progetto. '
                          'Il valore e\' quello agricolo.')
        return out

    # opzionalita' = agricolo x moltiplicatore -> monotona per costruzione, ovunque
    a_lo, a_hi = g_agr['eur_ha']
    o_lo, o_hi = a_lo * MOLT_OPZIONALITA[0], a_hi * MOLT_OPZIONALITA[1]
    out['gradini'].append({
        'nome': 'Terra con opzionalita\' rinnovabile',
        'range_eur': _banda(o_lo, o_hi, tot_ha),
        'eur_ha': (round(o_lo), round(o_hi)),
        'moltiplicatore': MOLT_OPZIONALITA,
        'fonte': f"{FONTI['opzionalita']} — {MOLT_OPZIONALITA[0]}–{MOLT_OPZIONALITA[1]}x "
                 f"sul valore agricolo ({'VAM ufficiale' if g_agr['base'] == 'vam' else 'banda nazionale'})",
        'nota': 'quanto paga un developer per terra grezza utilizzabile, PRIMA dei permessi',
    })

    # --- 3. valore RTB del PROGETTO (non del proprietario!)
    if tech in ('agriPV', 'PV'):
        mwp_lo, mwp_hi = MWP_HA.get(tech, MWP_HA['agriPV'])
        mwp = (tot_ha * mwp_lo, tot_ha * mwp_hi)
        rtb = (mwp[0] * EUR_MWP_RTB[0], mwp[1] * EUR_MWP_RTB[1])
        fonte = FONTI['rtb_pv']
    elif tech == 'BESS':
        mwp = (tot_ha * 2.0, tot_ha * 4.0)          # densita' indicativa MW/ha per storage
        rtb = (mwp[0] * EUR_MW_RTB_BESS[0], mwp[1] * EUR_MW_RTB_BESS[1])
        fonte = FONTI['rtb_bess']
        out['avvisi'].append('Densita\' MW/ha per BESS: indicativa, dipende da taglia e layout.')
    else:
        mwp, rtb, fonte = None, None, None

    if rtb:
        out['gradini'].append({
            'nome': f'Valore progetto RTB ({mwp[0]:.1f}–{mwp[1]:.1f} MW)',
            'range_eur': (int(round(rtb[0] / 1000) * 1000), int(round(rtb[1] / 1000) * 1000)),
            'range_eur_ponderato': (int(round(rtb[0] * p / 1000) * 1000),
                                    int(round(rtb[1] * p / 1000) * 1000)),
            'fonte': fonte,
            'nota': ('⚠ questo NON e\' il valore della tua terra: e\' quanto vale il PROGETTO '
                     'autorizzato, e lo incassa chi lo sviluppa (che ne paga capex, iter e rischio). '
                     'Serve come tetto della trattativa, mai come richiesta.'),
        })
        out['avvisi'].append(
            f'Il valore RTB e\' ponderato per p_auth={p:.0%} ({perche_p}). '
            'Senza permessi il progetto vale una frazione di quel numero.')

    out['confidenza'] = ('media' if (cov.get('habitat_regionale') and cov.get('sitap')
                                     and out.get('base_agricola') == 'vam') else 'bassa')
    out['sintesi'] = (
        f'Pavimento agricolo {out["gradini"][0]["range_eur"][0]:,}–{out["gradini"][0]["range_eur"][1]:,} €; '
        f'con opzionalita\' {out["gradini"][1]["range_eur"][0]:,}–{out["gradini"][1]["range_eur"][1]:,} €. '
        f'Probabilita\' autorizzativa stimata {p:.0%}.').replace(',', '.')
    return out


def descrivi(v):
    if 'errore' in v:
        return f'   ✗ {v["errore"]}'
    L = []
    e = lambda x: ('€{:,}'.format(int(x))).replace(',', '.')
    for g in v['gradini']:
        if g['range_eur'] is None:
            L.append(f'   • {g["nome"]}: — {g["nota"]}')
            continue
        L.append(f'   • {g["nome"]}: {e(g["range_eur"][0])} – {e(g["range_eur"][1])}')
        if g.get('range_eur_ponderato'):
            L.append(f'       ponderato per p_auth: {e(g["range_eur_ponderato"][0])} – {e(g["range_eur_ponderato"][1])}')
        L.append(f'       fonte: {g["fonte"]}')
        L.append(f'       {g["nota"]}')
    L.append(f'   Probabilita\' autorizzativa (grossolana): {v["p_auth"]:.0%} — {v["p_auth_perche"]}')
    L.append(f'   Confidenza complessiva: {v["confidenza"].upper()}')
    for a in v['avvisi']:
        L.append(f'   ⚠ {a}')
    L.append('   Questo NON e\' una perizia: e\' uno screening su dati pubblici.')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ha', type=float, required=True)
    ap.add_argument('--tech', default='agriPV')
    ap.add_argument('--zps', action='store_true'); ap.add_argument('--sic', action='store_true')
    ap.add_argument('--habitat-ban', action='store_true'); ap.add_argument('--usi-civici', action='store_true')
    ap.add_argument('--prov', help='sigla provincia: abilita il VAM ufficiale se caricato')
    ap.add_argument('--json', action='store_true')
    A = ap.parse_args()
    v = valore(A.ha, {'zps': A.zps, 'sic': A.sic, 'habitat_ban': A.habitat_ban,
                      'usi_civici': A.usi_civici}, tech=A.tech, prov=A.prov)
    print(json.dumps(v, ensure_ascii=False, indent=1) if A.json else descrivi(v))


if __name__ == '__main__':
    main()
