"""land-scout bess — screening per ACCUMULI, non per campi fotovoltaici.

Perche' un modulo separato e non un flag `tech='BESS'` in piu'.
--------------------------------------------------------------
`engine.score_parcel` gia' distingue il BESS sui VINCOLI (ZPS, pendenza,
buffer beni tutelati). Ma tutto il resto della pipeline — `installabile`,
`blocco`, `capacita` — e' tarato su un campo fotovoltaico, e per un accumulo
sbaglia in modo sistematico, sempre nella stessa direzione:

1. **La geometria.** `installabile.py` erode il blocco di 12,5 m perche' e'
   meta' dell'interfila agriPV: descrive un campo che si estende. Un BESS non
   si estende, si CONCENTRA: vuole UNA piattaforma compatta, spianata e
   recintata. Una striscia interna al blocco, che per il fotovoltaico e'
   perfettamente utile (le file la attraversano), per un accumulo non vale
   nulla se non ci sta dentro un rettangolo. Quindi non si misura la
   superficie erosa: si misura il **piu' grande quadrato inscritto**.

2. **La taglia.** Il tool ragiona in ha -> MWp con 0,6-0,8 MWp/ha. Per il BESS
   la catena e' ha -> MWh -> MW, e la densita' e' un ordine di grandezza
   diversa. Il registro VIA nazionale accumuli (361 progetti, `via_accumulo`)
   da' **mediana 38 MW, quartili 17 / 38 / 58 MW, minimo 4,4 MW**: il mercato
   NON costruisce accumuli da 9 MW. Sottodimensionare la stima porta a
   concludere "resta in MT" quando invece si finisce in alta tensione.

3. **La rete, che si ROVESCIA.** Per il fotovoltaico una sezione AT/MT in
   inversione di flusso e' una condanna: significa che quel nodo rimanda gia'
   energia verso l'alta tensione e non ne assorbe altra. Per l'accumulo e'
   **il contrario**: l'inversione di flusso e' esattamente il problema che lo
   storage risolve, e in prima approssimazione e' un segnale di DOMANDA. La
   stessa riga di dati va letta con il segno opposto.

4. **L'intensita' di capitale.** E' la ragione economica per cui un BESS
   sopravvive dove il fotovoltaico muore. Su 15 MWp di agrivoltaico il capex
   e' ~10 M EUR e una stazione utente da 1,85 M pesa il 18%: insostenibile.
   Su 38 MW / 4h di accumulo il capex e' ~30 M EUR e la stessa stazione pesa
   il 6%: normale. **A parita' di terreno e di rete, l'accumulo assorbe un
   costo di connessione che il solare non regge.**

Affidabilita' dei numeri (leggere prima di usarli in trattativa)
---------------------------------------------------------------
SOLIDI     : distribuzione taglie da registro VIA (dato pubblico, 361 record);
             soglia 10 MW = connessione AT a Terna; elenco sezioni in
             inversione e-Distribuzione; geometria delle particelle (WFS AdE).
DICHIARATI : taglia sito tipica di mercato 2,5-5 ha.
STIMATI    : MWh/ha, capex EUR/MWh, costo stazione utente, canone EUR/MW.
             Sono PARAMETRI, non misure: stanno tutti in testa al modulo,
             vanno sostituiti col primo dato reale che arriva da un developer.

Uso:
    from landscout import bess
    r = bess.analizza(particelle, slope_pct=9.0, inversione=True, d_se_m=5150)
    print(bess.print_analisi(r))
"""
import math

import numpy as np
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# COSTANTI — ogni voce dichiara la sua fonte
# ---------------------------------------------------------------------------

# [SOLIDO] Registro VIA nazionale accumuli, export 2026 (361 progetti, 319 con
# potenza nel titolo). Serve a non sottodimensionare: sotto ~15 MW un accumulo
# standalone e' fuori mercato per chi sviluppa.
VIA_TAGLIE_MW = {'min': 4.4, 'q1': 16.9, 'mediana': 38.1, 'q3': 57.5, 'max': 490.0}

# [DICHIARATO] Benchmark di mercato: siti da 2,5 a 5 ha,
# 2,5 ha e' la soglia minima utile. Incrociato con la mediana VIA da la densita'
# implicita — vedi densita_implicita().
TAGLIA_SITO_TIPICA_HA = (2.5, 5.0)

# [STIMATO] Densita' di superficie. Un accumulo containerizzato occupa poco, ma
# fra le file servono corridoi di manovra e le distanze di sicurezza antincendio
# fra i cabinati: e' quello, non il container, a fissare la densita'.
MWH_PER_HA = {'prudente': 25.0, 'media': 35.0, 'spinta': 45.0}
DURATA_H = 4.0            # ore di scarica nominali (MACSE punta su 4-8 h)

# [STIMATO] Capex chiavi in mano di un accumulo 4 h, EUR/MWh installato.
CAPEX_EUR_MWH = (150_000, 250_000)

# [STIMATO, gia' nel vault come "da verificare"] Stazione utente 150 kV.
STAZIONE_UTENTE_EUR = (1_200_000, 2_500_000)

# [SOLIDO] TICA / regole di connessione: da 10.000 kW in su la domanda va a
# Terna in alta tensione. Sotto, si resta in MT sulla cabina primaria.
SOGLIA_AT_MW = 10.0
STMG_EUR = 2_500

# [STIMATO] Canone del terreno. Per il BESS il mercato ragiona per MW occupato,
# non per ettaro: e' la ragione per cui un fondo piccolo puo' valere molto.
CANONE_EUR_MW_ANNO = (3_000, 8_000)

