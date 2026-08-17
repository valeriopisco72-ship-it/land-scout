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
