"""land-scout — modulo VINCOLI / FATTIBILITA' (v0.1, 15/07/2026).

Studio automatico dei vincoli che decidono la FATTIBILITA' autorizzativa di un
progetto FV/agriPV, da FONTI UFFICIALI (upgrade della Fase 3 che usava buffer OSM).

Tre livelli che il motore scoring da solo non copriva:
  1. HABITAT 6220/6210 (Carta Habitat regionale Campania) → se il terreno e' su
     questi habitat il FV a terra e' VIETATO in ZPS (DGR Campania 617/2024). E' la
     differenza tra "divieto secco" e "solo VINCA".
  2. Natura 2000 ZPS vs SIC/ZSC (EEA) → la ZPS attiva la VINCA su avifauna
     (Dir. Uccelli); il SIC aggiunge la Dir. Habitat. Distinguere cambia lo scope.
  3. SITAP ufficiale (Min. Cultura) → usi civici (RISCHIO TITOLO per la vendita),
     tratturi/archeologico, boschi 142-g, art.136, fasce lago 142-b / fiume 142-c.
     Riempie i gap che il README dichiarava "verifica manuale".

Verdetto per particella:
  BLOCK_HABITAT  = su 6220/6210 → FV a terra vietato (solo agriPV sopraelevato, incerto)
  VINCA          = dentro ZPS/SIC, ma non su habitat vietato → iter VINCA (gestibile)
  PAESAGGIO      = fuori Natura2000 ma con vincolo paesaggistico (autorizzazione)
  TITOLO         = usi civici → verificare prima di vendere
  CLEAN          = nessun vincolo rilevato

CLI:
  .venv/Scripts/python -m landscout.vincoli --parcels data/.../parcelle.json
  .venv/Scripts/python -m landscout.vincoli --bbox latmin,lonmin,latmax,lonmax

Nota: MVP geografico = Campania (Carta Habitat regionale). Overlay su centroide
(o su ring se presente). Conferma definitiva usi civici = inventario del Comune.
"""
import argparse, json, math, os, struct, sys, time, urllib.error, urllib.parse, urllib.request, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # niente path assoluti: radice auto-rilevata
from landscout.engine import m_per_deg
from landscout.config import (EP, UA, TIMEOUT, SITAP_LAYERS, BAN_CODES, HABITAT_ZIP,
                              HABITAT_PREFIX, copertura, sitap_layers, CHIAVI_SITAP,
                              CORINE_BAN, latlon)
from landscout.cache import cached_file
from shapely.geometry import Polygon, MultiPolygon, LineString, Point, GeometryCollection, shape
from shapely.ops import unary_union

def get(url, timeout=None):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout or TIMEOUT).read().decode('utf-8', 'replace')


class RispostaInutile(Exception):
    """La risposta e' arrivata ma non vale come dato. Va trattata come un guasto.

    ⚠ Esiste per la classe di bug piu' pericolosa trovata in QA (16/07): il **semi-guasto**.
    Un blackout e' onesto — l'eccezione si vede. Ma un servizio che risponde **HTTP 200 con
    un body di errore** non solleva nulla: `json.loads` passa, `features` e' vuota, e il tool
    conclude "verificato: nessuna ZPS". Provato: con un body `{'error': {...}}` la P.142 di
    Morcone — dentro la ZPS per 4 fonti concordi — usciva di nuovo **'CLEAN', zps=False**,
    nonostante il flag `ok` introdotto poche ore prima contro i blackout.
    Stessa famiglia: **l'assenza di risposta scambiata per assenza di vincolo**.
    """


def json_valido(testo, chiave_lista='features', fonte=''):
    """Parsa e VALIDA una risposta ArcGIS/WFS. Alza RispostaInutile invece di far finta.

    Controlla, in ordine: che sia JSON; che sia un oggetto (non lista/null); che non sia un
    errore applicativo mascherato da 200; che ci sia la chiave attesa; che la lista non sia
    stata **troncata in silenzio** (ArcGIS: exceededTransferLimit — WFS: numberMatched >
    numberReturned). Il troncamento e' insidioso quanto l'errore: i poligoni oltre il tetto
    semplicemente non esistono, e il verdetto direbbe "pulito".
    """
    try:
        d = json.loads(testo)
    except Exception as e:
        raise RispostaInutile(f'{fonte}: risposta non-JSON ({str(e)[:40]})')
    if not isinstance(d, dict):
        raise RispostaInutile(f'{fonte}: risposta di forma inattesa ({type(d).__name__}, atteso oggetto)')
    if 'error' in d:                      # ArcGIS: errore applicativo con HTTP 200
        e = d['error'] if isinstance(d['error'], dict) else {}
        raise RispostaInutile(f"{fonte}: errore del servizio {e.get('code', '')} "
                              f"{str(e.get('message', d['error']))[:60]}")
    if 'exceptionReport' in d or 'ExceptionReport' in d:      # OGC/WFS
        raise RispostaInutile(f'{fonte}: ExceptionReport del servizio WFS')
    if chiave_lista not in d:
        raise RispostaInutile(f"{fonte}: manca la chiave '{chiave_lista}' "
                              f'(chiavi viste: {sorted(d)[:5]})')
    if d.get('exceededTransferLimit'):
        raise RispostaInutile(f'{fonte}: lista TRONCATA dal servizio (exceededTransferLimit) '
                              '-> i vincoli oltre il tetto sarebbero invisibili')
    nm, nr = d.get('numberMatched'), d.get('numberReturned')
    if isinstance(nm, int) and isinstance(nr, int) and nm > nr:
        raise RispostaInutile(f'{fonte}: lista TRONCATA ({nr} di {nm} elementi) '
                              '-> alzare count o restringere la bbox')
    return d

# ---------- fonti (da config) ----------
SITAP = EP['sitap']
EEA = EP['eea_n2k']
HAB_URL = EP['habitat_campania_zip']
HAB_ZIP = str(HABITAT_ZIP)
HAB_PRE = HABITAT_PREFIX

