# -*- coding: utf-8 -*-
"""Export GeoJSON del blocco: le geometrie escono dal tool e si aprono altrove.

Perche' serve
-------------
Lo screening satellitare (`satcheck`) disegna il perimetro sopra UN solo livello,
la foto Esri. I vincoli invece li interroghiamo come dato — SITAP, PAI, ZPS,
Copernicus, fabbricati AdE — e otteniamo un si'/no che nessuno vede mai
disegnato sulla mappa.

E' esattamente li' che nasce l'errore ricorrente del tool: *assenza del dato
letta come terreno pulito*. Ferrovia-ponte, bosco non mappato, SITAP giu':
tutti trovati a vista, nessuno trovato dal codice. Un file che si apre in QGIS
o su geojson.io permette di sovrapporre il livello UFFICIALE alla particella e
guardare se la risposta torna. Non sostituisce i controlli: li rende falsificabili.

Convenzioni RFC 7946 rispettate qui
-----------------------------------
- coordinate **[lon, lat]**, non [lat, lon]: il tool internamente usa l'ordine
  opposto, e invertirlo e' l'errore piu' comune di tutta la materia. Sbagliarlo
  non da' errore: sposta i terreni in Somalia.
- anello **chiuso** (primo vertice ripetuto in coda);
- anello esterno in senso **antiorario** (regola della mano destra);
- sempre WGS84: il membro `crs` non si scrive, e' deprecato dal 2016.

Le proprieta' includono i colori `fill`/`stroke` della simplestyle-spec, cosi'
geojson.io colora il blocco senza dover configurare nulla.
"""
import json
import os

# Stessa scala di colori della mappa HTML: verde = gia' di famiglia,
# arancio = da acquisire e utile, giallo = da acquisire ma marginale.
_VERDE, _ARANCIO, _GIALLO = '#1a8a3a', '#ff8a3c', '#ffd27f'

# ~1 cm. Oltre e' rumore che gonfia il file senza aggiungere informazione.
_DEC = 7


def _chiudi(anello):
    """GeoJSON vuole l'anello chiuso; il tool lo tiene aperto."""
    if not anello:
        return anello
    return anello if anello[0] == anello[-1] else anello + [anello[0]]


def _area_con_segno(anello):
    """Shoelace su (lon, lat). Positiva = antiorario."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(anello, anello[1:]):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _antiorario(anello):
    """Anello esterno antiorario, come chiede la regola della mano destra."""
    return anello if _area_con_segno(anello) >= 0 else anello[::-1]


def anello_geojson(poly):
    """Da `poly` interno ([lat, lon], aperto) ad anello GeoJSON ([lon, lat], chiuso, CCW).

    L'inversione lat/lon avviene QUI e solo qui: un punto solo da sbagliare,
    un punto solo da testare.
    """
    if not poly or len(poly) < 3:
        return None
    a = [[round(float(lon), _DEC), round(float(lat), _DEC)] for lat, lon in poly]
    return _antiorario(_chiudi(a))


def _proprieta(p, comune=''):
    det = {k.replace('_pct', ''): round(float(v), 1)
           for k, v in (p.get('detrazioni') or {}).items() if v >= 1}
    ancora = bool(p.get('ancora'))
    netti = float(p.get('netti') or 0)
    colore = _VERDE if ancora else (_ARANCIO if netti >= 1 else _GIALLO)
    # `cat`/`nota` descrivono cose che i numeri non dicono — p.es. una particella
    # da frazionare, dove la stessa geometria compare due volte con destinazioni
    # diverse (porzione offerta e porzione tenuta). Senza questi campi le due
    # meta' diventano indistinguibili sulla mappa.
    cat = p.get('categoria') or p.get('cat')
    nota = p.get('nota')
    pr = {
        'comune': comune,
        'foglio': p.get('fg'),
        'particella': p.get('pla'),
        'ha_catastali': round(float(p.get('ha') or 0), 3),
        'ha_utili': round(netti, 3),
        'gia_di_famiglia': ancora,
        'stato': 'ancora' if ancora else 'da_acquisire',
        'categoria': cat or None,
        'nota': (nota or None) if isinstance(nota, str) else None,
        'detrazioni_pct': det or None,
        # simplestyle-spec: geojson.io e umap la leggono senza configurazione
        'fill': colore,
        'stroke': colore,
        'fill-opacity': 0.45,
        'stroke-width': 2,
    }
    return {k: v for k, v in pr.items() if v is not None}


def feature(p, comune=''):
    """Una particella -> una Feature. `None` se la geometria non e' usabile."""
    anello = anello_geojson(p.get('poly') or p.get('anello') or p.get('ring'))
    if anello is None:
        return None
    return {'type': 'Feature',
            'geometry': {'type': 'Polygon', 'coordinates': [anello]},
            'properties': _proprieta(p, comune)}


