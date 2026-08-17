"""land-scout prossimita' — i vincoli che dipendono dalla DISTANZA da qualcosa.

Tre controlli che a Morcone erano stati verificati a mano a luglio e non erano
mai entrati nel tool, con il risultato che ogni blocco rigenerato li perdeva:

- **buffer dai beni tutelati** (500 m, DM 21/06/2024 aree non idonee): a Morcone
  la chiesa interessava il **95% del Foglio 70**;
- **corridoio ecologico** del Tammaro (500 m): ~40% della superficie;
- **pendenza**: non e' un vincolo di legge ma un limite economico, e sopra il
  10-15% il costo delle strutture e del movimento terra mangia il margine.

I primi due sono buffer attorno a geometrie note; il terzo viene dal DEM.

⚠️ **I beni tutelati NON si indovinano dal nome.** Il modulo prende le geometrie
da OSM (chiese, castelli, monumenti, cimiteri) come *innesco*, ma il perimetro
vincolato vero e' quello del decreto di tutela: cio' che esce di qui e' un
elenco di **verifiche da fare**, non un verdetto. Una chiesa in OSM puo' non
essere vincolata, e un bene vincolato puo' non essere in OSM.

Uso:
    from landscout import prossimita
    b = prossimita.beni_tutelati(particelle)        # OSM + buffer 500 m
    c = prossimita.corridoio(particelle, corsi)     # buffer da idrografia
    p = prossimita.pendenza(particelle)             # DEM opentopodata
"""
import json
import math
import re
import time
import urllib.parse
import urllib.request

OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter',
            'https://overpass.private.coffee/api/interpreter']
UA = {'User-Agent': 'land-scout prossimita'}

BUFFER_BENE_M = 500.0        # DM 21/06/2024: fascia di rispetto dai beni tutelati
BUFFER_CORRIDOIO_M = 500.0   # corridoi ecologici regionali (Campania)
PEND_MAX_AGRIPV = 15.0       # oltre, strutture e movimento terra fuori budget
PEND_ATTENZIONE = 10.0

# Cio' che, se tutelato, genera la fascia dei 500 m. Innesco, non elenco ufficiale.
TAG_BENI = [
    ('historic', ['church', 'monument', 'castle', 'ruins', 'archaeological_site',
                  'memorial', 'tower', 'city_gate', 'monastery']),
    ('amenity', ['place_of_worship', 'grave_yard', 'monastery']),
    ('building', ['church', 'chapel', 'cathedral', 'monastery']),
    ('landuse', ['cemetery']),
    ('tourism', ['museum']),
]


def _overpass(q, timeout=120, tentativi=2):
    errori = []
    for _ in range(tentativi):
        for ep in OVERPASS:
            try:
                req = urllib.request.Request(
                    ep, data=urllib.parse.urlencode({'data': q}).encode(), headers=UA)
                return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            except Exception as e:
                errori.append(f'{ep.split("/")[2]}: {type(e).__name__}')
        time.sleep(5)
    raise RuntimeError('Overpass non raggiungibile: ' + '; '.join(errori[-3:]))


def _proj(particelle):
    lats = [q[0] for p in particelle for q in p['poly']]
    la0 = (min(lats) + max(lats)) / 2
    k = 111320 * math.cos(math.radians(la0))
    return (lambda pts: [(q[1] * k, q[0] * 110540) for q in pts])


def _bbox(particelle, m=0.012):
    la = [q[0] for p in particelle for q in p['poly']]
    lo = [q[1] for p in particelle for q in p['poly']]
    return (min(la) - m, min(lo) - m, max(la) + m, max(lo) + m)