# ---------- riproiezione WGS84 -> UTM33N (per la Carta Habitat regionale) ----------
_a = 6378137.0; _f = 1/298.257223563; _e2 = _f*(2-_f); _ep2 = _e2/(1-_e2)
_k0 = 0.9996; _lon0 = math.radians(15.0)
def to_utm33(lat, lon):
    phi = math.radians(lat); lam = math.radians(lon)
    N = _a/math.sqrt(1-_e2*math.sin(phi)**2); T = math.tan(phi)**2; C = _ep2*math.cos(phi)**2
    A = (lam-_lon0)*math.cos(phi)
    M = _a*((1-_e2/4-3*_e2**2/64-5*_e2**3/256)*phi-(3*_e2/8+3*_e2**2/32+45*_e2**3/1024)*math.sin(2*phi)
            +(15*_e2**2/256+45*_e2**3/1024)*math.sin(4*phi)-(35*_e2**3/3072)*math.sin(6*phi))
    x = 500000+_k0*N*(A+(1-T+C)*A**3/6+(5-18*T+T**2+72*C-58*_ep2)*A**5/120)
    y = _k0*(M+N*math.tan(phi)*(A**2/2+(5-T+9*C+4*C**2)*A**4/24+(61-58*T+T**2+600*_ep2*0+600*C-330*_ep2)*A**6/720))
    return x, y

# ==========================================================================
#  Overlay
# ==========================================================================
def _bbox_of(parcels, margin=0.01):
    lats = [p['lat'] for p in parcels]; lons = [p['lon'] for p in parcels]
    return (min(lats)-margin, min(lons)-margin, max(lats)+margin, max(lons)+margin)

def sitap_paesaggio(parcels, to_xy, regione=None):
    """Ritorna ({chiave: shapely_union_xy | None}, ok). Poligoni -> aree; linee (tratturo) -> buffer 28 m.
    I layer sono per REGIONE: le chiavi non disponibili restano None = NON verificato (non 'pulito')."""
    layers = sitap_layers(regione) if regione else SITAP_LAYERS
    bmin_lat, bmin_lon, bmax_lat, bmax_lon = _bbox_of(parcels, 0.008)
    bbox = f'{bmin_lat},{bmin_lon},{bmax_lat},{bmax_lon},urn:ogc:def:crs:EPSG::4326'
    out = {k: None for k in CHIAVI_SITAP}   # default: non verificato
    ok = True    # ok=False se anche un solo layer non e' stato raggiunto (host SITAP intermittente)
    for name, layer in layers.items():
        qs = {'service': 'wfs', 'version': '2.0.0', 'request': 'GetFeature',
              'typeNames': 'sitap_ws_clone:'+layer, 'outputFormat': 'application/json',
              'srsName': 'EPSG:4326', 'count': '400', 'bbox': bbox}
        try:
            feats = json_valido(get(SITAP+'?'+urllib.parse.urlencode(qs)),
                                'features', f'SITAP {name}')['features']
        except Exception as e:
            # None = NON verificato. Include ora anche i semi-guasti (200+errore) e i
            # troncamenti (count=400 con numberMatched piu' alto): prima passavano per "pulito".
            out[name] = None; ok = False; print(f'  ! SITAP {name}: {e}'); continue
        geoms = []
        for ft in feats:
            g = ft.get('geometry') or {}
            t = g.get('type', '')
            try:
                if t in ('Polygon', 'MultiPolygon'):
                    geoms.append(shape({'type': t, 'coordinates': _proj_coords(g['coordinates'], to_xy, t)}))
                elif t in ('LineString', 'MultiLineString'):
                    ls = shape({'type': t, 'coordinates': _proj_coords(g['coordinates'], to_xy, t)})
                    geoms.append(ls.buffer(28.0))    # tratturo ~55 m -> semilarghezza 28 m
            except Exception:
                pass
        out[name] = unary_union(geoms) if geoms else GeometryCollection()   # vuoto = verificato PULITO
    return out, ok

def _proj_coords(coords, to_xy, gtype):
    def pt(c):
        a, b = c[0], c[1]
        lat, lon = (a, b) if (40 <= a <= 43 and 13 <= b <= 16) else (b, a)
        return list(to_xy(lat, lon))
    if gtype in ('Polygon', 'MultiLineString'):
        return [[pt(c) for c in ring] for ring in coords]
    if gtype == 'MultiPolygon':
        return [[[pt(c) for c in ring] for ring in poly] for poly in coords]
    return [pt(c) for c in coords]   # LineString

# Interruttore di processo: un host morto non va interrogato dodici volte.
# Si rialza solo riavviando (il tool gira a comando, non e' un servizio).
# Interruttore per IdroGEO: (motivo, istante di scatto). NON e' permanente.
# ⚠️ 12/08/2026: lo era, e questo lo rendeva pericoloso quanto il problema che
# risolveva. Il 12/08 `idrogeo.isprambiente.it` non ha risolto per qualche minuto
# e poi ha ripreso a rispondere in 2 secondi: con un interruttore permanente,
# un blip di DNS all'inizio di una scansione avrebbe marcato NON VERIFICATE le
# frane di TUTTE le particelle per il resto del processo — e nessuno se ne
# sarebbe accorto, perche' "non verificato" e' un esito legittimo.
# Ora scatta per PAUSA_IDROGEO_S e poi si concede una nuova prova: si tiene il
# beneficio (non pagare 4 layer x 3 tentativi x ~11 s per ogni blocco quando il
# servizio e' davvero morto) senza il danno.
_IDROGEO_GIU = None
PAUSA_IDROGEO_S = 300


def reset_interruttore_pai():
    """Azzera l'interruttore. Serve ai test e a chi vuole forzare una riprova."""
    global _IDROGEO_GIU
    _IDROGEO_GIU = None


def stato_interruttore_pai():
    """(motivo, secondi_da_quando_e_scattato) oppure None."""
    if not _IDROGEO_GIU:
        return None
    return _IDROGEO_GIU[0], round(time.time() - _IDROGEO_GIU[1], 1)


