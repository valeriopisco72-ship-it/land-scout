"""land-scout — motore di scoring e stima economica (v0.1, demo Campolattaro).

Regole codificate dal progetto Morcone/Campolattaro (vault 06-13/07/2026):
- ZPS: dentro = VINCA obbligatoria (blocker solare, warning forte BESS); buffer 500 m = warning solare, ok BESS
- PAI frane (cod_per_it): 3/4 = blocker; 2 = warning; 0 (AA)/1 = nota
- PAI idraulica P2/P3 = blocker, P1 = warning
- art.142-b lago 300 m / 142-c fiume 150 m = warning (autorizzazione paesaggistica)
- pendenza: BESS ok<8, warn 8-12, block >12; agriPV ok<10, warn 10-15 (tracker), block >15
- rete: bonus vicinanza SE/linea 150kV
- taglia: benchmark BESS di mercato 2-2,5 ha minimi (da soli o aggregando)
"""
import math

MLAT = 111132.0

def m_per_deg(lat):
    return 111132.0, 111320.0 * math.cos(math.radians(lat))


def score_parcel(p, tech='BESS'):
    """p: dict con ha, slope, zps_pct, zps_border_m (>0 fuori), pai_fr (max cod), pai_idr (0/1/2/3),
    d_se_m, d_150kv_m, fascia_lago (bool), fascia_fiume (bool), note_occupazione (str|None).
    Ritorna (score 0-100, classe, flags[])"""
    s = 88.0  # base: un terreno "normale" senza vincoli ne' bonus vale ~8.8/10, il 10 va guadagnato
    flags = []
    blocker = False

    # --- ZPS / Natura 2000 ---
    if p['zps_pct'] > 10:
        if tech == 'BESS':
            s -= 30; flags.append('DENTRO ZPS: VINCA obbligatoria (warning forte)')
        elif 'habitat_ban' in p and not p['habitat_ban']:
            # Fase 7: ZPS ma verificato NON su habitat 6220/6210 → VINCA avifauna gestibile,
            # non preclusione (cfr. studio Morcone: habitat sgombro + precedente VINCA RWE).
            s -= 28; flags.append('DENTRO ZPS ma NON su habitat vietato (6220/6210): iter VINCA avifauna — impegnativo ma non preclusivo')
        else:
            blocker = True; flags.append('DENTRO ZPS: non idoneo solare/agriPV senza VINCA robusta')
    elif 0 < p['zps_border_m'] <= 500:
        if tech == 'BESS':
            s -= 3; flags.append(f'buffer ZPS ({p["zps_border_m"]:.0f} m): solo screening VINCA, non blocca BESS')
        else:
            s -= 20; flags.append(f'buffer ZPS ({p["zps_border_m"]:.0f} m): warning solare')

    # --- vincoli ufficiali (Fase 7, landscout/vincoli.py) ---
    # habitat 6220/6210: il divieto NON riguarda solo il fotovoltaico e NON
    # risparmia il BESS. Il "sentito" del Parco del Matese sulla CUP 31 di
    # Morcone (prot. 558/2026, rigetto per DIVIETO ASSOLUTO) elenca cosa e'
    # vietato in questi habitat: *modifica della destinazione d'uso*,
    # forestazione, coltivazione, spietramento, irrigazione, bruciatura. Una
    # piattaforma di accumulo e' una modifica della destinazione d'uso come e
    # piu' di un impianto FV: fino al 12/08/2026 questo motore la lasciava
    # passare.
    if p.get('habitat_ban'):
        blocker = True
        flags.append(
            f'HABITAT {p.get("habitat", "6220/6210")}: DIVIETO di modifica della '
            f'destinazione d uso (misure di conservazione, DGR Campania 617/2024) — '
            f'vale per FV a terra E per il BESS; precedente: rigetto CUP 31 Morcone')
    # SIC/ZSC: la VINCA copre anche la Direttiva Habitat (oltre gli uccelli della ZPS)
    if p.get('in_sic'):
        s -= 5; flags.append('dentro SIC/ZSC: VINCA estesa alla Direttiva Habitat')
    # usi civici: rischio TITOLO (demanio civico) — puo' bloccare la vendita fino a sdemanializzazione
    if p.get('usi_civici'):
        s -= 8; flags.append('USI CIVICI: verificare titolo prima di vendere/concedere (demanio civico)')
    if p.get('paesaggio_incompleto'):
        flags.append('⚠ SITAP non raggiunto: usi civici / paesaggio DA VERIFICARE (non assumere "pulito")')

    # --- PAI frane e idraulica ---
    # `-1`/`0` significano "controllato, nessun poligono qui"; `None` o
    # `pai_incompleto` significano "NON controllato", e non e' la stessa cosa.
    # La distinzione e' nata in audit (08/08/2026): con il layer IdroGEO muto o
    # mal proiettato ogni particella usciva senza vincolo PAI, cioe' con un
    # blocker spento in silenzio. Un dato che non arriva deve pesare come un
    # dubbio dichiarato, mai come una buona notizia.
    fr = p.get('pai_fr', -1)
    idr = p.get('pai_idr', 0)
    if p.get('pai_incompleto') or fr is None or idr is None:
        flags.append('⚠ PAI NON verificato: frane/idraulica da controllare su IdroGEO '
                     '(non assumere "nessun vincolo")')
    else:
        if fr >= 3:
            blocker = True; flags.append(f'PAI frana P{fr}: BLOCKER')
        elif fr == 2:
            s -= 15; flags.append('PAI frana P2: studio geologico necessario')
        elif fr in (0, 1):
            s -= 3; flags.append('PAI frana AA/P1: nota informativa (non vincolo operativo)')

        if idr >= 2:
            blocker = True; flags.append(f'PAI idraulica P{idr}: BLOCKER')
        elif idr == 1:
            s -= 10; flags.append('PAI idraulica P1: warning')

    # --- paesaggio art.142 / 136 (fascia_lago/fiume: da SITAP ufficiale se disponibile, altrimenti OSM) ---
    if p.get('fascia_lago'):
        s -= 10; flags.append('fascia 300 m lago (art.142-b): autorizzazione paesaggistica')
    if p.get('fascia_fiume'):
        s -= 10; flags.append('fascia 150 m fiume (art.142-c): autorizzazione paesaggistica')
    if p.get('bosco_142g'):
        s -= 10; flags.append('bosco vincolato (art.142-g): vincolo forestale / autorizzazione disboscamento')
    if p.get('tratturo'):
        s -= 8; flags.append('tratturo / archeologico lineare (art.142-m): fascia demaniale + autorizzazione')
    if p.get('art136'):
        s -= 8; flags.append('area dichiarata di notevole interesse pubblico (art.136): autorizzazione paesaggistica')

    # --- v0.2 (19/07/2026): indicatori aggiunti dopo audit della checklist operativa -------
    # Ogni check scatta SOLO se la chiave e' presente: una chiave assente non e' "pulito",
    # e' "non controllato" e lo dichiara vincoli_non_verificati(). Cosi' il vecchio scoring
    # (e i test) restano identici finche' non si popolano i nuovi campi.

    # aree naturali protette (EUAP): parco nazionale/regionale o riserva = fuori discussione
    if p.get('area_protetta'):
        blocker = True
        flags.append(f'AREA PROTETTA ({p["area_protetta"]}): parco/riserva — impianto non autorizzabile')

    # aree idonee / non idonee: D.Lgs 199/2021 art.20 + DM 21/06/2024 + legge regionale.
    # (TAR Campania: solo Stato e Regioni le definiscono, i divieti dei PUC comunali non contano.)
    if p.get('area_non_idonea'):
        blocker = True
        flags.append('AREA NON IDONEA per norma statale/regionale: iter precluso')
    elif p.get('area_idonea'):
        s += 10
        flags.append('AREA IDONEA: iter accelerato (D.Lgs 199/2021 art.20)')

    # colture di pregio storiche: in Campania vigneti/oliveti del Registro nazionale paesaggi
    # rurali storici e vigneti eroici sono NON idonei all'agrivoltaico (circolare 481104/2026).
    if p.get('coltura_storica') and tech != 'BESS':
        blocker = True
        flags.append('vigneto/oliveto storico (Registro paesaggi rurali / vigneti eroici): NON idoneo ad agrivoltaico')

    # buffer 500 m dai beni tutelati (DL Semplificazioni). L'agriPV avanzato gode di deroghe:
    # pesa molto ma non blocca — si negozia con la Soprintendenza.
    db = p.get('d_bene_tutelato_m')
    if db is not None and db < 500:
        s -= 8 if tech == 'BESS' else 22
        flags.append(f'bene tutelato a {db:.0f} m (<500 m): fascia critica per FV — agriPV in deroga, da concordare con Soprintendenza')

    # distanza dal LIMITE del bosco: diverso dall'essere dentro il bosco vincolato (142-g)
    dbo = p.get('d_bosco_m')
    if dbo is not None and dbo < 100:
        s -= 8
        flags.append(f'limite bosco a {dbo:.0f} m (<100 m): fascia di rispetto forestale da verificare')

    # DOP/IGP/DOCG: per l'agriPV non e' divieto, ma la commissione agricola regionale e' severa
    if p.get('dop_igp') and tech != 'BESS':
        s -= 10
        flags.append(f'area {p["dop_igp"]}: agriPV ammesso ma serve relazione agronomica robusta (commissione regionale severa)')

    # destinazione urbanistica: il CDU deve dire Zona E (agricola)
    zu = p.get('zona_urbanistica')
    if zu is not None and not str(zu).strip().upper().startswith('E'):
        s -= 15
        flags.append(f'destinazione urbanistica "{zu}": non agricola — serve Zona E da CDU')

    # vincolo idrogeologico R.D. 3267/1923: autorizzazione forestale, NON e' il PAI
    if p.get('vincolo_idrogeologico'):
        s -= 6
        flags.append('vincolo idrogeologico (R.D. 3267/1923): autorizzazione regionale/forestale')

    # aree percorse dal fuoco (L. 353/2000): divieti pluriennali di cambio destinazione
    if p.get('percorsa_fuoco'):
        blocker = True
        flags.append('area percorsa dal fuoco (L. 353/2000): divieti pluriennali — verificare catasto incendi comunale')

    # PLV: in Campania va certificato il mantenimento di >=80% della Produzione Lorda Vendibile
    plv = p.get('plv_residua')
    if plv is not None and tech != 'BESS' and plv < 0.80:
        s -= 18
        flags.append(f'PLV residua {plv*100:.0f}% < 80% (circolare Campania 481104/2026): progetto agronomico da rivedere')

    # --- pendenza ---
    sl = p.get('slope')
    if sl is not None:
        lim = (8, 12) if tech == 'BESS' else (10, 15)
        if sl > lim[1]:
            blocker = True; flags.append(f'pendenza {sl:.1f}%: oltre limite {tech}')
        elif sl > lim[0]:
            s -= 12; flags.append(f'pendenza {sl:.1f}%: al limite ({tech})')
        elif sl < 5:
            s += 5 - sl  # bonus continuo: piu' piatto = piu' punti
    else:
        flags.append('pendenza: n.d.')

    # --- esposizione (v0.2): a parita' di pendenza il versante conta ---
    # Su terreno quasi piatto l'esposizione e' irrilevante; da ~5% in su cambia resa e layout.
    asp = p.get('aspect')          # gradi: 0=N, 90=E, 180=S, 270=O
    if asp is not None and sl is not None and sl >= 5:
        sud = math.cos(math.radians(asp - 180))     # +1 = pieno Sud, -1 = pieno Nord
        if sud > 0.5:
            s += 4; flags.append(f'esposizione Sud ({asp:.0f}°): favorevole a parita\' di pendenza')
        elif sud < -0.3:
            s -= 6; flags.append(f'esposizione Nord ({asp:.0f}°): resa inferiore e layout penalizzato')

    # --- rete (bonus continui: la distanza pesa in modo graduale) ---
    dse = p.get('d_se_m', 9e9)
    if dse <= 3000:
        s += 12 * (1 - dse / 3000)
    else:
        s -= 12; flags.append(f'SE a {dse/1000:.1f} km: connessione da approfondire')
    dkv = p.get('d_150kv_m', 9e9)
    if dkv <= 1000:
        s += 3 * (1 - dkv / 1000)

    # --- taglia (continuo tra 1 e 2,5 ha) ---
    if p['ha'] < 1.0:
        s -= 10; flags.append(f'{p["ha"]:.2f} ha: sotto soglia da sola, serve aggregazione')
    elif p['ha'] >= 2.5:
        s += 8
    else:
        s += 8 * (p['ha'] - 1.0) / 1.5

    if p.get('note_occupazione'):
        flags.append('occupazione/uso reale: ' + p['note_occupazione'])

    s = max(0.0, min(100.0, s))
    if blocker:
        # un terreno bloccato non "vale zero": voto tappato a 2,5/10, resta il valore agricolo
        return round(min(s, 25.0), 1), 'D', flags
    classe = 'A' if s >= 80 else ('B' if s >= 60 else 'C')
    return round(s, 1), classe, flags