# [OSSERVATO — rassegna stampa specializzata letta l'08/08/2026, esito ufficiale
#  Terna DA VERIFICARE sul sito] Prima asta MACSE, il mercato a termine dello
#  stoccaggio: aggiudicati 10 GWh a un prezzo medio ponderato di 12.959 EUR per
#  MWh di capacita' all'anno (zona Sud/Calabria 12.146, Sicilia 15.846), contro un
#  premio di riserva di 37.000; entrata in esercizio prevista 2028.
#  Perche' sta qui: e' l'unico ricavo OSSERVATO di un accumulo italiano. Da questo
#  si ricava quanto incassa chi costruisce, e quindi quanto puo' pagare la terra —
#  il canone smette di essere una banda presa dal mercato e diventa una quota di
#  un ricavo noto. Non e' l'unico ricavo dell'impianto (restano MGP/MSD e capacity
#  market): usarlo come PAVIMENTO, mai come totale.
MACSE_EUR_MWH_ANNO = {'media_ponderata': 12_959, 'sud': 12_146, 'sicilia': 15_846,
                      'riserva': 37_000}

# --- geometria della piattaforma -------------------------------------------
FRANCO_BESS_M = 8.0     # recinzione + strada perimetrale + arretramento dai confini
LATO_MIN_M = 80.0       # sotto, non ci sta un layout con corridoi di manovra
RIS_M = 2.0

# --- pendenza ---------------------------------------------------------------
# Allineate a engine.score_parcel (BESS: ok <8, attenzione 8-12, blocco >12).
# Sotto il 5% la platea e' praticamente gratis, ed e' l'ottimo, non il limite:
# tenerlo separato evita di far sembrare "bocciato" un sito solo buono.
PEND_IDEALE, PEND_OK, PEND_LIMITE = 5.0, 8.0, 12.0
SBANCAMENTO_EUR_MC = 12.0    # [STIMATO] scavo + rinterro + compattazione

# --- distanze di sicurezza --------------------------------------------------
# [PRUDENZIALE] non esiste una distanza di legge unica per gli accumuli: la
# regola tecnica antincendio si applica caso per caso col comando VVF. Questi
# sono valori di buon senso progettuale, servono a segnalare rischio, non a
# dichiarare conformita'.
D_BOSCO_MIN_M = 50.0
D_ABITATO_MIN_M = 150.0


# ===========================================================================
# 1. GEOMETRIA — il piu' grande quadrato inscritto, non gli ettari erosi
# ===========================================================================
def _proj(polys):
    lats = [q[0] for p in polys for q in p]
    la0 = (min(lats) + max(lats)) / 2
    k = 111320 * math.cos(math.radians(la0))
    return [[(q[1] * k, q[0] * 110540) for q in p] for p in polys]


def _maschera(mp, ris=RIS_M, margine=40.0):
    xs = [x for p in mp for x, y in p]
    ys = [y for p in mp for x, y in p]
    x0, y0 = min(xs) - margine, min(ys) - margine
    W = int((max(xs) - x0 + margine) / ris) + 1
    H = int((max(ys) - y0 + margine) / ris) + 1
    img = Image.new('1', (W, H), 0)
    dr = ImageDraw.Draw(img)
    for p in mp:
        dr.polygon([((x - x0) / ris, H - 1 - (y - y0) / ris) for x, y in p], fill=1)
    return np.array(img, dtype=bool), (x0, y0, W, H)


def _erodi8(m):
    """Un passo di erosione 8-connessa.

    8-connessa e non 4-connessa di proposito: iterandola, il numero di passi che
    un pixel sopravvive e' la sua distanza di Chebyshev dal bordo, e quella
    distanza e' **meta' del lato del quadrato inscritto** centrato li'. Con
    l'erosione 4-connessa (quella di installabile.py) si otterrebbe un rombo,
    che non e' la forma di una piattaforma.
    """
    out = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            s = np.zeros_like(m)
            ys = slice(max(0, dy), m.shape[0] + min(0, dy))
            yd = slice(max(0, -dy), m.shape[0] + min(0, -dy))
            xs = slice(max(0, dx), m.shape[1] + min(0, dx))
            xd = slice(max(0, -dx), m.shape[1] + min(0, -dx))
            s[yd, xd] = m[ys, xs]
            out &= s
    return out


def _distanza_bordo(mask, max_passi=400):
    """Distanza di Chebyshev dal bordo, in pixel, per erosioni successive."""
    d = np.zeros(mask.shape, dtype=np.int32)
    m = mask
    for i in range(max_passi):
        m = _erodi8(m)
        if not m.any():
            break
        d[m] = i + 1
    return d


def ricavo_macse(dim, zona='sud'):
    """Ricavo annuo dell'accumulo al prezzo MACSE, e che quota ne chiede la terra.

    `dim` e' l'uscita di `dimensiona()`. Restituisce anche il canone come quota di
    quel ricavo: e' il numero che rende difendibile una richiesta in trattativa —
    "ti chiedo il 2% di quello che incassi" si discute, "ti chiedo 8.000 EUR/MW"
    no, perche' nessuna delle due parti sa da dove viene quella cifra.
    """
    p = MACSE_EUR_MWH_ANNO.get(zona, MACSE_EUR_MWH_ANNO['media_ponderata'])
    mwh = dim.get('mwh') or 0
    mw = dim.get('mw') or 0
    ricavo = p * mwh
    can_lo, can_hi = CANONE_EUR_MW_ANNO
    return {'zona': zona, 'eur_mwh_anno': p, 'mwh': mwh,
            'ricavo_eur_anno': round(ricavo),
            'canone_eur_anno': (round(can_lo * mw), round(can_hi * mw)),
            'quota_ricavo': (round(can_lo * mw / ricavo, 4) if ricavo else None,
                             round(can_hi * mw / ricavo, 4) if ricavo else None),
            'nota': ('prezzo MACSE = solo il contratto di capacita di stoccaggio: '
                     'l impianto incassa anche sui mercati. Pavimento, non totale.')}