def _e_di_rete(e):
    """Un guasto di trasporto (host giu') vs una risposta sbagliata del servizio.

    Solo il primo giustifica l'interruttore: se il server risponde ma il layer e'
    cambiato nome, gli altri layer vanno provati lo stesso.
    """
    return isinstance(e, (OSError, urllib.error.URLError)) or \
        type(e).__name__ in ('RemoteDisconnected', 'IncompleteRead', 'timeout',
                             'TimeoutError', 'ConnectionError')


def pai(parcels, to_xy, margine=0.01):
    """IdroGEO ISPRA -> ({classe: geometria}, {livello: geometria}, ok).

    Il rischio frana e idraulico era l'unico vincolo BLOCCANTE che questo percorso
    non guardava affatto: `engine.score_parcel` classifica P3/P4 come blocker da
    sempre, ma nessuno riempiva i campi, e `blocco.pipeline()` costruiva blocchi
    senza sapere se stavano su una frana (audit 08/08/2026). Lo scanner lo
    interrogava, ma con i poligoni mal proiettati — stesso effetto pratico.

    ⚠ `srsName` NON e' opzionale: il bbox in `urn:...EPSG::4326` dice al server in
    che sistema legge la richiesta, non in quale deve rispondere. Senza, IdroGEO
    risponde nel CRS nativo del layer (EPSG:3857) e i poligoni finiscono a milioni
    di km dai terreni: nessuna intersezione, mai, e ogni particella esce pulita.

    Classi `cod_per_it` (validate il 13/07/2026 contro le tavole E-phowi e le
    statistiche comunali ISPRA): 0=AA aree di attenzione · 1=P1 moderata ·
    2=P2 media · 3=P3 elevata · 4=P4 molto elevata. **AA copre meta' del Sannio e
    NON e' un vincolo operativo**: contarlo come tale bocciava mezza provincia.
    """
    bmin_lat, bmin_lon, bmax_lat, bmax_lon = _bbox_of(parcels, margine)
    bbox = f'{bmin_lat},{bmin_lon},{bmax_lat},{bmax_lon},urn:ogc:def:crs:EPSG::4326'

    def scarica(layer, tentativi=3, pausa=4.0):
        """IdroGEO chiude la connessione senza rispondere quando lo si interroga
        troppo spesso (osservato l'08/08/2026: ~11 s e poi RemoteDisconnected, su
        qualunque bbox, anche su query che avevano appena funzionato). Non e' un
        errore di richiesta: e' una strozzatura, e passa da sola. Un ritentativo
        con pausa evita di dichiarare "non verificato" un layer che c'e'."""
        p = {'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature',
             'typeNames': layer, 'outputFormat': 'application/json',
             'count': '2000', 'srsName': 'EPSG:4326', 'bbox': bbox}
        u = EP['idrogeo'] + '?' + urllib.parse.urlencode(p)
        ultimo = None
        for k in range(tentativi):
            try:
                return json_valido(get(u), 'features', layer)
            except Exception as e:
                ultimo = e
                if k < tentativi - 1:
                    time.sleep(pausa * (k + 1))
        raise ultimo

    frane, idro = {}, {}
    risposte, errori = 0, []
    global _IDROGEO_GIU
    if _IDROGEO_GIU:
        motivo, quando = _IDROGEO_GIU
        eta = time.time() - quando
        if eta < PAUSA_IDROGEO_S:
            print(f'  ! PAI: IdroGEO risultato irraggiungibile {eta:.0f}s fa ({motivo}) '
                  f'-> frane/idraulica NON verificate; si riprova fra '
                  f'{PAUSA_IDROGEO_S - eta:.0f}s')
            return {}, {}, False
        print(f'  · PAI: sono passati {eta:.0f}s dall ultimo guasto ({motivo}): riprovo')
        _IDROGEO_GIU = None
    try:
        d = scarica('idrogeo:pericolosita_frane')
        risposte += 1
        for ft in d.get('features', []):
            c = (ft.get('properties') or {}).get('cod_per_it')
            g = _geom_4326(ft.get('geometry'), to_xy)
            if g is not None and c is not None:
                frane.setdefault(int(c), []).append(g)
    except Exception as e:
        errori.append(f'frane: {str(e)[:60]}')
        if _e_di_rete(e):
            _IDROGEO_GIU = (f'{type(e).__name__} sul layer frane', time.time())
            print('  ! PAI IdroGEO IRRAGGIUNGIBILE (' + errori[0] +
                  ') -> frane/idraulica NON verificate: il verdetto lo dichiarera\'')
            return {}, {}, False
    for lvl, lay in ((1, 'p1'), (2, 'p2'), (3, 'p3')):
        try:
            d = scarica('idrogeo:pericolosita_idraulica_' + lay)
            risposte += 1
            for ft in d.get('features', []):
                g = _geom_4326(ft.get('geometry'), to_xy)
                if g is not None:
                    idro.setdefault(lvl, []).append(g)
        except Exception as e:
            errori.append(f'idraulica {lay}: {str(e)[:60]}')

    # Basta che UNO dei quattro layer non risponda perche' il quadro sia parziale:
    # la classe mancante potrebbe essere proprio quella che blocca. Meglio dichiarare
    # "non verificato" che dire "nessuna frana" avendo letto tre layer su quattro.
    ok = risposte == 4
    if not ok:
        print('  ! PAI IdroGEO incompleto (' + '; '.join(errori[:2]) +
              ') -> frane/idraulica NON verificate: il verdetto lo dichiarera\'')
    return ({k: _unione(v) for k, v in frane.items()},
            {k: _unione(v) for k, v in idro.items()}, ok)