def voto_10(score, classe):
    """Voto 0-10 comunicativo (scala scolastica). Blocker (D) = max 2,5."""
    return round(score / 10.0, 1)


# ---------------- v0.2: copertura dei controlli e costo di connessione ----------------
# Indicatori introdotti dopo l'audit della checklist (19/07/2026). Un campo assente NON
# significa "pulito": significa "non controllato", e va detto a chi legge il dossier.
CHECK_V2 = ('area_protetta', 'area_idonea', 'area_non_idonea', 'coltura_storica',
            'd_bene_tutelato_m', 'd_bosco_m', 'dop_igp', 'zona_urbanistica',
            'vincolo_idrogeologico', 'percorsa_fuoco', 'plv_residua', 'aspect')

ETICHETTE_V2 = {
    'area_protetta':        'parchi/riserve (EUAP)',
    'area_idonea':          'aree idonee (D.Lgs 199/2021)',
    'area_non_idonea':      'aree NON idonee (norma statale/regionale)',
    'coltura_storica':      'vigneti/oliveti storici (Registro paesaggi rurali)',
    'd_bene_tutelato_m':    'distanza beni tutelati (buffer 500 m)',
    'd_bosco_m':            'distanza dal limite del bosco (100 m)',
    'dop_igp':              'aree DOP/IGP/DOCG',
    'zona_urbanistica':     'destinazione urbanistica / CDU (Zona E)',
    'vincolo_idrogeologico':'vincolo idrogeologico R.D. 3267/1923',
    'percorsa_fuoco':       'aree percorse dal fuoco (L. 353/2000)',
    'plv_residua':          'PLV residua >=80% (circolare Campania 481104/2026)',
    'aspect':               'esposizione del versante',
}


