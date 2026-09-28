"""land-scout — DOSSIER TERRENO (v0.1, 15/07/2026): i 3 moduli in un unico output.

Compone il flusso prodotto completo per un set di particelle:
  1. FATTIBILITA'   (vincoli.py)   — è autorizzabile? habitat/ZPS/SIC/usi civici
  2. TECNOLOGIA     (recommend.py) — quale energia rinnovabile è adatta
  3. VALORE         (anchor progetto) — forbice € indicativa
  4. AZIENDE        (match.py)     — chi contattare, vicino e in target

È l'output che un proprietario riceverebbe (base del report web/PDF) e la demo
da mostrare a un developer.

CLI:
  .venv/Scripts/python -m landscout.dossier --parcels <{id:{lat,lon,ha[,slope]}}.json> --comune Morcone --prov BN [--tech agriPV] [--out d.json]
"""
import argparse, json, math, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
from collections import Counter
from landscout import vincoli as VC
from landscout.recommend import recommend
from landscout.match import match_companies
from landscout.resa import resa_terreno

from landscout.config import copertura as COPERTURA, valida_coordinate, CoordinataNonValida
from landscout.geo import risolvi as risolvi_luogo
from landscout.valore import valore as calcola_valore, descrivi as descrivi_valore
from landscout.rete import (contesto_nodo, nodo as nodo_info, descrivi as descrivi_nodo,
                            distanza_rete, descrivi_distanza)

def parcella_motore(p, v):
    """Particella + risultato vincoli -> dict per recommend/engine.

    zps_pct e' la frazione REALE di superficie in ZPS (overlay sul poligono
    catastale); col solo centroide resta 0/100. ⚠ 28/09/2026: con l'EEA non
    raggiunta (`zps` None) qui usciva 0.0 = "verificato fuori ZPS"; ora None,
    e a valle diventa un avviso invece di una buona notizia.
    """
    zpct = v.get('zps_pct')
    if zpct is None and v.get('zps') is not None:
        zpct = 100.0 if v['zps'] else 0.0
    zbd = None if zpct is None else (-1 if zpct > 0 else 9e9)
    ep = {'ha': p['ha'], 'slope': p.get('slope'),
          'd_se_m': p.get('d_se_m', 9e9), 'd_150kv_m': p.get('d_150kv_m', 9e9)}
    # ⚠ 28/09/2026: qui passavano solo ZPS e habitat. PAI, usi civici, bosco, fasce
    # e art.136 — che feasibility aveva appena misurato — non arrivavano al motore:
    # una particella su frana P4 (verdetto BLOCK_PAI) usciva "agriPV RACCOMANDATO,
    # voto 10". to_score_fields e' la traduzione unica gia' esistente, con i tre stati.
    ep.update(VC.to_score_fields(v))
    ep.update({'zps_pct': zpct, 'zps_border_m': zbd,
               'habitat_ban': v.get('habitat_ban'), 'in_sic': v.get('sic')})
    return ep


def con_rete(parcels, rd):
    """Porta la distanza dalla SE misurata dal dossier (rete.distanza_rete, sul blocco)
    alle particelle che non ne hanno una propria. ⚠ 28/09/2026: la distanza veniva
    calcolata DOPO la raccomandazione e non arrivava al motore — ogni particella
    prendeva -12 con "SE non individuata" mentre la sezione ③ dello stesso dossier
    diceva "stazione a 300 m". Overpass giu' -> nessuna distanza inventata."""
    if not (rd or {}).get('verificato') or rd.get('d_se_m') is None:
        return parcels
    return {i: (p if p.get('d_se_m') is not None else dict(p, d_se_m=rd['d_se_m']))
            for i, p in parcels.items()}