def _dist_punto_seg(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def beni_tutelati(particelle, buffer_m=BUFFER_BENE_M, timeout=120):
    """Particelle entro `buffer_m` da un potenziale bene tutelato (OSM).

    Restituisce, per ogni particella, la distanza dal bene piu' vicino e quali
    sono. **Non e' un verdetto di esclusione**: il perimetro vincolato vero sta
    nel decreto, e va letto. Serve a sapere DOVE guardare.
    """
    bb = _bbox(particelle)
    parti = []
    for chiave, valori in TAG_BENI:
        for v in valori:
            parti.append(f'node["{chiave}"="{v}"]({bb[0]},{bb[1]},{bb[2]},{bb[3]});')
            parti.append(f'way["{chiave}"="{v}"]({bb[0]},{bb[1]},{bb[2]},{bb[3]});')
    d = _overpass(f'[out:json][timeout:120];({"".join(parti)});out center tags;', timeout)

    beni = []
    for e in d.get('elements', []):
        la = e.get('lat') or (e.get('center') or {}).get('lat')
        lo = e.get('lon') or (e.get('center') or {}).get('lon')
        if la is None:
            continue
        tg = e.get('tags') or {}
        beni.append({'lat': la, 'lon': lo, 'nome': tg.get('name') or '(senza nome)',
                     'tipo': (tg.get('historic') or tg.get('amenity') or
                              tg.get('building') or tg.get('landuse') or tg.get('tourism'))})
    M = _proj(particelle)
    pb = [(M([[b['lat'], b['lon']]])[0], b) for b in beni]

    out = {}
    for p in particelle:
        m = M(p['poly'])
        best = None
        for xy, b in pb:
            dd = min(math.dist(v, xy) for v in m)
            if best is None or dd < best[0]:
                best = (dd, b)
        if best:
            out[f"{p['fg']}_{p['pla']}"] = {
                'd_m': round(best[0]), 'entro_buffer': best[0] <= buffer_m,
                'bene': best[1]['nome'], 'tipo': best[1]['tipo']}
    return {'beni_trovati': len(beni), 'buffer_m': buffer_m, 'particelle': out,
            'n_entro': sum(1 for v in out.values() if v['entro_buffer']),
            'nota': ('geometrie OSM come innesco: il perimetro vincolato vero e\' nel '
                     'decreto di tutela. Elenco di verifiche, non verdetto.')}


def corridoio(particelle, buffer_m=BUFFER_CORRIDOIO_M, timeout=120):
    """Particelle entro `buffer_m` da un corso d'acqua principale.

    I corridoi ecologici regionali si appoggiano di norma all'idrografia. Qui si
    usa l'asta principale (waterway=river) come proxy: **il perimetro ufficiale
    va letto sul PTR/PTCP**, questo dice solo chi e' in gioco.
    """
    bb = _bbox(particelle)
    q = (f'[out:json][timeout:120];('
         f'way["waterway"="river"]({bb[0]},{bb[1]},{bb[2]},{bb[3]});'
         f'way["natural"="water"]({bb[0]},{bb[1]},{bb[2]},{bb[3]}););out geom tags;')
    d = _overpass(q, timeout)
    M = _proj(particelle)
    segs, nomi = [], set()
    for e in d.get('elements', []):
        g = e.get('geometry')
        if not g:
            continue
        nomi.add((e.get('tags') or {}).get('name') or '(senza nome)')
        pts = M([(x['lat'], x['lon']) for x in g])
        segs += [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]

    out = {}
    for p in particelle:
        m = M(p['poly'])
        dd = min(_dist_punto_seg(v, a, b) for v in m for a, b in segs) if segs else None
        out[f"{p['fg']}_{p['pla']}"] = {
            'd_m': round(dd) if dd is not None else None,
            'entro_buffer': bool(dd is not None and dd <= buffer_m)}
    return {'corsi': sorted(nomi), 'buffer_m': buffer_m, 'particelle': out,
            'n_entro': sum(1 for v in out.values() if v['entro_buffer']),
            'nota': ('proxy sull\'idrografia principale: il corridoio ufficiale sta nel '
                     'PTR/PTCP e va verificato li\'.')}


# TINITALY (INGV): DEM nazionale a 10 m con la PENDENZA gia' derivata come layer.
# Verificato il 10/08/2026: `tinitaly_dem` restituisce la quota (488,1 m su
# Fg70/142 a Morcone) e `tinitaly_slope` la pendenza, via GetFeatureInfo.
# Perche' conta: il tool stimava la pendenza da SRTM a 30 m campionando i
# vertici — su un fondo di 100 m di lato significa 3 celle in tutto, e una
# scarpata di bordo puo' sparire o inventarsi. A 10 m le celle sono 100, e la
# pendenza non la deriviamo noi: la fornisce chi ha costruito il modello.
TINITALY = 'https://tinitaly.pi.ingv.it/TINItaly_1_1/ows'
TINITALY_SLOPE, TINITALY_DEM = 'tinitaly_slope', 'tinitaly_dem'


def _tinitaly(lat, lon, layer=TINITALY_SLOPE, d=0.0008, timeout=60):
    """Valore del raster nel punto. None se il servizio non risponde o non copre."""
    p = {'service': 'WMS', 'version': '1.1.1', 'request': 'GetFeatureInfo',
         'layers': layer, 'query_layers': layer, 'styles': '', 'srs': 'EPSG:4326',
         'bbox': f'{lon - d},{lat - d},{lon + d},{lat + d}',
         'width': '101', 'height': '101', 'x': '50', 'y': '50',
         'info_format': 'text/plain'}
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            TINITALY + '?' + urllib.parse.urlencode(p), headers=UA), timeout=timeout)
        txt = r.read().decode('utf-8', 'replace')
    except Exception:
        return None
    m = re.search(r'GRAY_INDEX\s*=\s*(-?[\d.]+)', txt)
    if not m:
        return None
    v = float(m.group(1))
    # il nodata dei raster INGV esce come valore assurdo: fuori dominio -> None,
    # mai zero (una pendenza 0 inventata fa passare per pianura una scarpata).
    # ⚠ Il dominio dipende dal LAYER: 0-90 gradi per la pendenza, ma le QUOTE
    # italiane arrivano a 4.800 m. Con un solo intervallo 0-90 il layer del DEM
    # rispondeva None ovunque sopra i 90 m di altitudine — cioe' quasi ovunque,
    # in silenzio (trovato il 10/08/2026 interrogando Morcone, 409 m).
    lo, hi = (-500.0, 5000.0) if layer == TINITALY_DEM else (-1.0, 90.0)
    if v < lo or v > hi:
        return None
    return v