def vincoli_non_verificati(p):
    """Elenco leggibile di cosa NON e' stato controllato su questa particella.

    Serve a non spacciare "non controllato" per "pulito": il dossier deve mostrare i buchi.
    """
    return [ETICHETTE_V2[k] for k in CHECK_V2 if p.get(k) is None]


def costo_connessione_eur(d_se_m):
    """Costo indicativo del cavidotto interrato fino al punto di connessione.

    100-150 k€/km (scavo + posa, MT/AT). E' il vero discrimine economico: oltre ~5 km
    il costo di connessione si mangia il margine, per quanto il terreno sia buono.
    """
    if d_se_m is None or d_se_m >= 9e8:
        return None
    km = d_se_m / 1000.0
    lo, hi = 100_000, 150_000
    return {'km': round(km, 2),
            'eur': (round(km * lo), round(km * hi)),
            'oltre_soglia_economica': km > 5.0}


# ---------------- stima economica ----------------
# Ancoraggi (fonte: progetto Morcone/Campolattaro, luglio 2026):
# - comparabile reale RWE-Pontelandolfo: 60.000 EUR / 0,903 ha = 66.445 EUR/ha (concessione ~30 anni)
# - le soglie qui sotto sono VALORI DI ESEMPIO: vanno ricalibrati sui
#   comparabili della propria zona prima di qualunque uso reale.
# - il pavimento agricolo va letto dai VAM della PROPRIA provincia
BASE_EUR_HA = {
# ATTENZIONE: valori di ESEMPIO, non raccomandazioni di mercato.
# Vanno sostituiti con i comparabili osservati nella propria zona.
    'BESS':   {'floor': 40_000, 'target': 60_000, 'apertura': 80_000},
    'agriPV': {'floor': 35_000, 'target': 50_000, 'apertura': 70_000},
}
CANONE_ANNUO_EUR_HA = {'BESS': (2_500, 4_500), 'agriPV': (2_000, 3_500)}