def _unione(geoms):
    """Fonde, e se la topologia si ribella tiene comunque i poligoni.

    Perdere la fusione costa qualche millisecondo di intersezione in piu';
    perdere il layer significa dire "nessuna frana" dove ce n'e' una.
    """
    g = [x for x in geoms if x is not None and not x.is_empty]
    if not g:
        return None
    try:
        return unary_union(g)
    except Exception:
        try:
            return unary_union([x.buffer(0) for x in g])
        except Exception:
            return MultiPolygon([p for x in g
                                 for p in (x.geoms if x.geom_type == 'MultiPolygon' else [x])
                                 if p.geom_type == 'Polygon'])


def _geom_4326(gj, to_xy):
    """GeoJSON in gradi -> poligono nel piano metrico locale. None se non e' lat/lon.

    Se il servizio ha risposto in coordinate proiettate, `valida_coordinate` alza e
    qui si scarta la feature invece di piazzarla dall'altra parte del mondo.
    """
    if not gj:
        return None
    try:
        g = shape(gj)
    except Exception:
        return None
    polys = [g] if g.geom_type == 'Polygon' else list(getattr(g, 'geoms', []))
    out = []
    for q in polys:
        if q.geom_type != 'Polygon':
            continue
        try:
            # il GeoJSON e' (lon, lat): latlon() lo riconosce e ALZA se sono metri
            r = Polygon([to_xy(*latlon(x, y)) for x, y in q.exterior.coords])
        except Exception:
            return None
        # I poligoni della mosaicatura PAI arrivano spesso auto-intersecanti (sono
        # unioni di piani di bacino diversi): `unary_union` su una geometria non
        # valida alza TopologyException e fa saltare TUTTO il layer — cioe' il
        # vincolo frane sparirebbe per colpa di un vertice. buffer(0) li ripara.
        if not r.is_valid:
            r = r.buffer(0)
        if not r.is_empty:
            out.append(r)
    if not out:
        return None
    try:
        return unary_union(out)
    except Exception:
        # ultima difesa: si perde la fusione, non i poligoni
        return MultiPolygon([x for x in out if x.geom_type == 'Polygon']) if out else None


def natura2000(parcels, to_xy):
    """EEA -> (zps, sic, ok). SITETYPE: A=ZPS(SPA), B=SIC/ZSC, C=entrambi.

    ⚠ Il terzo valore `ok` esiste per un bug trovato in QA il 16/07 e vale piu' degli altri due.
    Prima la funzione tornava solo (zps, sic) e inghiottiva gli errori di rete con un
    `except: continue`: se l'EEA era giu', TUTTI i layer fallivano, le liste restavano vuote
    e si tornava (None, None) — **indistinguibile da "verificato: fuori da Natura 2000"**.
    A valle diventava il verdetto `CLEAN`. Provato sul campo: con EEA simulato giu', la
    P.142 di Morcone — che e' al 100% dentro la ZPS IT8020015 (CDU comunale, EEA, screening
    E-phowi e ENGIE, tutti concordi) — usciva **'CLEAN', zps=False**.
    Cioe' il tool generava da solo la frase "area libera da vincoli Natura 2000 (verificato)":
    esattamente la falsita' che nel mondo reale e' costata un developer.

    ok=False significa "non lo so", e il chiamante DEVE dichiararlo. Mai dedurre l'assenza
    di un vincolo dall'assenza di una risposta.
    """
    bmin_lat, bmin_lon, bmax_lat, bmax_lon = _bbox_of(parcels, 0.02)
    env = {'xmin': bmin_lon, 'ymin': bmin_lat, 'xmax': bmax_lon, 'ymax': bmax_lat,
           'spatialReference': {'wkid': 4326}}
    zps, sic = [], []
    risposte, errori = 0, []
    for lyr in (0, 1, 2, 3):
        p = {'geometry': json.dumps(env), 'geometryType': 'esriGeometryEnvelope', 'inSR': 4326,
             'outSR': 4326, 'outFields': 'SITECODE,SITETYPE', 'returnGeometry': 'true',
             'spatialRel': 'esriSpatialRelIntersects', 'f': 'json'}
        try:
            # json_valido() distingue "risposta valida" da "200 con dentro un errore o una
            # lista troncata": senza, risposte+=1 scatterebbe anche su un messaggio d'errore.
            d = json_valido(get(f'{EEA}/{lyr}/query?' + urllib.parse.urlencode(p)),
                            'features', f'EEA layer {lyr}')
            risposte += 1
        except Exception as e:
            errori.append(f'layer {lyr}: {str(e)[:60]}')
            continue
        for ft in d.get('features', []):
            st = (ft.get('attributes') or {}).get('SITETYPE', '')
            for ring in ft.get('geometry', {}).get('rings', []):
                try:
                    g = Polygon([to_xy(v[1], v[0]) for v in ring])
                except Exception:
                    continue
                if st in ('A', 'C'): zps.append(g)
                if st in ('B', 'C'): sic.append(g)
    # nessun layer ha risposto -> non sappiamo nulla. NON e' "non c'e' nulla".
    ok = risposte > 0
    if not ok:
        print('  ! EEA Natura 2000 IRRAGGIUNGIBILE (' + '; '.join(errori[:2]) +
              ') -> ZPS/SIC NON verificati: il verdetto lo dichiarera\'')
    return (unary_union(zps) if zps else None, unary_union(sic) if sic else None, ok)

def _geom_particella(p, to_xy):
    """(shapely, modo) per una particella: poligono catastale se c'e', altrimenti il punto.

    ⚠ Con il solo centroide la risposta puo' essere soltanto 0% o 100%: e' il limite che
    rendeva tutte le percentuali 'stime per difetto'. Un habitat protetto che entra da un
    bordo e copre un quarto del terreno non tocca il centroide e per il tool non esisteva —
    ed e' il BLOCKER: la differenza fra 'progetto vietato' e 'progetto fattibile arretrando'.
    """
    anello = p.get('anello')
    if anello:
        try:
            g = Polygon([to_xy(la, lo) for la, lo in anello])
            if not g.is_valid:
                g = g.buffer(0)
            if g.area > 0:
                return g, 'poligono'
        except Exception:
            pass
    return Point(to_xy(p['lat'], p['lon'])), 'centroide'