def piattaforma(particelle, franco_m=FRANCO_BESS_M, ris=RIS_M, strade=None):
    """Quanto vale questo insieme di particelle COME PIATTAFORMA per accumuli.

    Non risponde "quanti ettari sopravvivono all'erosione" (domanda giusta per
    un campo di moduli) ma "che lato ha il piu' grande quadrato che ci sta
    dentro" — perche' un accumulo o ci mette una platea rettangolare o non ci
    mette niente.
    """
    polys = [p['poly'] for p in particelle]
    mp = _proj(polys)
    mask, geo = _maschera(mp, ris)
    if strade:
        from . import strade as ST
        road, _ = ST.maschera(particelle, strade, ris=ris, margine=40.0)
        if road.shape == mask.shape:
            mask = mask & ~road

    px_ha = (ris * ris) / 10000.0
    ha_unione = mask.sum() * px_ha

    passi = max(1, int(round(franco_m / ris)))
    utile = mask
    for _ in range(passi):
        utile = _erodi8(utile)
    ha_utile = utile.sum() * px_ha

    d = _distanza_bordo(mask)
    d_max_px = int(d.max()) if d.size else 0
    lato_m = 2.0 * d_max_px * ris          # quadrato inscritto massimo
    ha_quadrato = (lato_m ** 2) / 10000.0

    # compattezza: quanto l'insieme somiglia a un blocco pieno invece che a un
    # nastro. 1.0 = cerchio perfetto; sotto ~0.25 e' una forma allungata.
    ha_bbox = 0.0
    if mask.any():
        ys, xs = np.nonzero(mask)
        ha_bbox = ((xs.max() - xs.min() + 1) * ris) * ((ys.max() - ys.min() + 1) * ris) / 10000.0
    riempimento = (ha_unione / ha_bbox) if ha_bbox else 0.0

    # gli ettari catastali restano la misura ufficiale: la geometria fornisce
    # solo il fattore di forma (stessa scelta di installabile.py)
    ha_netti = round(sum(p.get('netti') or p.get('ha') or 0 for p in particelle), 2)
    resa = (ha_utile / ha_unione) if ha_unione else 0.0

    ok = lato_m >= LATO_MIN_M
    return {
        'ha_netti_dichiarati': ha_netti,
        'ha_unione_geometrica': round(ha_unione, 2),
        'ha_utile': round(ha_netti * resa, 2),
        'resa_forma': round(resa, 3),
        'lato_quadrato_m': round(lato_m, 1),
        'ha_quadrato_inscritto': round(ha_quadrato, 2),
        'riempimento_bbox': round(riempimento, 3),
        'franco_m': franco_m,
        'piattaforma_ok': ok,
        'nota': ('Il quadrato inscritto e\' la misura che conta: un accumulo vuole UNA '
                 'platea compatta. Ettari sparsi su piu\' lingue di terra non fanno '
                 'una piattaforma, per quanto sommino.'),
    }


# ===========================================================================
# 2. TAGLIA — da ettari a MW/MWh, con il controllo incrociato sulla densita'
# ===========================================================================
def densita_implicita(taglie_mw=None, ha=TAGLIA_SITO_TIPICA_HA, durata_h=DURATA_H):
    """Triangolazione: se un developer dice "mi servono 2,5-5 ha" e il mercato
    costruisce accumuli con mediana 38 MW, allora la densita' implicita e'
    38 MW / 2,5-5 ha. Serve a non fidarsi del solo MWH_PER_HA assunto a tavolino.
    """
    t = taglie_mw or VIA_TAGLIE_MW
    mw_ha = (t['mediana'] / ha[1], t['mediana'] / ha[0])
    return {
        'mw_per_ha': (round(mw_ha[0], 1), round(mw_ha[1], 1)),
        'mwh_per_ha': (round(mw_ha[0] * durata_h, 0), round(mw_ha[1] * durata_h, 0)),
        'coerente_con_assunto': mw_ha[0] * durata_h <= MWH_PER_HA['spinta']
                                and mw_ha[1] * durata_h >= MWH_PER_HA['prudente'],
        'fonte': 'mediana registro VIA / taglia sito dichiarata dal developer',
    }


def dimensiona(ha_utile, densita='media', durata_h=DURATA_H, ha_quadrato=None):
    """Da superficie utile a MWh, MW e capex.

    `ha_quadrato`: superficie del piu' grande quadrato inscritto, se nota. Serve
    perche' le due misure rispondono a due domande diverse e la verita' sta in
    mezzo: `ha_utile` presume che si possa usare tutta la superficie erosa (vero
    solo terrazzando in piu' platee), il quadrato inscritto presume UNA sola
    platea (vero solo per un layout monoblocco). Dichiarare la forbice e' piu'
    onesto che scegliere di nascosto uno dei due.
    """
    mwh_ha = MWH_PER_HA[densita] if isinstance(densita, str) else float(densita)
    mwh = ha_utile * mwh_ha
    mw = mwh / durata_h
    capex = (mwh * CAPEX_EUR_MWH[0], mwh * CAPEX_EUR_MWH[1])
    conservativo = None
    if ha_quadrato is not None:
        mwh_c = ha_quadrato * mwh_ha
        conservativo = {'ha': round(ha_quadrato, 2), 'mwh': round(mwh_c, 1),
                        'mw': round(mwh_c / durata_h, 1),
                        'sopra_soglia_at': (mwh_c / durata_h) >= SOGLIA_AT_MW,
                        'ipotesi': 'una sola platea, nessun terrazzamento'}
    t = VIA_TAGLIE_MW
    if mw < t['min']:
        posizione = 'sotto il minimo del registro VIA: taglia fuori mercato'
    elif mw < t['q1']:
        posizione = 'primo quartile: piccolo ma esistente'
    elif mw <= t['q3']:
        posizione = 'nella meta' + ' centrale del mercato'
    else:
        posizione = 'sopra il terzo quartile: progetto grande'
    # ⚠ Un accumulo sta su una PLATEA, non su un territorio. Se la superficie
    # erosa e' molte volte il quadrato inscritto, quell'insieme di particelle non
    # e' una piattaforma: e' terra sparsa, e il numero di MWh che esce di qui e'
    # una moltiplicazione senza significato fisico. Successo il 10/08/2026
    # interrogando 281 particelle di Morcone: 90 ha "utili", quadrato 3,84 ha,
    # e in uscita 788 MW — un numero che nessuno costruira' mai.
    avviso = None
    if ha_quadrato and ha_utile > 3 * ha_quadrato:
        avviso = (f'superficie utile ({round(ha_utile, 1)} ha) molto maggiore del quadrato '
                  f'inscritto ({round(ha_quadrato, 2)} ha): queste particelle NON sono una '
                  f'piattaforma, sono terra sparsa. Per un accumulo vale il quadrato — '
                  f'{conservativo["mw"] if conservativo else "?"} MW — non gli MWh qui sopra.')

    return {
        'ha_utile': round(ha_utile, 2),
        'densita_mwh_ha': mwh_ha,
        'durata_h': durata_h,
        'mwh': round(mwh, 1),
        'mw': round(mw, 1),
        'capex_eur': (round(capex[0]), round(capex[1])),
        'sopra_soglia_at': mw >= SOGLIA_AT_MW,
        'posizione_mercato': posizione,
        'conservativo': conservativo,
        'avviso_forma': avviso,
    }