def pendenza_tinitaly(particelle, campioni=5, timeout=60):
    """Pendenza per particella dal layer TINITALY (10 m), campionando pochi punti.

    Restituisce lo stesso formato di `pendenza()`, cosi' i due sono
    intercambiabili a valle. Una particella che il servizio non copre resta
    `verificata: False` — non 0%.
    """
    out = {}
    letti = 0
    for p in particelle:
        k = f"{p['fg']}_{p['pla']}"
        anello = p['poly']
        cx = sum(q[0] for q in anello) / len(anello)
        cy = sum(q[1] for q in anello) / len(anello)
        pts = [(cx, cy)] + [tuple(q) for q in anello[:max(0, campioni - 1)]]
        val = [v for v in (_tinitaly(a, b, timeout=timeout) for a, b in pts)
               if v is not None]
        if not val:
            out[k] = {'pendenza_pct': None, 'verificata': False}
            continue
        letti += 1
        med = sum(val) / len(val)
        out[k] = {'pendenza_pct': round(med, 1), 'pendenza_max_pct': round(max(val), 1),
                  'campioni': len(val), 'verificata': True,
                  'oltre_limite': med > PEND_MAX_AGRIPV,
                  'attenzione': PEND_ATTENZIONE < med <= PEND_MAX_AGRIPV}
    ok = [v for v in out.values() if v.get('verificata')]
    return {'particelle': out, 'dataset': 'TINITALY 10 m (INGV), layer tinitaly_slope',
            'n_verificate': len(ok), 'n_non_verificate': len(out) - len(ok),
            'n_oltre_limite': sum(1 for v in ok if v['oltre_limite']),
            'limite_pct': PEND_MAX_AGRIPV,
            'nota': ('pendenza gia derivata dal modello a 10 m, non ricalcolata da noi '
                     'sui vertici. Dove il servizio non copre resta NON verificata.')}