def _frazioni(geom, modo, candidati):
    """{codice: % della particella su quel codice}. candidati: [(codice, shapely)].

    Col centroide: 0 o 100 (e si ferma al primo che contiene il punto, come prima).
    Col poligono: la frazione vera, e **un terreno puo' stare su piu' habitat insieme** —
    cosa che il centroide, per costruzione, non poteva nemmeno rappresentare.
    """
    out = {}
    if modo == 'centroide':
        for cod, g in candidati:
            try:
                if g.contains(geom):
                    return {cod: 100.0}
            except Exception:
                pass
        return {}
    area = geom.area
    if area <= 0:
        return {}
    for cod, g in candidati:
        try:
            if not geom.intersects(g):
                continue
            pct = 100.0 * geom.intersection(g).area / area
            if pct > 0.05:                      # sotto il mezzo per mille e' rumore di digitalizzazione
                out[cod] = round(out.get(cod, 0.0) + pct, 2)
        except Exception:
            pass
    return out


def habitat_ispra(parcels):
    """Fallback NAZIONALE dove non c'e' la carta regionale: Carta della Natura ISPRA (WFS hb1:habitat).
    Ritorna {id: {'codici': {codice_CORINE: pct}, 'geometria': 'poligono'|'centroide'}} | None.
    ⚠ CORINE != codice Natura2000: e' INDICATIVO, non autorevole
    (serve a non dire 'nessun divieto' quando in realta' non abbiamo controllato nulla)."""
    plist = [dict(id=k, **v) for k, v in parcels.items()]
    a, b, c, d_ = _bbox_of(plist, 0.01)
    qs = {'service': 'wfs', 'version': '2.0.0', 'request': 'GetFeature', 'typeNames': 'hb1:habitat',
          'outputFormat': 'application/json', 'srsName': 'EPSG:4326', 'count': '400',
          'bbox': f'{a},{b},{c},{d_},urn:ogc:def:crs:EPSG::4326'}
    try:
        data = json_valido(get(EP['ispra_habitat_wfs'] + '?' + urllib.parse.urlencode(qs)),
                           'features', 'ISPRA habitat')
    except Exception as e:
        # ⚠ QA 16/07: prima si tornava {} = "nessun habitat trovato" = a valle "nessun divieto".
        # Un servizio caduto non e' un'assenza di vincoli. None = "non lo so".
        print('  ! ISPRA habitat non raggiungibile:', str(e)[:70], '-> habitat NON verificato')
        return None
    ident = lambda lat, lon: (lon, lat)
    geoms = []
    for f in data.get('features', []):
        g = f.get('geometry') or {}
        t = g.get('type', '')
        if t not in ('Polygon', 'MultiPolygon'):
            continue
        try:
            geoms.append(((f.get('properties') or {}).get('codice_corine'),
                          shape({'type': t, 'coordinates': _proj_coords(g['coordinates'], ident, t)})))
        except Exception:
            pass
    # geoms sono in gradi (lon, lat). Va bene per una FRAZIONE: intersezione/totale hanno lo
    # stesso fattore di scala, che quindi si semplifica. (Non andrebbe bene per un'area assoluta.)
    res = {}
    for p in plist:
        geom, modo = _geom_particella(p, ident)
        res[p['id']] = {'codici': _frazioni(geom, modo, geoms), 'geometria': modo}
    return res


def habitat_ban(parcels):
    """Carta Habitat regionale Campania (fonte AUTOREVOLE, codici Natura2000).

    Ritorna {id: {'codici': {codice: pct}, 'geometria': 'poligono'|'centroide'}} | None.
    None = fonte non raggiunta ("non lo so"), MAI {} ("nessun habitat").
    Usa UTM33N. Scarica+cache lo shapefile alla prima esecuzione."""
    zp = cached_file(HAB_URL, Path(HAB_ZIP).name, ttl_giorni=180)   # scarica una volta, poi riusa
    if zp is None:
        # ⚠ QA 16/07: prima {} -> a valle "nessun habitat" -> "nessun divieto". None = "non lo so".
        print('  ! Carta Habitat non scaricabile: check habitat NON eseguito (non verificato)')
        return None
    z = zipfile.ZipFile(zp)
    shp = z.read(HAB_PRE+'Habitat_poligoni.shp'); shx = z.read(HAB_PRE+'Habitat_poligoni.shx')
    dbf = z.read(HAB_PRE+'Habitat_poligoni.dbf')
    hsize = struct.unpack('<H', dbf[8:10])[0]; rsize = struct.unpack('<H', dbf[10:12])[0]
    def codice(i): return dbf[hsize+i*rsize+1: hsize+i*rsize+51].decode('latin1').strip()
    # normalizza dict/lista in {id: particella}
    pdict = parcels if isinstance(parcels, dict) else {p['id']: p for p in parcels}
    # geometria di ogni particella in UTM33 (poligono catastale se c'e', altrimenti il punto)
    geo = {pid: _geom_particella(p, to_utm33) for pid, p in pdict.items()}
    # bbox target: deve coprire i POLIGONI, non solo i centroidi, altrimenti si scartano
    # habitat che toccano un bordo della particella ma non il suo centro (il bug che stiamo chiudendo)
    xs, ys = [], []
    for g, _ in geo.values():
        x0, y0, x1, y1 = g.bounds
        xs += [x0, x1]; ys += [y0, y1]
    TB = (min(xs)-200, min(ys)-200, max(xs)+200, max(ys)+200)
    def hit(b): return not (b[2] < TB[0] or b[0] > TB[2] or b[3] < TB[1] or b[1] > TB[3])
    cand = []
    nshx = (len(shx)-100)//8
    for i in range(nshx):
        off = struct.unpack('>i', shx[100+i*8:100+i*8+4])[0]*2
        if struct.unpack('<i', shp[off+8:off+12])[0] != 5: continue
        b = struct.unpack('<4d', shp[off+12:off+44])
        if any(v != v for v in b) or not hit(b): continue
        p = off+44; npar = struct.unpack('<i', shp[p:p+4])[0]; npts = struct.unpack('<i', shp[p+4:p+8])[0]
        p += 8; parts = list(struct.unpack('<%di' % npar, shp[p:p+4*npar])); p += 4*npar
        pp = struct.unpack('<%dd' % (2*npts), shp[p:p+16*npts]); parts.append(npts)
        rings = [[(pp[2*j], pp[2*j+1]) for j in range(parts[k], parts[k+1])] for k in range(npar)]
        cand.append((codice(i), rings))
    # anelli shapefile -> shapely. Un poligono shapefile ha piu' parti: contorni esterni e
    # buchi, distinti dal verso. La regola e' EVEN-ODD (la stessa del ray casting che c'era
    # prima): la differenza simmetrica la riproduce esattamente, senza dover indovinare
    # l'orientamento di ogni anello.
    poly_cand = []
    for cod, rings in cand:
        g = None
        for r in rings:
            if len(r) < 4:
                continue
            try:
                q = Polygon(r)
                if not q.is_valid:
                    q = q.buffer(0)
                g = q if g is None else g.symmetric_difference(q)
            except Exception:
                pass
        if g is not None and not g.is_empty and g.area > 0:
            poly_cand.append((cod, g))

    res = {}
    for pid, (geom, modo) in geo.items():
        res[pid] = {'codici': _frazioni(geom, modo, poly_cand), 'geometria': modo}
    return res