def taglia_per_restare_in_mt(durata_h=DURATA_H, densita='media'):
    """Quanta superficie serve per stare DELIBERATAMENTE sotto i 10 MW.

    Non e' un dettaglio: sotto soglia si resta in media tensione (domanda a
    e-Distribuzione, niente stazione utente), sopra si va a Terna in AT. E'
    una scelta di progetto, e va fatta sapendo cosa si compra e cosa si perde.
    """
    mwh_ha = MWH_PER_HA[densita]
    mwh_max = (SOGLIA_AT_MW - 0.1) * durata_h
    return {'ha_max': round(mwh_max / mwh_ha, 2), 'mwh_max': round(mwh_max, 1),
            'mw_max': SOGLIA_AT_MW - 0.1}


# ===========================================================================
# 3. RETE — la stessa riga di dati, letta col segno opposto
# ===========================================================================
def rete(mw, inversione=None, d_se_m=None, coda_mw=None, criticita=None):
    """Lettura della rete dal punto di vista dell'accumulo.

    `inversione`: la sezione AT/MT di riferimento e' nell'elenco e-Distribuzione
    delle sezioni in inversione di flusso >=5% delle ore. Per il fotovoltaico e'
    un veto; qui e' un argomento a favore.
    """
    note, punti = [], 0
    at = mw >= SOGLIA_AT_MW
    if at:
        note.append(f'{mw:.1f} MW >= {SOGLIA_AT_MW:.0f} MW: connessione in ALTA TENSIONE, '
                    'domanda a Terna. NON passa dalla cabina primaria in MT, quindi la '
                    'saturazione MT non si applica.')
    else:
        note.append(f'{mw:.1f} MW < {SOGLIA_AT_MW:.0f} MW: resta in MEDIA TENSIONE, '
                    'domanda a e-Distribuzione sulla cabina primaria — ed e\' li\' che '
                    'la saturazione morde.')
    if inversione is True:
        if at:
            punti += 6
            note.append('sezione in inversione di flusso: per un ACCUMULO e\' domanda, '
                        'non ostacolo — lo storage assorbe l\'eccesso che causa '
                        'l\'inversione. Da confermare col gestore, non e\' automatico.')
        else:
            punti += 2
            note.append('sezione in inversione: favorevole in linea di principio, ma in MT '
                        'la valutazione resta del distributore caso per caso.')
    elif inversione is False:
        note.append('sezione non in inversione: nessun segnale specifico di domanda di storage.')

    if coda_mw:
        note.append(f'coda accumuli in provincia {coda_mw:,.0f} MW richiesti: e\' insieme '
                    'segnale di domanda e di AFFOLLAMENTO. Chi ha la terra e arriva prima '
                    'con la STMG ha il vantaggio; chi arriva dopo prende la coda.')
        punti -= 2
    if criticita is not None:
        note.append(f'criticita\' provinciale rete livello {criticita}/4 (dato e-Distribuzione, '
                    'riferito alla GENERAZIONE: non si trasferisce tale e quale allo storage).')

    if d_se_m is not None:
        km = d_se_m / 1000.0
        if at:
            note.append(f'{km:.1f} km dalla stazione: in AT il collegamento tipico e\' in '
                        'antenna, lo stallo e\' impianto di rete, la linea e\' del richiedente.')
            punti += 4 if km <= 3 else (2 if km <= 6 else -2)
        else:
            punti += 4 if km <= 2 else (1 if km <= 5 else -4)
    return {'mw': mw, 'alta_tensione': at, 'punteggio_rete': punti,
            'stmg_eur': STMG_EUR, 'note': note}


# ===========================================================================
# 4. ECONOMIA — perche' l'accumulo regge un costo di connessione che il PV no
# ===========================================================================
def economia(dim, stazione_eur=None, canone_eur_mw=None, quota_famiglia=1.0,
             anni=20, tasso=0.05, istat=0.02):
    """Peso della connessione sul capex, e valore del terreno per la proprieta'."""
    st_lo, st_hi = stazione_eur or STAZIONE_UTENTE_EUR
    cx_lo, cx_hi = dim['capex_eur']
    quota = (st_lo / cx_hi, st_hi / cx_lo) if cx_lo else (0, 0)

    can_lo, can_hi = canone_eur_mw or CANONE_EUR_MW_ANNO
    van = {}
    for etichetta, c in (('basso', can_lo), ('alto', can_hi)):
        c0 = dim['mw'] * c * quota_famiglia
        van[etichetta] = round(sum(c0 * (1 + istat) ** t / (1 + tasso) ** (t + 1)
                                   for t in range(anni)))
    return {
        'capex_eur': dim['capex_eur'],
        'stazione_eur': (st_lo, st_hi),
        'quota_connessione_su_capex': (round(quota[0], 3), round(quota[1], 3)),
        'sostenibile': quota[1] <= 0.15,
        'canone_annuo_famiglia_eur': (round(dim['mw'] * can_lo * quota_famiglia),
                                      round(dim['mw'] * can_hi * quota_famiglia)),
        'van_famiglia_eur': (van['basso'], van['alto']),
        'anni': anni,
        'riferimento_pv': ('su 15 MWp di agrivoltaico lo stesso costo di stazione pesa '
                           '~18% del capex; e\' la differenza che decide chi sopravvive'),
    }


