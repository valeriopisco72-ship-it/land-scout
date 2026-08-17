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

    # contesto nodo dal registro rete: se il nodo non e' noto -> {} (nessuna affermazione inventata)
    if node is None:
        node = contesto_nodo(comune, prov)

    # 1. fattibilita' (prov -> determina la copertura: habitat/SITAP sono regionali)
    vinc = VC.feasibility(parcels, prov=prov)
    cov = COPERTURA(prov)

    # 2. tecnologia per particella
    recos = {}
    for i in ids:
        p = parcels[i]; v = vinc[i]
        # zps_pct e' ora la frazione REALE di superficie in ZPS (overlay sul poligono
        # catastale); col solo centroide resta 0/100 e il dossier lo dichiara.
        zpct = v.get('zps_pct')
        if zpct is None:
            zpct = 100.0 if v.get('zps') else 0.0
        ep = {'ha': p['ha'], 'slope': p.get('slope'),
              'zps_pct': zpct, 'zps_border_m': -1 if zpct > 0 else 9e9,
              'habitat_ban': v.get('habitat_ban', False), 'in_sic': v.get('sic', False),
              'd_se_m': p.get('d_se_m', 9e9), 'd_150kv_m': p.get('d_150kv_m', 9e9)}
        recos[i] = recommend(ep, node)

    verdetti = Counter(vinc[i]['verdetto'] for i in ids)
    ha_ban = sum(parcels[i]['ha'] for i in ids if vinc[i].get('habitat_ban'))
    uc = sum(1 for i in ids if vinc[i].get('usi_civici') is True)
    sitap_ok = all(vinc[i].get('sitap_ok', True) for i in ids)
    tech_dist = Counter(recos[i]['top'] for i in ids if recos[i]['top'])
    block_tech = tech or (tech_dist.most_common(1)[0][0] if tech_dist else 'agriPV')

    # 3. resa energetica (PVGIS) — solo per tecnologie solari
    resa = resa_terreno(tot_ha, lat0, lon0, block_tech if block_tech in ('agriPV', 'PV') else 'agriPV')

    # 4. valore — funzione di superficie + vincoli + tecnologia + copertura.
    #    (prima era 3 costanti di Morcone x ettari: stesso € ovunque in Italia)
    vinc_blocco = {'zps': any(vinc[i].get('zps') for i in ids),
                   'sic': any(vinc[i].get('sic') for i in ids),
                   'habitat_ban': any(vinc[i].get('habitat_ban') for i in ids),
                   'usi_civici': any(vinc[i].get('usi_civici') is True for i in ids)}
    val = calcola_valore(tot_ha, vinc_blocco, tech=block_tech, copertura=cov, prov=prov)

    # 5. aziende (sulla tecnologia dominante)
    aziende = match_companies(comune, prov, [lat0, lon0], block_tech, geo=geo)

    return {'comune': comune, 'prov': prov, 'n': len(ids), 'tot_ha': round(tot_ha, 2),
            'centroide': [round(lat0, 5), round(lon0, 5)],
            'avvisi_luogo': avvisi_luogo,
            'fattibilita': {'verdetti': dict(verdetti), 'ha_habitat_vietato': round(ha_ban, 2),
                            'usi_civici_n': uc, 'sitap_ok': sitap_ok, 'copertura': cov},
            'tecnologia': {'consigliata': block_tech, 'distribuzione': dict(tech_dist)},
            'rete': nodo_info(comune, prov),
            'rete_distanza': distanza_rete([(parcels[i]['lat'], parcels[i]['lon']) for i in ids]),
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
    print(f'   Habitat divieto FV: {f["ha_habitat_vietato"]} ha  →  '
          + ('⛔ presente' if f['ha_habitat_vietato'] else '✅ non rilevato')
          + f'   [fonte: {cov.get("habitat_fonte")}]')
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
    t = d['tecnologia']
    print('\n② TECNOLOGIA CONSIGLIATA')
    print(f'   ➜ {t["consigliata"].upper()}   (distribuzione particelle: {t["distribuzione"]})')
    if t['consigliata'] == 'agriPV':
        in_zps = any('VINCA' in k for k in (d['fattibilita'].get('verdetti') or {}))
        if in_zps:
            print('   Motivo: terra agricola in ZPS → eolico escluso (DM 2007), FV a terra vietato su agricolo '
                  '(D.Lgs 190/2024) → agriPV avanzato sopraelevato, via VINCA.')
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