def pendenza(particelle, dataset='srtm30m', timeout=90, punti_max=100, fonte='tinitaly'):
    """Pendenza media per particella.

    `fonte='tinitaly'` (default) usa il DEM nazionale a 10 m con la pendenza gia'
    derivata; se il servizio non risponde si ripiega su opentopodata/SRTM 30 m
    campionando i vertici — piu' grossolano, ma meglio di niente, e la fonte
    effettivamente usata finisce nell'output.

    E' comunque una stima: per il progetto esecutivo serve un rilievo. Basta a
    dire quali fondi sono fuori budget per movimento terra.
    """
    if fonte == 'tinitaly':
        r = pendenza_tinitaly(particelle, timeout=min(timeout, 60))
        if r['n_verificate']:
            return r
        # nessuna particella misurata: il servizio non risponde o non copre.
        # Non si restituisce un risultato vuoto — si prova l'altra fonte.

    campioni, indice = [], []
    for p in particelle:
        pts = p['poly'][:12]
        cx = sum(q[0] for q in p['poly']) / len(p['poly'])
        cy = sum(q[1] for q in p['poly']) / len(p['poly'])
        pts = pts + [[cx, cy]]
        indice.append((f"{p['fg']}_{p['pla']}", len(campioni), len(pts), p))
        campioni += pts

    quote = [None] * len(campioni)
    for i in range(0, len(campioni), punti_max):
        blocco = campioni[i:i + punti_max]
        locs = '|'.join(f'{a},{b}' for a, b in blocco)
        url = f'https://api.opentopodata.org/v1/{dataset}?locations={urllib.parse.quote(locs, safe=",|")}'
        try:
            r = json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=timeout).read())
            for j, x in enumerate(r.get('results', [])):
                quote[i + j] = x.get('elevation')
        except Exception:
            pass
        time.sleep(1.1)      # opentopodata: 1 richiesta/secondo

    M = _proj(particelle)
    out = {}
    for k, i0, n, p in indice:
        qs = [q for q in quote[i0:i0 + n] if q is not None]
        if len(qs) < 3:
            out[k] = {'pendenza_pct': None, 'verificata': False}
            continue
        m = M(p['poly'][:12])
        estensione = max(math.dist(a, b) for a in m for b in m) if len(m) > 1 else 1
        dislivello = max(qs) - min(qs)
        pend = 100 * dislivello / estensione if estensione else 0
        out[k] = {'pendenza_pct': round(pend, 1), 'dislivello_m': round(dislivello, 1),
                  'verificata': True,
                  'oltre_limite': pend > PEND_MAX_AGRIPV,
                  'attenzione': PEND_ATTENZIONE < pend <= PEND_MAX_AGRIPV}
    ok = [v for v in out.values() if v.get('verificata')]
    return {'particelle': out, 'dataset': dataset,
            'n_verificate': len(ok), 'n_non_verificate': len(out) - len(ok),
            'n_oltre_limite': sum(1 for v in ok if v['oltre_limite']),
            'limite_pct': PEND_MAX_AGRIPV,
            'nota': ('stima da DEM sui vertici: per il progetto esecutivo serve un '
                     'rilievo. Dove il DEM non risponde la pendenza resta NON verificata, '
                     'mai assunta buona.')}


# --------------------------------------------------------------------------
# Verifiche che NON si automatizzano (e dirlo e' parte del lavoro)
# --------------------------------------------------------------------------
MANUALI = [
    {"voce": "Catasto incendi comunale (L. 353/2000)",
     "dove": "albo pretorio del Comune; spesso solo PDF, quasi mai in WFS",
     "perche": "le aree percorse dal fuoco hanno divieti pluriennali (10 anni per "
               "edificazione, 15 per destinazioni diverse): un blocco che ci ricade "
               "e morto, e non lo scopri da nessun layer",
     "automatizzabile": False},
    {"voce": "Accessi, servitu e passi carrai",
     "dove": "ente gestore della strada (Comune / Provincia / ANAS)",
     "perche": "le particelle attraversate da viabilita hanno bisogno di titolo per "
               "l accesso di cantiere e per il cavidotto: senza, il layout non si "
               "realizza anche se la terra e tua",
     "automatizzabile": False},
    {"voce": "PLV preesistente (>=80%, Circolare Campania 481104/2026)",
     "dove": "fascicolo aziendale AGEA / dichiarazioni PAC dei proprietari",
     "perche": "la baseline va documentata PRIMA di progettare: e il numero che il "
               "progetto agronomico deve eguagliare, e dipende da cosa coltivavano i "
               "proprietari, non da cosa coltiverai tu",
     "automatizzabile": False},
    {"voce": "Perimetro vero dei beni tutelati (D.Lgs 42/2004 art. 136)",
     "dove": "decreti di tutela, SITAP, Soprintendenza",
     "perche": "il buffer calcolato qui parte da geometrie OSM: dice DOVE guardare, "
               "non cosa e vincolato",
     "automatizzabile": False},
]


def print_manuali():
    print("\n=== VERIFICHE NON AUTOMATIZZABILI ===")
    for m in MANUALI:
        print(f"  [ ] {m['voce']}")
        print(f"      dove:   {m['dove']}")
        print(f"      perche: {m['perche']}")