def canone_confronto(dim, ha_sito, canone_eur_mw=None, canone_eur_ha=None):
    """Le due basi di calcolo del canone, messe una accanto all'altra.

    ATTENZIONE — questa funzione esiste per smontare un errore che e' facilissimo
    fare (e che ho fatto): dire "il BESS si paga per MW, non per ettaro" suona
    come un vantaggio strutturale, ma **se i MW sono proporzionali agli ettari,
    EUR/MW e' solo EUR/ha riscalato**. Non c'e' nessuna magia nella metrica: se
    il BESS rende di piu' per ettaro e' per il LIVELLO del canone, non per come
    lo si misura. E il livello va chiesto a un developer, non assunto.

    Il controllo utile e' il canone come quota del capex: se le due tecnologie
    atterrano su percentuali molto diverse, l'assunto e' probabilmente sbagliato.
    """
    c_mw = canone_eur_mw or CANONE_EUR_MW_ANNO
    per_ha_implicito = tuple(round(dim['mw'] * c / ha_sito) for c in c_mw) if ha_sito else (0, 0)
    capex_medio = sum(dim['capex_eur']) / 2
    quota_capex = tuple(round(dim['mw'] * c / capex_medio, 4) for c in c_mw) if capex_medio else (0, 0)
    out = {
        'base_per_mw': c_mw,
        'canone_sito_eur_anno': tuple(round(dim['mw'] * c) for c in c_mw),
        'per_ha_implicito_eur': per_ha_implicito,
        'quota_su_capex': quota_capex,
        'riferimento_pv_eur_ha': (1_500, 3_000),
        'riferimento_pv_quota_capex': 0.0074,
    }
    if canone_eur_ha:
        out['base_per_ha'] = canone_eur_ha
        out['canone_sito_da_ha_eur_anno'] = tuple(round(c * ha_sito) for c in canone_eur_ha)
        lo = out['canone_sito_eur_anno'][0] or 1
        out['rapporto_mw_su_ha'] = round(out['canone_sito_eur_anno'][1]
                                         / max(out['canone_sito_da_ha_eur_anno'][1], 1), 1)
    out['allarme'] = (per_ha_implicito[1] > 8 * out['riferimento_pv_eur_ha'][1])
    out['nota'] = ('Se il canone per ettaro implicito e\' molto sopra quello agrivoltaico, '
                   'l\'assunto EUR/MW e\' probabilmente troppo generoso: verificarlo PRIMA '
                   'di portare qualunque VAN alla famiglia.')
    return out


def sbancamento(ha_utile, slope_pct, platee=1):
    """Movimento terra per ottenere una platea. Cresce col CUBO del lato.

    Su un versante di pendenza p, spianare una piastra quadrata di lato L
    richiede di compensare un dislivello Dh = L*p da un capo all'altro. Con
    sterro e riporto in equilibrio (mezza piastra si scava, mezza si riempie)
    il volume di scavo e' ~ L^2 * Dh / 8 = L^3 * p / 8.

    Il termine L^3 e' il motivo per cui **terrazzare conviene sempre**: dividere
    in `platee` gradoni riduce il lato di ciascuno di sqrt(n) e il volume totale
    di un fattore sqrt(n). Non e' un dettaglio contabile — su questi siti e' la
    differenza fra un costo trascurabile e uno che si vede a bilancio.
    """
    if slope_pct is None or ha_utile is None or ha_utile <= 0:
        return None
    platee = max(1, int(platee))
    lato = math.sqrt(ha_utile * 10000 / platee)
    vol = platee * (lato ** 3) * (slope_pct / 100.0) / 8.0
    vol1 = (math.sqrt(ha_utile * 10000) ** 3) * (slope_pct / 100.0) / 8.0
    return {
        'platee': platee,
        'lato_platea_m': round(lato),
        'volume_mc': round(vol),
        'costo_eur': round(vol * SBANCAMENTO_EUR_MC),
        'costo_platea_unica_eur': round(vol1 * SBANCAMENTO_EUR_MC),
        'nota': ('ordine di grandezza per confrontare siti, non un computo metrico. '
                 'Il volume scala con L^3: terrazzare in n gradoni lo divide per sqrt(n).'),
    }


