"""land-scout — modulo RECOMMEND (v0.1, 15/07/2026): quale energia rinnovabile per il terreno.

Dato un terreno (dati arricchiti: vincoli + pendenza + rete), raccomanda la
tecnologia migliore fra agriPV / BESS / FV a terra / eolico, con il perche' e
il "perche' no" delle altre. Riusa engine.score_parcel (BESS/agriPV gia' scorati)
e aggiunge le regole normative per FV-a-terra ed eolico.

Regole codificate (progetto Morcone, lug-2026):
- EOLICO: vietato in ZPS (DM 17/10/2007) → escluso se dentro ZPS.
- FV A TERRA (utility): su suolo agricolo vietato (D.Lgs 190/2024) → si usa agriPV;
  in ZPS su habitat 6220/6210 e' vietato del tutto.
- agriPV avanzato: default per terra agricola; in ZPS serve VINCA (gestibile se
  habitat sgombro); premia taglia e pendenza bassa.
- BESS: ideale per lotti piccoli/piatti VICINI alla stazione elettrica; non tocca
  il divieto habitat; la vicinanza alla SE e' il driver.

CLI:
  .venv/Scripts/python -m landscout.recommend --scan demo/scan_xxx.json   (arricchisce uno scan)
  .venv/Scripts/python -m landscout.recommend --demo                       (3 casi tipo)
"""
import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from landscout.engine import score_parcel

def _cl_verdetto(cl):
    return {'A': 'RACCOMANDATO', 'B': 'RACCOMANDATO', 'C': 'possibile', 'D': 'sconsigliato'}[cl]

def _key_reasons(flags):
    """estrae dai flag engine i motivi rilevanti per la scelta tecnologia."""
    keep = []
    for f in flags:
        if any(w in f for w in ('ZPS', 'HABITAT', 'pendenza', 'SE a', 'connessione', 'usi', 'fascia', 'bosco', 'ha:', 'soglia')):
            keep.append(f)
    return keep[:4]

def _num(v, default):
    """None/''/'abc' -> default. Senza questo, un campo vuoto nel form faceva esplodere
    score_parcel con TypeError: '<' not supported between 'NoneType' and 'float' (QA 16/07)."""
    if v is None or v == '':
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if f != f else f          # NaN -> default


def _normalizza(p):
    """Un parcel puo' arrivare da un form incompleto, da uno scan o da un JSON scritto a
    mano. Qui si riempiono SOLO i campi tecnici mancanti con default neutri e onesti:
    'non so' = 'lontanissimo' (9e9) per le distanze. Per i VINCOLI invece 'non so'
    resta None: un vincolo non verificato non e' un vincolo assente.
    La superficie NON ha default: senza ettari non c'e' niente da raccomandare."""
    q = dict(p or {})
    q['ha'] = _num(q.get('ha'), 0.0)
    q['slope'] = _num(q.get('slope'), None) if q.get('slope') is not None else None
    q['zps_pct'] = _num(q.get('zps_pct'), 0.0)
    q['zps_border_m'] = _num(q.get('zps_border_m'), 9e9)
    q['d_se_m'] = _num(q.get('d_se_m'), 9e9)
    q['d_150kv_m'] = _num(q.get('d_150kv_m'), 9e9)
    # ⚠️ 12/08/2026: qui `bool(...)` ANNULLAVA la correzione del 16/07 scritta tre
    # righe piu' sotto, dentro recommend(). Il campo assente ("non verificato")
    # diventava False ("nessun divieto"), quindi `hab_ignoto = hab_ban is None`
    # non poteva MAI essere vero e l'avviso "habitat NON verificato" non e' mai
    # uscito. Una correzione documentata in un commento e disfatta tre righe
    # sopra: i tre stati vanno tenuti tre anche qui.
    q['habitat_ban'] = None if q.get('habitat_ban') is None else bool(q['habitat_ban'])
    q['in_sic'] = None if q.get('in_sic') is None else bool(q['in_sic'])
    return q