def con_pendenza(parcels, _pendenza=None):
    """Misura la pendenza sul poligono catastale dove manca (prossimita.pendenza:
    TINITALY 10 m, ripiego opentopodata). Ritorna (parcels, note).

    Il dossier non la misurava: la raccomandazione girava con `slope=None` — e oltre
    il 15% l'agriPV non si fa. DEM muto o poligono assente: la pendenza resta None
    (NON verificata, mai assunta buona) e una nota lo dice. Non alza.
    """
    note = []
    da_misurare = {i: p for i, p in parcels.items() if p.get('slope') is None}
    senza_poly = [i for i, p in da_misurare.items() if not p.get('anello')]
    for i in senza_poly:
        note.append(f'{i}: pendenza NON verificata (manca il poligono catastale)')
    part = [{'fg': 'p', 'pla': i, 'poly': p['anello']}
            for i, p in da_misurare.items() if p.get('anello')]
    if not part:
        return parcels, note
    try:
        if _pendenza is None:
            # il dossier e' interattivo (pagina web): timeout corto per richiesta E
            # budget totale per fonte, altrimenti con TINITALY appeso 5 campioni in
            # fila a particella fermerebbero tutto per minuti
            from landscout.prossimita import pendenza
            r = pendenza(part, timeout=10, budget_s=45)
        else:
            r = _pendenza(part)
    except Exception as e:
        note.append(f'pendenza NON verificata ({type(e).__name__}): DEM non raggiunto')
        return parcels, note
    out = dict(parcels)
    for x in part:
        v = (r.get('particelle') or {}).get(f"p_{x['pla']}") or {}
        if v.get('verificata') and v.get('pendenza_pct') is not None:
            out[x['pla']] = dict(parcels[x['pla']], slope=v['pendenza_pct'])
        else:
            note.append(f"{x['pla']}: pendenza NON verificata (DEM muto su questa particella)")
    return out, note


def solidita(parcels, vinc, tech):
    """Forbice di verifica per particella (vedi forbice.py): quanto regge il voto se
    le fonti che non hanno risposto rispondessero male. Nel dossier e' la risposta
    alla domanda del proprietario: "posso fidarmi di questo esito?"."""
    from landscout.forbice import forbice, compatta
    per = {i: compatta(forbice(parcella_motore(parcels[i], vinc[i]), tech)) for i in parcels}
    fragili = [i for i, f in per.items() if f['bloccanti_ignoti']]
    return {'particelle': per, 'fragili': len(fragili), 'n': len(per),
            'verifica_prima': per[fragili[0]]['verifica_prima'] if fragili else None}


def vincoli_blocco(vinc):
    """Vincoli per particella -> vincoli del blocco, a tre stati.

    True se il vincolo e' stato TROVATO su almeno una particella (un divieto
    trovato vince sul dubbio); None se non e' stato trovato ma almeno una
    particella non e' stata verificata; False solo se verificato ovunque.
    Prima era `any(...)`: il None diventava False, e `valore.p_auth` scriveva
    "fuori Natura 2000: iter ordinario" su un blocco che l'EEA non aveva visto.
    """
    def tre(k):
        vals = [v.get(k) for v in vinc.values()]
        if any(vals):
            return True
        return None if any(x is None for x in vals) else False
    return {'zps': tre('zps'), 'sic': tre('sic'), 'habitat_ban': tre('habitat_ban'),
            # usi civici: SITAP non raggiunto e' gia' dichiarato a parte (sitap_ok)
            'usi_civici': any(v.get('usi_civici') is True for v in vinc.values())}