# ==========================================================================
#  Feasibility
# ==========================================================================
def feasibility(parcels, prov=None):
    """parcels: dict {id:{lat,lon,ha[,tipo]}}. prov: sigla provincia -> determina la COPERTURA
    (Carta Habitat e SITAP sono regionali: fuori copertura NON si controlla e si dichiara).
    Ritorna dict id -> risultato vincoli+verdetto."""
    # SEMPRE copertura(): gestisce gia' prov None/vuota/ignota (regione=None -> sitap=False, layer=[]).
    # Un fallback scritto a mano qui ometteva chiavi (sitap_layer/habitat_regionale) -> KeyError.
    # Senza provincia non sappiamo in che regione siamo: si resta conservativi, non si assume copertura.
    cov = copertura(prov)
    if prov and not cov['habitat']:
        print(f"  ! Carta Habitat non disponibile per {cov['regione'] or prov}: check habitat NON eseguito")
    if prov and not cov['sitap']:
        print(f"  ! layer SITAP non mappati per {cov['regione'] or prov}: paesaggio/usi civici NON verificati")
    plist = [dict(id=k, **v) for k, v in parcels.items()]
    lat0 = sum(p['lat'] for p in plist)/len(plist)
    MLAT, MLON = m_per_deg(lat0)
    def to_xy(lat, lon): return (lon*MLON, lat*MLAT)

    print('N2K (EEA): scarico confini ZPS/SIC...')
    zps_u, sic_u, n2k_ok = natura2000(plist, to_xy)
    print('PAI (IdroGEO ISPRA): frane + idraulica...')
    pai_fr_u, pai_idr_u, pai_ok = pai(plist, to_xy)
    if cov['sitap']:
        print(f"SITAP {cov['regione']}: {len(cov['sitap_layer'])} layer disponibili"
              + (f" (mancanti qui: {', '.join(cov['sitap_mancanti'])})" if cov['sitap_mancanti'] else ''))
        pae, sitap_ok = sitap_paesaggio(plist, to_xy, regione=cov['regione'])
        if not sitap_ok:
            print('  ! SITAP incompleto (host intermittente): usi civici/paesaggio DA VERIFICARE, non assumere "pulito"')
    else:
        pae, sitap_ok = {k: None for k in CHIAVI_SITAP}, False   # fuori copertura: NON verificato
    if cov['habitat_regionale']:
        print('Habitat: overlay Carta Habitat REGIONALE (codici Natura2000)...')
        hab = habitat_ban(parcels)
    else:
        print(f"Habitat: carta regionale assente per {cov['regione'] or 'questa regione'} "
              '-> fallback ISPRA CORINE (indicativo)...')
        hab = habitat_ispra(parcels)

    out = {}
    for p in plist:
        pt = Point(to_xy(p['lat'], p['lon']))
        # ── geometria: poligono catastale se c'e', altrimenti il centroide ────────────
        # Il centroide risponde "il centro e' dentro?"; il poligono risponde "QUANTA
        # superficie e' dentro?". Un vincolo che entra da un bordo e copre un quarto del
        # terreno non tocca il centroide: per il tool non esisteva. Da qui le percentuali
        # "per difetto" di tutti i numeri precedenti (incluso il "40% nel corridoio" di Morcone).
        anello = p.get('anello')
        geom, modo = pt, 'centroide'
        if anello:
            try:
                g = Polygon([to_xy(la, lo) for la, lo in anello])
                if not g.is_valid:
                    g = g.buffer(0)
                if g.area > 0:
                    geom, modo = g, 'poligono'
            except Exception:
                pass                    # geometria sporca: si ripiega sul centroide, dichiarato

        def frazione(u):
            """% della particella dentro l'union u. None se u non e' verificata.
            Col centroide la risposta puo' essere solo 0 o 100: e' il limite, non una misura."""
            if u is None:
                return None
            try:
                if modo == 'centroide':
                    return 100.0 if u.contains(geom) else 0.0
                if not geom.intersects(u):
                    return 0.0
                return round(100.0 * geom.intersection(u).area / geom.area, 1)
            except Exception:
                return None

        r = {'ha': p['ha'], 'tipo': p.get('tipo'), 'geometria': modo}
        if modo == 'poligono':
            r['ha_geometrico'] = round(geom.area / 10000, 4)
        # None = "non verificato", non "assente". Se l'EEA non ha risposto NON si puo' dire
        # che il terreno e' fuori dalla ZPS: e' esattamente il bug del 16/07.
        r['zps_pct'] = frazione(zps_u) if n2k_ok else None
        r['sic_pct'] = frazione(sic_u) if n2k_ok else None
        r['zps'] = (r['zps_pct'] > 0) if r['zps_pct'] is not None else None
        r['sic'] = (r['sic_pct'] > 0) if r['sic_pct'] is not None else None
        r['n2k_ok'] = n2k_ok

        # ── PAI: quanto della particella sta in ciascuna classe ───────────────────────
        # La percentuale conta piu' del si'/no, come per l'habitat: un lembo di P3 sul
        # bordo si arretra, un P3 sul 60% del fondo e' un altro progetto. Col centroide
        # la distinzione non esisteva (0 o 100), col poligono si'.
        if pai_ok:
            fr_pct = {c: frazione(g) for c, g in pai_fr_u.items()}
            idr_pct = {l: frazione(g) for l, g in pai_idr_u.items()}
            r['pai_frana_pct'] = {c: v for c, v in fr_pct.items() if v}
            r['pai_idraulica_pct'] = {l: v for l, v in idr_pct.items() if v}
            # classe massima effettivamente presente sulla particella; -1/0 = "controllato,
            # nulla qui" (e' la convenzione che engine.score_parcel gia' conosce)
            r['pai_fr'] = max([c for c, v in fr_pct.items() if v], default=-1)
            r['pai_idr'] = max([l for l, v in idr_pct.items() if v], default=0)
        else:
            r['pai_frana_pct'] = r['pai_idraulica_pct'] = None
            r['pai_fr'] = r['pai_idr'] = None      # None = NON controllato
        r['pai_ok'] = pai_ok
        r['pai_incompleto'] = not pai_ok
        # AA (classe 0) e P1 non sono vincoli operativi: AA copre meta' del Sannio e
        # sulle tavole E-phowi la stessa particella risulta senza vincoli.
        r['pai_blocker'] = (None if not pai_ok else
                            bool((r['pai_fr'] or -1) >= 3 or (r['pai_idr'] or 0) >= 2))

        h = hab.get(p['id']) if hab is not None else None
        r['habitat_ok'] = hab is not None            # False = fonte habitat non raggiunta
        r['habitat_fonte'] = cov['habitat_fonte']
        r['habitat_autorevole'] = bool(cov['habitat_regionale'])
        # i codici del divieto dipendono dalla fonte: Natura2000 (carta regionale) vs CORINE (ISPRA)
        _ban = BAN_CODES if cov['habitat_regionale'] else CORINE_BAN
        if h is None:
            r['habitat'] = None; r['habitat_pct'] = None
            r['habitat_ban'] = None; r['habitat_ban_pct'] = None
            r['habitat_geometria'] = None
        else:
            codici = h['codici']
            r['habitat_pct'] = codici                       # {codice: % della particella}
            # codice dominante: quello che copre piu' superficie (col centroide ce n'e' uno solo)
            r['habitat'] = max(codici, key=codici.get) if codici else None
            r['habitat_geometria'] = h['geometria']
            # ⚠ La percentuale conta piu' del si'/no: il divieto della DGR 617/2024 riguarda
            # l'habitat, non la particella. Un 3% su 6220 non uccide il progetto — si arretra.
            # Col centroide questa distinzione non era nemmeno rappresentabile (0 o 100).
            r['habitat_ban_pct'] = round(sum(pct for c, pct in codici.items()
                                             if any(str(c).startswith(b) for b in _ban)), 2)
            r['habitat_ban'] = r['habitat_ban_pct'] > 0
        for name in SITAP_LAYERS:
            g = pae.get(name)
            pct = frazione(g)                      # None = non verificato
            r[name + '_pct'] = pct
            r[name] = (pct > 0) if pct is not None else None
        r['sitap_ok'] = sitap_ok
        r['copertura'] = {'regione': cov.get('regione'), 'habitat': cov['habitat'], 'sitap': cov['sitap']}
        # ── VERDETTO ──────────────────────────────────────────────────────────────────
        # Regola: **la parola CLEAN non puo' comparire se una fonte non ha risposto.**
        # I vincoli TROVATI vincono sempre (un divieto e' un divieto anche se il resto e'
        # incerto); solo DOPO, se non c'e' nessun vincolo, ci si chiede se avevamo davvero
        # gli occhi aperti. L'ordine conta: prima si guarda cosa si e' visto, poi cosa no.
        if r['habitat_ban'] is True:
            v = 'BLOCK_HABITAT'
        elif r['pai_blocker'] is True:
            det = []
            if (r['pai_fr'] or -1) >= 3:
                det.append(f"frana P{r['pai_fr']} {max(r['pai_frana_pct'].values()):.0f}%")
            if (r['pai_idr'] or 0) >= 2:
                det.append(f"idraulica P{r['pai_idr']} {max(r['pai_idraulica_pct'].values()):.0f}%")
            v = 'BLOCK_PAI(' + ', '.join(det) + ')'
        elif r['usi_civici'] is True:
            v = 'TITOLO(usi civici)'
        elif r['zps'] or r['sic']:
            v = 'VINCA' + ('+SIC' if r['sic'] else '')
        elif any(r.get(k) for k in ('lago_300m', 'fiume_150m', 'bosco_142g', 'tratturo', 'archeo_area', 'art136')):
            v = 'PAESAGGIO'
        else:
            # nessun vincolo trovato: ma li abbiamo cercati tutti davvero?
            ciechi = []
            if not n2k_ok:
                ciechi.append('Natura 2000 (EEA non raggiunta)')
            if not pai_ok:
                ciechi.append('PAI frane/idraulica (IdroGEO non raggiunto)')
            if r['habitat_ok'] is False:
                ciechi.append('habitat (fonte non raggiunta)')
            if not cov['sitap']:
                ciechi.append(f"SITAP assente per {cov['regione'] or 'questa regione'}")
            elif not sitap_ok:
                ciechi.append('SITAP non raggiunto')
            if ciechi:
                # MAI 'CLEAN' qui: senza queste fonti non sappiamo nulla di decisivo.
                v = 'NON VERIFICATO: ' + ' + '.join(ciechi)
            elif cov.get('sitap_mancanti') or not cov['habitat_regionale']:
                v = 'CLEAN (verifica PARZIALE)'   # tutte le fonti hanno risposto, ma non coprono tutto
            else:
                v = 'CLEAN'
        r['verdetto'] = v
        out[p['id']] = r
    return out