def recommend(p, node=None):
    """p: parcel dict (engine.score_parcel-compatibile) con eventuali campi vincoli.
    node: {'pv_queue': bool, 'bess_queue_mw': float} contesto nodo (opzionale).

    Robusto a campi mancanti/None: normalizza prima di scorare. Se manca la superficie
    ritorna un esito esplicito invece di fingere una raccomandazione."""
    node = node or {}
    p = _normalizza(p)
    if p['ha'] <= 0:
        return {'top': None, 'opzioni': [],
                'errore': 'superficie mancante o non valida: senza ettari non si puo\' '
                          'raccomandare una tecnologia'}
    zps = p.get('zps_pct', 0) > 10
    # ⚠ QA 16/07: `bool(...)` trasformava None ("non verificato") in False ("nessun divieto")
    # = stesso schema del falso-pulito. Ora i tre stati restano tre: True / False / None.
    hab_ban = p.get('habitat_ban')
    hab_ignoto = hab_ban is None
    hab_ban = hab_ban is True
    R = []

    # --- agriPV ---
    if hab_ban:
        # ⚠ QA 16/07 (fuzz, 273 casi su 4000): agriPV veniva scorato lo stesso e poteva
        # VINCERE anche con divieto habitat, mentre valore.py azzerava il premio (p_auth=0).
        # Due moduli che dicevano il contrario sullo stesso fatto. Il divieto della DGR
        # 617/2024 riguarda il fotovoltaico su 6210/6220: l'agriPV e' un impianto FV, quindi
        # e' escluso quanto il FV a terra. Escluso qui = non puo' piu' finire in cima.
        R.append({'tech': 'agriPV', 'score': None, 'verdetto': 'ESCLUSO',
                  'reasons': ['habitat 6220/6210: impianti FV vietati in ZPS su questi habitat '
                              '(DGR Campania 617/2024) — vale anche per l\'agriPV sopraelevato']})
    else:
        s, cl, fl = score_parcel(dict(p), 'agriPV')
        e = {'tech': 'agriPV', 'score': s, 'classe': cl, 'verdetto': _cl_verdetto(cl),
             'reasons': _key_reasons(fl)}
        if node.get('pv_queue') is False:
            e['reasons'].append('coda FV vuota al nodo = primo arrivato')
        if hab_ignoto:
            e['reasons'].append('⚠ habitat NON verificato (fonte non raggiunta): se sotto ci '
                                'fosse 6210/6220 questa raccomandazione decade')
        R.append(e)

    # --- BESS ---
    # ⚠ 12/08/2026: il BESS era l'unica tecnologia che sopravviveva al divieto
    # habitat, sul presupposto che il divieto riguardasse "il fotovoltaico".
    # Non e' cosi': il sentito del Parco del Matese sulla CUP 31 di Morcone
    # elenca fra i divieti in 6210(*)/6220* la *modifica della destinazione
    # d'uso*. Una piattaforma di accumulo con recinzione e cabine e' una
    # modifica della destinazione d'uso, non un uso agricolo.
    if hab_ban:
        R.append({'tech': 'BESS', 'score': None, 'verdetto': 'ESCLUSO',
                  'reasons': ['habitat 6220/6210: vietata la modifica della destinazione '
                              'd\'uso (DGR Campania 617/2024) — il divieto non risparmia '
                              'l\'accumulo; precedente: rigetto CUP 31 Morcone']})
    else:
        s, cl, fl = score_parcel(dict(p), 'BESS')
        e = {'tech': 'BESS', 'score': s, 'classe': cl, 'verdetto': _cl_verdetto(cl),
             'reasons': _key_reasons(fl)}
        if node.get('bess_queue_mw'):
            e['reasons'].append(f'mercato storage attivo al nodo (~{node["bess_queue_mw"]:.0f} MW in coda) ma affollato: la velocita\' conta')
        if hab_ignoto:
            e['reasons'].append('⚠ habitat NON verificato: se sotto ci fosse 6210/6220 '
                                'anche il BESS decade')
        R.append(e)

    # --- FV a terra (utility) ---
    if hab_ban:
        R.append({'tech': 'FV a terra', 'score': None, 'verdetto': 'ESCLUSO',
                  'reasons': ['habitat 6220/6210: FV a terra vietato in ZPS (DGR Campania 617/2024)']})
    else:
        R.append({'tech': 'FV a terra', 'score': None, 'verdetto': 'sconsigliato',
                  'reasons': ['FV a terra su suolo agricolo vietato (D.Lgs 190/2024) → convertire in agriPV avanzato']
                             + (['⚠ habitat NON verificato: divieto 6210/6220 non escluso'] if hab_ignoto else [])})

    # --- eolico ---
    if zps:
        R.append({'tech': 'eolico', 'score': None, 'verdetto': 'ESCLUSO',
                  'reasons': ['eolico vietato in ZPS (DM 17/10/2007)']})
    else:
        R.append({'tech': 'eolico', 'score': None, 'verdetto': 'da valutare',
                  'reasons': ['fuori ZPS: possibile ma richiede atlante vento + scala + distanza abitazioni (non valutato dal tool)']})

    # --- pick top fra le scorate non escluse ---
    scored = [r for r in R if r.get('score') is not None and r['verdetto'] != 'ESCLUSO']
    top = max(scored, key=lambda r: r['score']) if scored else None
    sint = ''
    if top:
        sint = f"Tecnologia consigliata: {top['tech']} (voto {top['score']/10:.1f}, classe {top['classe']})"
        if top['tech'] == 'agriPV' and zps:
            sint += ' — via VINCA (iter ~2-3 anni; habitat sgombro = fattibile)'
        if top['tech'] == 'BESS':
            sint += ' — chiave = vicinanza alla stazione elettrica'
    # ordina il ranking: scorate per voto desc, poi le regole (escluso in fondo)
    R.sort(key=lambda r: (r.get('score') is None, -(r.get('score') or 0)))
    return {'ranking': R, 'top': top['tech'] if top else None, 'sintesi': sint}