def build_dossier(parcels, comune=None, prov=None, tech=None, node=None, geo=True):
    """comune/prov sono OPZIONALI: si ricavano dalle coordinate (geo.risolvi).
    Se l'utente li passa e non tornano, vincono le coordinate e si avvisa."""
    if not parcels:
        raise ValueError('nessuna particella: serve almeno un punto con lat, lon e ha')
    ids = list(parcels)
    for i in ids:                     # validazione PRIMA di toccare qualunque servizio esterno
        p = parcels[i]
        lat, lon = valida_coordinate(p.get('lat'), p.get('lon'))
        p['lat'], p['lon'] = lat, lon
        try:
            p['ha'] = float(p.get('ha'))
        except (TypeError, ValueError):
            raise ValueError(f'particella "{i}": superficie non valida ({p.get("ha")!r}), servono ettari numerici')
        if not (p['ha'] > 0):
            raise ValueError(f'particella "{i}": superficie deve essere > 0 ettari (ricevuto {p["ha"]})')

    tot_ha = sum(parcels[i]['ha'] for i in ids)
    lat0 = sum(parcels[i]['lat'] for i in ids)/len(ids)
    lon0 = sum(parcels[i]['lon'] for i in ids)/len(ids)

    # 0. DOVE siamo davvero: la mappa vince sui campi digitati a mano
    comune, prov, avvisi_luogo = risolvi_luogo(lat0, lon0, comune, prov)

    # 0-bis. GEOMETRIA vera dal catasto: senza, gli overlay campionano solo il centroide e
    # ogni percentuale esce sottostimata (un vincolo che entra da un bordo e' invisibile).
    from landscout.catasto import arricchisci as arricchisci_catasto
    parcels, note_catasto = arricchisci_catasto(parcels)
    avvisi_luogo = list(avvisi_luogo) + note_catasto
    # 0-ter. pendenza sul poligono: senza, ogni raccomandazione agriPV ignorava il 15%
    parcels, note_pend = con_pendenza(parcels)
    avvisi_luogo += note_pend

    # contesto nodo dal registro rete: se il nodo non e' noto -> {} (nessuna affermazione inventata)
    if node is None:
        node = contesto_nodo(comune, prov)

    # 1. fattibilita' (prov -> determina la copertura: habitat/SITAP sono regionali)
    vinc = VC.feasibility(parcels, prov=prov)
    cov = COPERTURA(prov)

    # 2. tecnologia per particella — con la distanza dalla rete gia' misurata
    rete_dist = distanza_rete([(parcels[i]['lat'], parcels[i]['lon']) for i in ids])
    p_motore = con_rete({i: parcels[i] for i in ids}, rete_dist)
    recos = {}
    for i in ids:
        recos[i] = recommend(parcella_motore(p_motore[i], vinc[i]), node)

    verdetti = Counter(vinc[i]['verdetto'] for i in ids)
    ha_ban = sum(parcels[i]['ha'] for i in ids if vinc[i].get('habitat_ban'))
    uc = sum(1 for i in ids if vinc[i].get('usi_civici') is True)
    sitap_ok = all(vinc[i].get('sitap_ok', True) for i in ids)
    # "0 ha su habitat vietato" vale solo se la carta habitat ha risposto: senza,
    # la stampa diceva "✅ non rilevato" su un controllo mai eseguito.
    habitat_ok = all(vinc[i].get('habitat_ok') is not False for i in ids)
    n2k_ok = all(vinc[i].get('n2k_ok') is not False for i in ids)
    tech_dist = Counter(recos[i]['top'] for i in ids if recos[i]['top'])
    block_tech = tech or (tech_dist.most_common(1)[0][0] if tech_dist else 'agriPV')
    # quanto regge l'esito se le fonti mute rispondessero male (forbice.py)
    sol = solidita(p_motore, vinc, block_tech)

    # 3. resa energetica (PVGIS) — solo per tecnologie solari
    resa = resa_terreno(tot_ha, lat0, lon0, block_tech if block_tech in ('agriPV', 'PV') else 'agriPV')

    # 4. valore — funzione di superficie + vincoli + tecnologia + copertura.
    #    (prima era 3 costanti di Morcone x ettari: stesso € ovunque in Italia)
    val = calcola_valore(tot_ha, vincoli_blocco({i: vinc[i] for i in ids}),
                         tech=block_tech, copertura=cov, prov=prov)

    # 5. aziende (sulla tecnologia dominante)
    aziende = match_companies(comune, prov, [lat0, lon0], block_tech, geo=geo)

    return {'comune': comune, 'prov': prov, 'n': len(ids), 'tot_ha': round(tot_ha, 2),
            'centroide': [round(lat0, 5), round(lon0, 5)],
            'avvisi_luogo': avvisi_luogo,
            'fattibilita': {'verdetti': dict(verdetti), 'ha_habitat_vietato': round(ha_ban, 2),
                            'usi_civici_n': uc, 'sitap_ok': sitap_ok,
                            'habitat_ok': habitat_ok, 'n2k_ok': n2k_ok, 'copertura': cov},
            'solidita': sol,
            'tecnologia': {'consigliata': block_tech, 'distribuzione': dict(tech_dist)},
            'rete': nodo_info(comune, prov),
            'rete_distanza': rete_dist,
            'resa': resa, 'valore_eur': val, 'aziende': aziende[:6],
            'vincoli_per_particella': {i: vinc[i]['verdetto'] for i in ids},
            'reco_per_particella': {i: recos[i]['top'] for i in ids}}