def price_parcel(p, score, classe, tech='BESS'):
    """Stima INDICATIVA (non perizia). Ritorna dict con range vendita e canone."""
    if classe == 'D':
        return {'applicabile': False,
                'motivo': 'vincoli bloccanti: valore = solo agricolo (rif. VAM ~15-30k EUR/ha)'}
    base = BASE_EUR_HA[tech]
    # moltiplicatore qualita': classe A=1.0, B=0.85, C=0.65
    mq = {'A': 1.0, 'B': 0.85, 'C': 0.65}[classe]
    # rete: oltre 2 km la negoziabilita' scende
    mr = 1.0 if p.get('d_se_m', 9e9) < 1000 else (0.92 if p['d_se_m'] < 2000 else 0.85)
    m = mq * mr
    out = {'applicabile': True,
           'eur_ha': {k: round(v * m / 500) * 500 for k, v in base.items()},
           'canone_annuo_eur_ha': CANONE_ANNUO_EUR_HA[tech],
           'moltiplicatore': round(m, 2)}
    out['totale_eur'] = {k: round(v * p['ha'] / 500) * 500 for k, v in out['eur_ha'].items()}
    out['canone_annuo_tot'] = tuple(round(c * p['ha'] / 100) * 100 for c in CANONE_ANNUO_EUR_HA[tech])
    return out


def capacity_note(ha_utile, tech='BESS'):
    if tech == 'BESS':
        ok = ha_utile >= 2.0
        return (f'{ha_utile:.2f} ha utili: '
                + ('compatibile con footprint BESS utility-scale (benchmark di mercato: 2-2,5 ha minimi)'
                   if ok else 'sotto il benchmark di mercato (2-2,5 ha): necessaria aggregazione'))
    mw = (0.6 * ha_utile, 0.8 * ha_utile)
    return f'{ha_utile:.2f} ha utili = ~{mw[0]:.1f}-{mw[1]:.1f} MWp agrivoltaico avanzato (0,6-0,8 MWp/ha)'