# ===========================================================================
# 5. VINCOLI SPECIFICI DELL'ACCUMULO
# ===========================================================================
def vincoli_bess(p):
    """Cosa pesa su un accumulo e NON su un campo fotovoltaico (e viceversa).

    p: dict come quello di engine.score_parcel, piu' d_abitato_m, accesso_mezzi_pesanti.
    """
    flag, blocker = [], False

    idr = p.get('pai_idr')
    if idr is None:
        flag.append('PAI idraulico NON verificato — per un accumulo e\' il primo controllo, '
                    'non l\'ultimo: allagare cabinati con celle al litio e\' scenario '
                    'inaccettabile per VVF e assicuratore')
    elif idr >= 1:
        blocker = idr >= 2
        flag.append(f'PAI idraulico P{idr}: per il BESS pesa PIU\' che per il fotovoltaico '
                    f'({"escludente" if blocker else "da superare con studio idraulico"})')

    d_b = p.get('d_bosco_m')
    if d_b is not None and d_b < D_BOSCO_MIN_M:
        flag.append(f'bosco a {d_b:.0f} m (<{D_BOSCO_MIN_M:.0f}): rischio incendio nei DUE '
                    'sensi — l\'accumulo verso il bosco e il bosco verso l\'accumulo')

    d_a = p.get('d_abitato_m')
    if d_a is None:
        flag.append('distanza dalle abitazioni NON verificata: rumore dei gruppi di '
                    'raffreddamento e scenario incendio la rendono dirimente in conferenza')
    elif d_a < D_ABITATO_MIN_M:
        flag.append(f'abitazioni a {d_a:.0f} m (<{D_ABITATO_MIN_M:.0f}): opposizione probabile')

    sl = p.get('slope')
    if sl is not None:
        if sl > PEND_LIMITE:
            blocker = True
            flag.append(f'pendenza {sl:.1f}%: oltre il limite per una platea ({PEND_LIMITE:.0f}%)')
        elif sl > PEND_OK:
            flag.append(f'pendenza {sl:.1f}%: al limite, platea con sbancamento rilevante')
        elif sl > PEND_IDEALE:
            flag.append(f'pendenza {sl:.1f}%: accettabile, ma terrazzare conviene '
                        f'(sotto {PEND_IDEALE:.0f}% la platea e\' quasi gratis)')

    if p.get('accesso_mezzi_pesanti') is False:
        flag.append('accesso mezzi pesanti assente: i cabinati arrivano su bilico, serve '
                    'una viabilita\' con raggi di curvatura adeguati — costo di adeguamento')
    elif p.get('accesso_mezzi_pesanti') is None:
        flag.append('accesso mezzi pesanti NON verificato')

    # I vincoli che il fotovoltaico teme e l'accumulo no: vanno detti, perche'
    # sono la ragione strategica per cui questo sito puo' valere per il BESS.
    favorevoli = []
    if p.get('zps_pct', 0) > 10:
        favorevoli.append('dentro ZPS: la VINCA resta obbligatoria, ma il regime "aree non '
                          'idonee" del D.Lgs 199/2021 riguarda gli impianti FER — un accumulo '
                          'non produce energia. Da far confermare, e\' il punto piu' + ' delicato.')
    if p.get('coltura_storica') or p.get('dop_igp'):
        favorevoli.append('vincoli agronomici (PLV, colture di pregio) non si applicano: '
                          'nessuna coltura sotto i cabinati da dimostrare')
    if p.get('sismica') is None:
        flag.append('zona sismica NON verificata: il beneventano e\' ad alta sismicita\' e '
                    'incide sulle fondazioni dei cabinati')
    return {'blocker': blocker, 'criticita': flag, 'favorevoli': favorevoli}


# ===========================================================================
# 6. SCAN — l'analogo di blocco.frontiera(), ma per piattaforme
# ===========================================================================
# Per l'agrivoltaico la domanda e' "fino a dove posso crescere": si massimizzano
# gli ettari contigui e si accettano molte controparti. Per l'accumulo la
# domanda si rovescia: **qual e' il pezzo PIU' COMPATTO da 3-5 ha, e di chi e'.**
# Crescere oltre non serve a niente e costa firme.

def _centroide(poly):
    return (sum(q[0] for q in poly) / len(poly), sum(q[1] for q in poly) / len(poly))


def _adiacenza(particelle, thr_m=25.0):
    n = len(particelle)
    la0 = sum(_centroide(p['poly'])[0] for p in particelle) / n
    k = 111320 * math.cos(math.radians(la0))
    mp = [[(q[1] * k, q[0] * 110540) for q in p['poly']] for p in particelle]
    cen = [(sum(x for x, y in m) / len(m), sum(y for x, y in m) / len(m)) for m in mp]
    rad = [max(math.dist(c, q) for q in m) for c, m in zip(cen, mp)]
    adj = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if math.dist(cen[i], cen[j]) > rad[i] + rad[j] + thr_m:
                continue                                   # prefiltro sui cerchi
            if min(math.dist(a, b) for a in mp[i] for b in mp[j]) <= thr_m:
                adj[i].add(j)
                adj[j].add(i)
    return adj, mp, cen


def candidati(particelle, target_ha=4.0, se_latlon=None, max_siti=8, thr_m=25.0):
    """Trova i migliori SITI-PIATTAFORMA dentro un insieme di particelle.

    Ritorna una lista ordinata: per ogni sito, quali particelle, quanti ettari,
    quante controparti, il lato del quadrato inscritto e la distanza dalla
    stazione. E' il ranking che serve per decidere a chi bussare per primo.
    """
    adj, mp, cen = _adiacenza(particelle, thr_m)
    visti, out = set(), []
    ordine = sorted(range(len(particelle)),
                    key=lambda i: (not particelle[i].get('ancora'),
                                   -(particelle[i].get('netti') or 0)))
    for seed in ordine:
        sel = [seed]
        ha = particelle[seed].get('netti') or 0
        while ha < target_ha:
            cand = set().union(*(adj[i] for i in sel)) - set(sel)
            if not cand:
                break
            def raggio(j):
                pts = [q for i in sel + [j] for q in mp[i]]
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                return sum(math.dist((cx, cy), p) for p in pts) / len(pts)
            b = min(cand, key=raggio)
            sel.append(b)
            ha += particelle[b].get('netti') or 0
        chiave = frozenset(sel)
        if chiave in visti or ha < target_ha * 0.6:
            continue
        visti.add(chiave)
        gruppo = [particelle[i] for i in sel]
        pf = piattaforma(gruppo)
        acq = [p for p in gruppo if not p.get('ancora')]
        fam = sum(p.get('netti') or 0 for p in gruppo if p.get('ancora'))
        d_se = None
        if se_latlon:
            c = _centroide(particelle[seed]['poly'])
            d_se = math.dist((c[0] * 110540, c[1] * 111320 * math.cos(math.radians(c[0]))),
                             (se_latlon[0] * 110540,
                              se_latlon[1] * 111320 * math.cos(math.radians(se_latlon[0]))))
        dim = dimensiona(pf['ha_utile'], ha_quadrato=pf['ha_quadrato_inscritto'])
        out.append({
            'particelle': [f"Fg{p['fg']}/{p['pla']}" for p in gruppo],
            'n': len(gruppo), 'ha': round(ha, 2),
            'ha_famiglia': round(fam, 2), 'quota_famiglia': round(fam / ha, 3) if ha else 0,
            'controparti': len(acq),
            'da_acquisire': [f"Fg{p['fg']}/{p['pla']}" for p in acq],
            'lato_m': pf['lato_quadrato_m'], 'ha_utile': pf['ha_utile'],
            'riempimento': pf['riempimento_bbox'],
            'mw': dim['mw'], 'mw_conservativo': (dim['conservativo'] or {}).get('mw'),
            'd_se_m': round(d_se) if d_se else None,
        })
    # ranking: piattaforma buona, poche firme, quota di famiglia alta
    def punteggio(s):
        return (s['lato_m'] / 10.0
                - 6.0 * s['controparti']
                + 20.0 * s['quota_famiglia']
                - (s['d_se_m'] or 0) / 1000.0)
    out.sort(key=punteggio, reverse=True)
    for i, s in enumerate(out, 1):
        s['rank'] = i
        s['punteggio'] = round(punteggio(s), 1)
    return out[:max_siti]