def print_reco(pid, reco):
    print(f'\n### {pid}')
    print(f'  >>> {reco["sintesi"] or "nessuna tecnologia idonea"}')
    for r in reco['ranking']:
        sc = f"voto {r['score']/10:.1f}" if r.get('score') is not None else '—'
        mark = {'RACCOMANDATO': '✅', 'possibile': '🟡', 'da valutare': '🔵',
                'sconsigliato': '🟠', 'ESCLUSO': '⛔'}.get(r['verdetto'], '·')
        print(f'   {mark} {r["tech"]:<12} {r["verdetto"]:<13} {sc}')
        for x in r['reasons']:
            print(f'        - {x}')

# ---------- CLI ----------
DEMO = {
    'Fg.70 P.142 (famiglia, ZPS, lontano SE)': {
        'ha': 1.97, 'slope': 7.3, 'zps_pct': 100, 'zps_border_m': -1,
        'habitat_ban': False, 'in_sic': False, 'd_se_m': 4600, 'd_150kv_m': 3700},
    'P.276 Campolattaro (buffer ZPS, vicino-ish SE)': {
        'ha': 1.28, 'slope': 4.0, 'zps_pct': 0, 'zps_border_m': 5,
        'habitat_ban': False, 'd_se_m': 3000, 'd_150kv_m': 2800},
    'Cuffiano zona A (fuori ZPS, piatto, adiacente SE)': {
        'ha': 1.87, 'slope': 4.5, 'zps_pct': 0, 'zps_border_m': 1700,
        'habitat_ban': False, 'd_se_m': 36, 'd_150kv_m': 8},
}
# ⚠ Il contesto nodo (code di connessione) e' SPECIFICO DEL NODO: va letto dal registro
# rete.py per il comune giusto. Qui resta solo per la demo, che dichiara di essere Morcone.
# Bug QA 16/07: `--scan` applicava questa costante a QUALUNQUE particella d'Italia, cosi'
# un terreno in Puglia si sentiva dire "coda FV vuota, 699 MW BESS" = i numeri di Morcone.
_NODE_DEMO_MORCONE = {'pv_queue': False, 'bess_queue_mw': 699}

def main():
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', help='JSON prodotto da scan.py --vincoli: aggiunge reco a ogni particella')
    ap.add_argument('--demo', action='store_true', help='3 casi tipo (Morcone)')
    ap.add_argument('--comune', help='comune del nodo, per leggere le code dal registro rete')
    ap.add_argument('--prov', help='sigla provincia (obbligatoria con --comune)')
    ap.add_argument('--out')
    A = ap.parse_args()
    if A.demo:
        print('=' * 78 + '\n  RACCOMANDAZIONE TECNOLOGIA — casi tipo (nodo Morcone: no coda FV, 699 MW BESS)\n' + '=' * 78)
        for pid, p in DEMO.items():
            print_reco(pid, recommend(p, _NODE_DEMO_MORCONE))
        return
    if A.scan:
        # il nodo si legge dal registro per il comune indicato; se non e' indicato,
        # NESSUN contesto nodo (meglio tacere che riportare le code di un altro posto)
        node = {}
        if A.comune and A.prov:
            from landscout.rete import contesto_nodo
            node = contesto_nodo(A.comune, A.prov) or {}
            if not node:
                print(f'⚠ nodo {A.comune} ({A.prov}) non nel registro: nessun contesto code di connessione')
        elif A.comune or A.prov:
            print('⚠ --comune e --prov vanno insieme: ignorati, nessun contesto nodo')
        else:
            print('ℹ nessun --comune/--prov: raccomando senza contesto code di connessione '
                  '(prima qui veniva applicato per sbaglio il nodo di Morcone)')
        d = json.load(open(A.scan, encoding='utf-8'))
        recs = d.get('risultati', d if isinstance(d, list) else [])
        for r in recs:
            p = {'ha': r.get('ha', 0), 'slope': r.get('slope'),
                 'zps_pct': r.get('n2k_pct', 0), 'zps_border_m': r.get('n2k_border_m') or 9e9,
                 'habitat_ban': r.get('habitat_ban', False), 'in_sic': r.get('in_sic', False),
                 'd_se_m': r.get('d_se_m', 9e9), 'd_150kv_m': r.get('d_150kv_m', 9e9)}
            r['reco'] = recommend(p, node)
        outp = A.out or (A.scan.replace('.json', '') + '_reco.json')
        json.dump(d, open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('salvato:', outp, f'({len(recs)} particelle con raccomandazione)')
        return
    print('Uso: --demo  oppure  --scan <scan.json> [--comune X --prov YY]')

if __name__ == '__main__':
    main()