def collezione(particelle, comune=''):
    """FeatureCollection + elenco degli scarti.

    Gli scarti tornano SEMPRE al chiamante: una particella senza geometria che
    sparisce in silenzio e' la stessa classe di bug che questo modulo esiste per
    smascherare.
    """
    feats, scartate = [], []
    for p in particelle or []:
        f = feature(p, comune)
        if f is None:
            scartate.append(f"{p.get('fg')}/{p.get('pla')}")
        else:
            feats.append(f)
    return {'type': 'FeatureCollection', 'features': feats}, scartate


# ------------------------------------------------------------------ scan
# Lo scan produceva JSON e CSV: una graduatoria da leggere a mano, senza poterla
# sovrapporre a nulla. Qui ogni particella esce col suo poligono, colorata per
# classe, e con la FORBICE di verifica fra le proprieta': in QGIS si filtra
# "fragile = true" e si vede subito dove il voto alto poggia su una fonte muta.
_COLORE_CLASSE = {'A': '#1a8a3a', 'B': '#7cc242', 'C': '#ff8a3c', 'D': '#c62828'}
_GRIGIO = '#9e9e9e'
# contorno scuro e spesso = voto alto che una verifica mancante puo' far crollare
_FRAGILE = '#212121'


def _proprieta_scan(r):
    fb = r.get('forbice') or {}
    fragile = bool(fb.get('bloccanti_ignoti'))
    colore = _COLORE_CLASSE.get(r.get('classe'), _GRIGIO)
    d_se = r.get('d_se_m')
    pr = {
        'particella': r.get('pla'),
        'foglio': r.get('fg'),
        'comune_catastale': r.get('com'),
        'ha': r.get('ha'),
        'voto': r.get('voto'),
        'classe': r.get('classe'),
        'voto_peggiore': fb.get('voto_peggiore'),
        'voto_migliore': fb.get('voto_migliore'),
        'verifica_prima': fb.get('verifica_prima'),
        'fragile': fragile,
        'n2k_pct': r.get('n2k_pct'),
        'n2k_incompleto': r.get('n2k_incompleto'),
        'pai_fr': r.get('pai_fr'),
        'pai_idr': r.get('pai_idr'),
        'pai_incompleto': r.get('pai_incompleto'),
        'slope': r.get('slope'),
        # la sentinella 9e9 non e' una distanza: in QGIS diventerebbe un numero vero
        'd_se_m': d_se if (d_se is not None and d_se < 9e8) else None,
        'habitat_ban': r.get('habitat_ban'),
        'flags': ' | '.join(r.get('flags') or []) or None,
        'fill': colore,
        'fill-opacity': 0.5,
        'stroke': _FRAGILE if fragile else colore,
        'stroke-width': 4 if fragile else 1,
    }
    # i None restano solo dove SIGNIFICANO qualcosa (non verificato): le chiavi di
    # verifica si tengono anche vuote, il resto no
    tieni = {'voto_peggiore', 'voto_migliore', 'verifica_prima', 'n2k_pct', 'pai_fr',
             'pai_idr', 'habitat_ban', 'slope'}
    return {k: v for k, v in pr.items() if v is not None or k in tieni}


def collezione_scan(righe):
    """Righe dello scan -> (FeatureCollection, scarti 'fg/pla' senza geometria usabile)."""
    feats, scartate = [], []
    for r in righe or []:
        anello = anello_geojson(r.get('poly'))
        if anello is None:
            scartate.append(f"{r.get('fg')}/{r.get('pla')}")
            continue
        feats.append({'type': 'Feature',
                      'geometry': {'type': 'Polygon', 'coordinates': [anello]},
                      'properties': _proprieta_scan(r)})
    return {'type': 'FeatureCollection', 'features': feats}, scartate


def esporta_scan_geojson(righe, out_path, meta=None):
    """Scrive l'esito di uno scan come GeoJSON. Ritorna (percorso, scarti)."""
    fc, scartate = collezione_scan(righe)
    fc['properties'] = dict(meta or {}, n_particelle=len(fc['features']),
                            particelle_senza_geometria=scartate or None,
                            fragili=sum(1 for f in fc['features'] if f['properties']['fragile']))
    d = os.path.dirname(os.path.abspath(out_path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False, separators=(',', ':'))
    return out_path, scartate


def esporta_geojson(blk, out_path, comune=''):
    """Scrive il blocco come GeoJSON. Ritorna (percorso, scarti)."""
    fc, scartate = collezione(blk.get('particelle'), comune)
    fc['properties'] = {
        'titolo': blk.get('titolo'),
        'ha_lordi': blk.get('ha_lordi'),
        'ha_netti': blk.get('ha_netti'),
        'ha_ancore': blk.get('ha_ancore'),
        'ha_acquisti': blk.get('ha_acquisti'),
        'n_particelle': len(fc['features']),
        'particelle_senza_geometria': scartate or None,
    }
    d = os.path.dirname(os.path.abspath(out_path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False, separators=(',', ':'))
    return out_path, scartate