def print_candidati(righe):
    L = ["\n=== CANDIDATI PIATTAFORMA BESS (ordinati) ===",
         f"  {'#':>2} {'ha':>6} {'fam%':>5} {'ctp':>4} {'lato':>6} {'MW':>7} {'d.SE':>6}  particelle"]
    for s in righe:
        mwr = (f"{s['mw_conservativo']:.0f}-{s['mw']:.0f}"
               if s['mw_conservativo'] else f"{s['mw']:.0f}")
        L.append(f"  {s['rank']:>2} {s['ha']:>6.2f} {100*s['quota_famiglia']:>4.0f}% "
                 f"{s['controparti']:>4} {s['lato_m']:>5.0f}m {mwr:>7} "
                 f"{(s['d_se_m'] or 0)/1000:>5.1f}k  "
                 + ' '.join(s['particelle'][:6]) + (' …' if s['n'] > 6 else ''))
    L.append("  ~ 'lato' = quadrato inscritto: sotto 80 m non ci sta un layout con corridoi.")
    L.append("  ~ 'ctp' = controparti da acquisire. Per un BESS ogni firma in piu' e' costo puro.")
    return '\n'.join(L)


def png(particelle, out, franco_m=FRANCO_BESS_M, ris=RIS_M):
    """Verifica visiva: grigio = particelle, verde = area utile, rosso = quadrato
    inscritto massimo. Il riquadro rosso e' cio' che un accumulo occupa davvero:
    guardarlo evita di innamorarsi di un totale di ettari che non fa una platea.
    """
    mp = _proj([p['poly'] for p in particelle])
    mask, (x0, y0, W, H) = _maschera(mp, ris)
    utile = mask
    for _ in range(max(1, int(round(franco_m / ris)))):
        utile = _erodi8(utile)
    d = _distanza_bordo(mask)
    rgb = np.zeros(mask.shape + (3,), dtype=np.uint8)
    rgb[mask] = (85, 85, 85)
    rgb[utile] = (60, 190, 90)
    if d.max() > 0:
        cy, cx = np.unravel_index(int(np.argmax(d)), d.shape)
        r = int(d.max())
        img = Image.fromarray(rgb)
        ImageDraw.Draw(img).rectangle([cx - r, cy - r, cx + r, cy + r],
                                      outline=(230, 60, 60), width=2)
        img.save(out)
    else:
        Image.fromarray(rgb).save(out)
    return out


# ===========================================================================
# 7. ORCHESTRATORE
# ===========================================================================
def analizza(particelle, slope_pct=None, inversione=None, d_se_m=None,
             coda_mw=None, criticita=None, quota_famiglia=1.0, densita='media',
             durata_h=DURATA_H, strade=None, p_vincoli=None):
    pf = piattaforma(particelle, strade=strade)
    dim = dimensiona(pf['ha_utile'], densita=densita, durata_h=durata_h,
                     ha_quadrato=pf['ha_quadrato_inscritto'])
    rt = rete(dim['mw'], inversione=inversione, d_se_m=d_se_m,
              coda_mw=coda_mw, criticita=criticita)
    ec = economia(dim, quota_famiglia=quota_famiglia)
    # 4 gradoni: compromesso tipico fra costo di terrazzamento e perdita di superficie
    sb = sbancamento(pf['ha_utile'], slope_pct, platee=4)
    vc = vincoli_bess(dict(p_vincoli or {}, slope=slope_pct))
    return {'piattaforma': pf, 'taglia': dim, 'rete': rt, 'economia': ec,
            'sbancamento': sb, 'vincoli': vc, 'densita_implicita': densita_implicita(),
            'mt_alternativa': taglia_per_restare_in_mt(durata_h, densita)}