def to_score_fields(vinc):
    """Mappa un risultato vincoli (una particella) sui campi letti da engine.score_parcel.
    Le fasce lago/fiume UFFICIALI (SITAP) sovrascrivono quelle OSM della Fase 3."""
    # habitat_ban e in_sic NON hanno default False: sono gli unici due campi con
    # una logica a TRE stati a valle (recommend distingue vietato / pulito / non
    # verificato). `feasibility` mette gia' None quando la fonte non risponde, e
    # quel None passa; ma un dict costruito a mano — dall'API, da uno scan, da un
    # JSON scritto a mano — non ha la chiave, e con `default=False` si trasformava
    # in "nessun divieto verificato". Gli altri campi restano a False perche' a
    # valle non c'e' nessuno che distingua il terzo stato: metterli a None
    # sarebbe piu' onesto nel dato e identico nell'effetto, cioe' rumore.
    f = {
        'habitat_ban': vinc.get('habitat_ban'),
        'habitat': vinc.get('habitat'),
        'in_sic': vinc.get('sic'),
        'usi_civici': vinc.get('usi_civici', False),
        'bosco_142g': vinc.get('bosco_142g', False),
        'tratturo': vinc.get('tratturo', False) or vinc.get('archeo_area', False),
        'art136': vinc.get('art136', False),
    }
    if vinc.get('lago_300m'): f['fascia_lago'] = True
    if vinc.get('fiume_150m'): f['fascia_fiume'] = True
    if vinc.get('sitap_ok') is False:
        f['paesaggio_incompleto'] = True
    # PAI: `-1`/`0` = controllato e pulito, `None` = non controllato. La differenza la
    # conosce gia' engine.score_parcel; qui va solo passata senza appiattirla.
    f['pai_fr'] = vinc.get('pai_fr', -1)
    f['pai_idr'] = vinc.get('pai_idr', 0)
    if vinc.get('pai_ok') is False:
        f['pai_incompleto'] = True
    # se il modulo ha rilevato la ZPS e il chiamante non la calcola gia', la fornisco
    if vinc.get('zps') and 'zps_pct' not in f:
        f['zps_pct'] = 100.0; f['zps_border_m'] = -1
    return f