def print_dossier(d):
    L = '═'*82
    print('\n'+L+f'\n  DOSSIER TERRENO — {d["comune"]} ({d["prov"]})   ·   {d["n"]} particelle · {d["tot_ha"]} ha\n'+L)
    for a in (d.get('avvisi_luogo') or []):
        print(f'\n⚠ {a}')
    f = d['fattibilita']
    print('\n① FATTIBILITÀ AUTORIZZATIVA')
    print(f'   Verdetti: {f["verdetti"]}')
    cov = f.get('copertura') or {}
    reg = cov.get('regione') or 'regione ignota'
    aut = cov.get('habitat_regionale')
    if f['ha_habitat_vietato']:
        esito_hab = '⛔ presente'
    elif f.get('habitat_ok') is False:
        esito_hab = '⚠ NON VERIFICATO (fonte habitat non raggiunta: il divieto non e escluso)'
    else:
        esito_hab = '✅ non rilevato'
    print(f'   Habitat divieto FV: {f["ha_habitat_vietato"]} ha  →  {esito_hab}'
          f'   [fonte: {cov.get("habitat_fonte")}]')
    if f.get('n2k_ok') is False:
        print('   Natura 2000 (ZPS/SIC): ⚠ NON VERIFICATO — EEA non raggiunta, confini da controllare')
    if not aut:
        print(f'      ⚠ carta regionale assente per {reg}: uso ISPRA 1:50.000 + corrispondenza ufficiale CORINE→Direttiva Habitat.')
        print('        Fondato ma a scala grossolana: conferma sulla cartografia regionale prima di decidere.')
    if not cov.get('sitap'):
        print(f'   Usi civici / paesaggio: ⚠ NON VERIFICATI — SITAP non copre {reg}')
    else:
        manc = cov.get('sitap_mancanti') or []
        if 'usi_civici' in manc:
            print(f'   Usi civici: ⚠ NON VERIFICABILI — SITAP non ha il layer usi civici per {reg}')
        else:
            print(f'   Usi civici (titolo): ' + ('DA VERIFICARE (SITAP non raggiunto)' if not f['sitap_ok']
                  else (f'{f["usi_civici_n"]} particelle DA VERIFICARE' if f['usi_civici_n'] else '✅ nessuno (titolo libero)')))
        if manc:
            print(f'      controlli non disponibili in {reg}: {", ".join(manc)}')
    sol = d.get('solidita')
    if sol:
        if sol['fragili']:
            print(f"   Solidità dell esito: ⚠ {sol['fragili']}/{sol['n']} particelle con voto "
                  f"FRAGILE — una fonte non raggiunta puo' bloccarle. Verifica prima: "
                  f"{sol['verifica_prima']}")
        else:
            print('   Solidità dell esito: ✓ nessuna fonte muta puo\' ribaltare il voto')
    t = d['tecnologia']
    print('\n② TECNOLOGIA CONSIGLIATA')
    print(f'   ➜ {t["consigliata"].upper()}   (distribuzione particelle: {t["distribuzione"]})')
    if t['consigliata'] == 'agriPV':
        in_zps = any('VINCA' in k for k in (d['fattibilita'].get('verdetti') or {}))
        if in_zps:
            print('   Motivo: terra agricola in ZPS → eolico escluso (DM 2007), FV a terra vietato su agricolo '
                  '(D.Lgs 190/2024) → agriPV avanzato sopraelevato, via VINCA.')
        elif f.get('n2k_ok') is False:
            print('   Motivo: terra agricola → FV a terra vietato su agricolo (D.Lgs 190/2024) → agriPV '
                  'avanzato. ⚠ Natura 2000 NON verificato: se fosse ZPS servirebbe la VINCA '
                  'e l eolico sarebbe escluso.')
        else:
            print('   Motivo: terra agricola fuori Natura 2000 → FV a terra vietato su agricolo (D.Lgs 190/2024) '
                  '→ agriPV avanzato. Eolico: da valutare (serve atlante vento, non calcolato).')
    print('\n③ RETE / CONNESSIONE')
    print(descrivi_distanza(d.get('rete_distanza')))
    print('   ' + descrivi_nodo(d.get('rete') or {'verificato': False, 'comune': d['comune'],
                                                  'prov': d['prov'], 'nota': 'registro non disponibile'}))
    r = d.get('resa') or {}
    print('\n④ PRODUZIONE ATTESA (PVGIS)')
    if 'error' in r:
        print('   n.d. — PVGIS non raggiungibile:', r['error'])
    else:
        print(f'   Resa sito: {r["kwh_per_kwp"]} kWh/kWp/anno ({r["config"]})')
        print(f'   Impianto:  {r["mwp"][0]}–{r["mwp"][1]} MWp  →  {r["mwh_anno"][0]:,}–{r["mwh_anno"][1]:,} MWh/anno'.replace(',', '.'))
        e = lambda x: ('€{:,}'.format(int(x))).replace(',', '.')
        print(f'   Ricavi lordi impianto: {e(r["ricavi_impianto_eur_anno"][0])}–{e(r["ricavi_impianto_eur_anno"][1])}/anno '
              f'({r["eur_mwh_ipotesi"][0]}–{r["eur_mwh_ipotesi"][1]} €/MWh) — del developer, al lordo di capex/O&M.')
    print('\n⑤ VALORE INDICATIVO DELLA TERRA (non perizia)')
    print(descrivi_valore(d['valore_eur']))
    print('\n⑥ AZIENDE DA CONTATTARE  (tecnologia: %s)' % t['consigliata'])
    for i, s in enumerate(d['aziende'], 1):
        head = s['known'][0] if s['known'] else s['proponente']
        extra = f' — {s["known"][1]}' if s['known'] else ''
        dist = f'{s["dist_km"]} km' if s.get('dist_km') else s['why_geo']
        print(f'   {i}. {head}{extra}')
        print(f'      {dist} · {s["why_tech"]} · {s["mw"]:.0f} MW · {s["link"]}')
    print('\n'+L)
    print('  Screening automatico su dati pubblici ufficiali. NON sostituisce VINCA/perizia/visure.')
    print('  land-scout · fattibilità (vincoli) + tecnologia (recommend) + aziende (match)')
    print(L)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--parcels', required=True)
    # ⚠ niente default='BN': chi ometteva --prov otteniva in silenzio i layer della Campania
    ap.add_argument('--comune', required=True); ap.add_argument('--prov', required=True)
    ap.add_argument('--tech'); ap.add_argument('--no-geo', action='store_true'); ap.add_argument('--out')
    A = ap.parse_args()
    parcels = json.load(open(A.parcels, encoding='utf-8'))
    d = build_dossier(parcels, A.comune, A.prov, tech=A.tech, geo=not A.no_geo)
    print_dossier(d)
    if A.out:
        json.dump(d, open(A.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('salvato:', A.out)

if __name__ == '__main__':
    main()