def print_analisi(r, titolo='SITO'):
    pf, d, rt, ec = r['piattaforma'], r['taglia'], r['rete'], r['economia']
    L = []
    A = L.append
    A(f"\n{'='*74}\n  BESS — {titolo}\n{'='*74}")
    A(f"  GEOMETRIA   {pf['ha_netti_dichiarati']} ha netti -> {pf['ha_utile']} ha utili "
      f"(resa {100*pf['resa_forma']:.0f}%)")
    A(f"              quadrato inscritto {pf['lato_quadrato_m']:.0f} m di lato = "
      f"{pf['ha_quadrato_inscritto']} ha  [{'OK' if pf['piattaforma_ok'] else 'TROPPO STRETTO'}]")
    A(f"              riempimento del rettangolo di ingombro {100*pf['riempimento_bbox']:.0f}%")
    A(f"  TAGLIA      {d['mwh']:.0f} MWh / {d['mw']:.1f} MW ({d['durata_h']:.0f} h, "
      f"{d['densita_mwh_ha']:.0f} MWh/ha)  [ipotesi: platee terrazzate]")
    if d.get('conservativo'):
        c = d['conservativo']
        A(f"              forbice onesta: {c['mw']:.1f} MW (una sola platea, {c['ha']} ha) "
          f"... {d['mw']:.1f} MW (tutta la superficie erosa)")
    A(f"              {d['posizione_mercato']} — registro VIA: mediana "
      f"{VIA_TAGLIE_MW['mediana']:.0f} MW, quartili {VIA_TAGLIE_MW['q1']:.0f}-{VIA_TAGLIE_MW['q3']:.0f}")
    A(f"              capex {d['capex_eur'][0]/1e6:.1f}-{d['capex_eur'][1]/1e6:.1f} M EUR")
    A(f"  RETE        {'ALTA TENSIONE (Terna)' if rt['alta_tensione'] else 'media tensione (e-Distribuzione)'}"
      f"   punteggio {rt['punteggio_rete']:+d}")
    for n in rt['note']:
        A(f"                - {n}")
    A(f"  ECONOMIA    connessione = {100*ec['quota_connessione_su_capex'][0]:.0f}-"
      f"{100*ec['quota_connessione_su_capex'][1]:.0f}% del capex  "
      f"[{'SOSTENIBILE' if ec['sostenibile'] else 'PESANTE'}]")
    A(f"              ~ {ec['riferimento_pv']}")
    A(f"              canone famiglia {ec['canone_annuo_famiglia_eur'][0]:,} - "
      f"{ec['canone_annuo_famiglia_eur'][1]:,} EUR/anno")
    A(f"              VAN {ec['anni']} anni: {ec['van_famiglia_eur'][0]:,} - "
      f"{ec['van_famiglia_eur'][1]:,} EUR")
    if r['sbancamento']:
        sb = r['sbancamento']
        A(f"  PLATEE      {sb['platee']} gradoni da ~{sb['lato_platea_m']} m: "
          f"{sb['volume_mc']:,} mc = ~{sb['costo_eur']:,} EUR")
        A(f"              (platea unica costerebbe ~{sb['costo_platea_unica_eur']:,} EUR: "
          f"terrazzare divide per sqrt(n))")
    di = r['densita_implicita']
    A(f"  CONTROLLO   densita' implicita da mercato+developer: {di['mw_per_ha'][0]}-"
      f"{di['mw_per_ha'][1]} MW/ha = {di['mwh_per_ha'][0]:.0f}-{di['mwh_per_ha'][1]:.0f} MWh/ha "
      f"-> assunto {'COERENTE' if di['coerente_con_assunto'] else 'DA RIVEDERE'}")
    mt = r['mt_alternativa']
    A(f"  ALTERNATIVA restare sotto i 10 MW (in MT) vuole max {mt['ha_max']} ha utili")
    if r['vincoli']['criticita']:
        A("  CRITICITA'")
        for f in r['vincoli']['criticita']:
            A(f"                ! {f}")
    if r['vincoli']['favorevoli']:
        A("  A FAVORE (cio' che ferma il fotovoltaico e non l'accumulo)")
        for f in r['vincoli']['favorevoli']:
            A(f"                + {f}")
    return '\n'.join(L)


# ---------------------------------------------------------------- CLI
def main():
    """Punto d'ingresso: `python -m landscout.bess --parcels blocco.json`.

    Esiste perche' fino all'08/08/2026 questo modulo non lo chiamava nessuno —
    ne' un altro modulo ne' una riga di comando — e uno screening che non si puo'
    lanciare e' uno screening che non esiste. L'accumulo NON e' un caso
    particolare del fotovoltaico: vuole una platea, non un campo, e la domanda
    "dove sta il quadrato piu' grande" non e' quella di `installabile.py`.
    """
    import argparse
    import json
    import sys

    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    ap = argparse.ArgumentParser(description='Screening per accumuli (BESS).')
    ap.add_argument('--parcels', required=True,
                    help="JSON [{'fg','pla','ha','poly'}] oppure l'uscita di blocco "
                         "(si legge blocco.particelle)")
    ap.add_argument('--siti', action='store_true',
                    help='cerca i migliori siti-piattaforma dentro le particelle '
                         'invece di analizzare tutto come un sito solo')
    ap.add_argument('--target-ha', type=float, default=4.0)
    ap.add_argument('--slope', type=float, default=None, help='pendenza media %%')
    ap.add_argument('--d-se-m', type=float, default=None, help='distanza dalla sottostazione')
    ap.add_argument('--prov', default=None,
                    help='sigla o nome provincia: aggiunge la criticita e-Distribuzione')
    ap.add_argument('--coda-mw', type=float, default=None)
    ap.add_argument('--quota-famiglia', type=float, default=1.0)
    ap.add_argument('--zona-macse', default='sud', choices=sorted(MACSE_EUR_MWH_ANNO))
    ap.add_argument('--png', default=None, help='verifica visiva della piattaforma')
    A = ap.parse_args()

    d = json.load(open(A.parcels, encoding='utf-8'))
    part = (d.get('blocco', {}).get('particelle') if isinstance(d, dict) else d) or d
    part = [p for p in part if p.get('poly')]
    if not part:
        raise SystemExit('nessuna particella con geometria: il BESS si misura sulla forma')

    crit = None
    if A.prov:
        from . import capacita as CAP
        from . import config as CFG
        c = CAP.criticita_provincia(CFG.nome_prov(A.prov), cod_pro=CFG.cod_prov(A.prov))
        crit = c.get('livello') if c.get('verificato') else None
        if not c.get('verificato'):
            print(f"   criticita rete NON verificata: {c.get('nota')}")

    if A.siti:
        print_candidati(candidati(part, target_ha=A.target_ha))
        return

    r = analizza(part, slope_pct=A.slope, d_se_m=A.d_se_m, coda_mw=A.coda_mw,
                 criticita=crit, quota_famiglia=A.quota_famiglia)
    print(print_analisi(r))
    mc = ricavo_macse(r['taglia'], zona=A.zona_macse)
    q = mc['quota_ricavo']
    print(f"\n  MACSE       {mc['mwh']:.0f} MWh x {mc['eur_mwh_anno']:,} EUR/MWh-anno = "
          f"~{mc['ricavo_eur_anno']:,} EUR/anno di sola capacita ({mc['zona']})")
    if q[0] is not None:
        print(f"              il canone chiesto ne assorbe il {q[0]:.1%}-{q[1]:.1%} "
              f"— {mc['nota']}")
    if A.png:
        png(part, A.png)
        print(f'\n  scritto: {A.png}')


if __name__ == '__main__':
    main()