def score_with_vincoli(parcels, tech='agriPV'):
    """Comodita': feasibility() + merge su ogni particella + engine.score_parcel.
    parcels: {id:{lat,lon,ha[,slope,...]}}. Ritorna {id: {..vincoli.., score, classe, voto, flags}}."""
    from landscout.engine import score_parcel, voto_10
    res = feasibility(parcels)
    out = {}
    for pid, vinc in res.items():
        base = dict(parcels[pid])                 # ha, slope, ecc. gia' presenti
        base.setdefault('zps_pct', 0.0); base.setdefault('zps_border_m', 9e9)
        base.update(to_score_fields(vinc))
        score, classe, flags = score_parcel(base, tech)
        out[pid] = {**vinc, 'score': score, 'classe': classe,
                    'voto': voto_10(score, classe), 'flags': flags}
    return out


def print_report(res):
    order = {'BLOCK_HABITAT': 0, 'TITOLO(usi civici)': 1, 'VINCA+SIC': 2, 'VINCA': 3, 'PAESAGGIO': 4, 'CLEAN': 5}
    rows = sorted(res.items(), key=lambda kv: (order.get(kv[1]['verdetto'], 9), kv[0]))
    print('\n' + '='*90)
    print('  VINCOLI / FATTIBILITA\' per particella')
    print('='*90)
    print(f'{"particella":<14}{"ha":>6}  {"verdetto":<18} dettaglio vincoli')
    print('-'*90)
    for pid, r in rows:
        det = []
        if r['habitat']: det.append('hab '+r['habitat'])
        for k, lab in (('zps', 'ZPS'), ('sic', 'SIC'), ('usi_civici', 'USI CIVICI'),
                       ('lago_300m', 'lago300'), ('fiume_150m', 'fiume150'), ('bosco_142g', 'bosco'),
                       ('tratturo', 'tratturo'), ('archeo_area', 'archeo'), ('art136', 'art136')):
            if r.get(k): det.append(lab)
        print(f'{pid:<14}{r["ha"]:>6.2f}  {r["verdetto"]:<18} {", ".join(det) or "-"}')
    # sintesi
    from collections import Counter
    c = Counter(r['verdetto'] for r in res.values())
    tot = sum(r['ha'] for r in res.values())
    ban = sum(r['ha'] for r in res.values() if r['verdetto'] == 'BLOCK_HABITAT')
    uc = sum(r['ha'] for r in res.values() if 'usi civici' in r['verdetto'])
    print('-'*90)
    print(f'  {len(res)} particelle, {tot:.2f} ha | verdetti: {dict(c)}')
    print(f'  Su habitat vietato 6220/6210: {ban:.2f} ha | usi civici: {uc:.2f} ha')
    print('='*90)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--parcels', help='JSON {id:{lat,lon,ha[,tipo]}}')
    ap.add_argument('--out', help='salva risultati JSON')
    A = ap.parse_args()
    if not A.parcels:
        print('Uso: python -m landscout.vincoli --parcels <file.json>'); return
    parcels = json.load(open(A.parcels, encoding='utf-8'))
    res = feasibility(parcels)
    print_report(res)
    if A.out:
        json.dump(res, open(A.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('salvato:', A.out)

if __name__ == '__main__':
    main()
