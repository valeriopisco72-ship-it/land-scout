"""land-scout — CATASTO (v0.1, 16/07/2026): il poligono vero della particella.

## Perche' esiste

Fino a oggi tutti gli overlay (ZPS, SIC, habitat, paesaggio) campionavano un **punto solo**:
il centroide. Conseguenza, dichiarata piu' volte ma mai risolta: **un vincolo che morde la
particella da un bordo e' invisibile**. Il test lo ha quantificato — un vincolo che copre
**un quarto** della superficie, entrando da un lato, non tocca il centroide e per il tool
non esiste. Tutte le percentuali erano quindi **stime per difetto**, e lo erano anche i
numeri portati in trattativa (i vincoli su Morcone: "40% della superficie nel corridoio"
significava "almeno il 40%").

Qui si prende la geometria vera dal WFS INSPIRE dell'Agenzia delle Entrate, e si passa da
"il centro e' dentro?" a "**quanta** superficie e' dentro?".

Nota: il **portale** dell'AdE e' bloccato da Akamai da questo ambiente (403 ovunque, vedi
vam.py), ma il **WFS cartografico e' un host diverso e risponde**. Verificato 16/07:
bbox 0,004° attorno alla P.142 di Morcone -> 111 particelle con geometria.

## Il sistema di riferimento

L'AdE serve EPSG:6706 (ETRS89 geografiche) con ordine **lat, lon** — non lon, lat. Sbagliarlo
non da' errore: sposta il terreno in mezzo al mare, e gli overlay tornerebbero tutti "pulito".
E' la stessa trappola dei falsi-pulito: un errore silenzioso che assomiglia a un dato.

CLI:
  .venv/Scripts/python -m landscout.catasto --lat 42.33405 --lon 13.71036
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

from landscout.cache import JsonCache
from landscout.config import EP, UA, TIMEOUT, valida_coordinate

# una particella e': IT.AGE.PLA.<comune>_<foglio>00.<numero>
_RE_ID = re.compile(r'IT\.AGE\.PLA\.([A-Z]\d{3})_0*(\d+)00\.(.+)$')
_RE_GID = re.compile(r'gml:id="CadastralParcel\.(IT\.AGE\.PLA\.[^"]+)"')
_RE_POS = re.compile(r'<gml:posList[^>]*>([\d\.\s\-]+)</gml:posList>')


class CatastoNonDisponibile(Exception):
    """Il catasto non ha risposto o non ha la particella. Chi chiama DEVE ripiegare
    sul centroide **e dichiararlo** — mai fingere di avere la geometria."""


def _tile(bbox, timeout=None):
    """bbox = (lat_min, lon_min, lat_max, lon_max) -> {id_particella: [(lat,lon), ...]}"""
    p = {'SERVICE': 'WFS', 'VERSION': '2.0.0', 'REQUEST': 'GetFeature',
         'TYPENAMES': 'CP:CadastralParcel', 'SRSNAME': 'urn:ogc:def:crs:EPSG::6706',
         'BBOX': f'{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},urn:ogc:def:crs:EPSG::6706',
         'COUNT': '500', 'STARTINDEX': '0'}
    url = EP['catasto'] + '?' + urllib.parse.urlencode(p)
    try:
        d = urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                   timeout=timeout or TIMEOUT).read().decode('utf-8', 'replace')
    except Exception as e:
        raise CatastoNonDisponibile(f'WFS catasto non raggiungibile: {str(e)[:60]}')
    if 'ExceptionReport' in d or 'ows:Exception' in d:
        raise CatastoNonDisponibile('WFS catasto: ExceptionReport (query rifiutata)')
    membri = d.split('<wfs:member>')[1:]
    if not membri and 'CadastralParcel' not in d:
        raise CatastoNonDisponibile('WFS catasto: risposta senza particelle (forma inattesa)')
    # ⚠ COUNT=500: se il tile e' pieno la lista e' TRONCATA e mancherebbero particelle.
    # Stessa famiglia dei troncamenti silenziosi di EEA/SITAP: meglio saperlo.
    if len(membri) >= 500:
        raise CatastoNonDisponibile('WFS catasto: 500 particelle = tile SATURO, lista troncata '
                                    '-> restringere la bbox')
    out = {}
    for m in membri:
        gid, pl = _RE_GID.search(m), _RE_POS.findall(m)
        if not (gid and pl):
            continue
        n = pl[0].split()                      # EPSG:6706 -> ordine lat, lon
        anello = [(float(n[i]), float(n[i+1])) for i in range(0, len(n)-1, 2)]
        if len(anello) >= 4:
            out[gid.group(1)] = anello
    return out


def _poligono(anello, to_xy):
    from shapely.geometry import Polygon
    g = Polygon([to_xy(la, lo) for la, lo in anello])
    if not g.is_valid:
        g = g.buffer(0)                        # ripara auto-intersezioni del catasto
    return g


def particella_del_punto(lat, lon, cache=None, raggio_gradi=0.0015):
    """Il poligono catastale che CONTIENE (lat, lon).

    Ritorna {'id', 'comune', 'foglio', 'particella', 'anello': [(lat,lon)...], 'ha'}.
    Alza CatastoNonDisponibile se il servizio non risponde o nessuna particella contiene
    il punto (succede su strade, acque, o se il punto e' fuori dal catasto mappato).
    """
    from shapely.geometry import Point
    lat, lon = valida_coordinate(lat, lon)
    cache = cache or JsonCache('catasto', ttl_giorni=365)   # le mappe catastali cambiano di rado
    key = f'{lat:.5f}|{lon:.5f}'
    v = cache.get(key, '__miss__')
    if v != '__miss__' and v:
        return v

    b = (lat - raggio_gradi, lon - raggio_gradi, lat + raggio_gradi, lon + raggio_gradi)
    tile = _tile(b)
    # proiezione locale piana: bastano metri relativi, il tile e' piccolo
    import math
    MY, MX = 111_132.0, 111_320.0 * math.cos(math.radians(lat))
    to_xy = lambda la, lo: (lo * MX, la * MY)
    pt = Point(to_xy(lat, lon))

    for pid, anello in tile.items():
        m = _RE_ID.match(pid)
        if not m or not m.group(3)[0].isdigit():
            continue                            # scarta poligoni STRADA/ACQUA/etichette
        g = _poligono(anello, to_xy)
        if g.contains(pt):
            out = {'id': pid, 'comune': m.group(1), 'foglio': str(int(m.group(2))),
                   'particella': m.group(3), 'anello': anello, 'ha': round(g.area / 10000, 4)}
            cache.set(key, out)                 # in cache SOLO i successi
            return out
    raise CatastoNonDisponibile(
        f'nessuna particella catastale contiene il punto ({lat}, {lon}): '
        f'{len(tile)} particelle nel raggio, ma nessuna lo racchiude '
        '(punto su strada/acqua, o fuori dal catasto mappato)')


_RE_NOME = re.compile(r'^(\d+)[_/-](\d+[A-Za-z]?)$')     # '70_142', '69/103', '83-14'


def verifica_identita(pid, c):
    """Se l'id ha la forma <foglio>_<particella>, controlla che il punto cada DAVVERO li'.

    ⚠ Vale piu' di quanto sembra. Sui 35 punti di famiglia del vault questo controllo ha
    trovato **2 coordinate sbagliate** (70_825 -> il punto cade su P.534; 83_285 -> su P.605):
    per quelle due, ogni verifica di vincolo era stata fatta **sul terreno di qualcun altro**.
    Un controllo basato solo sul rapporto fra superfici ne pescava una sola (0,373/0,278 = 1,34,
    sotto ogni soglia ragionevole): e' l'IDENTITA' che va confrontata, non l'area.
    """
    m = _RE_NOME.match(str(pid).strip())
    if not m:
        return None                            # id libero: niente da confrontare
    fg, pl = m.group(1), m.group(2)
    if c['foglio'] == fg and str(c['particella']) == pl:
        return None
    return (f"{pid}: il punto NON cade sulla particella {fg}/{pl} ma su "
            f"{c['comune']} Fg.{c['foglio']} P.{c['particella']} ({c['ha']:.3f} ha) — "
            "coordinate sbagliate: i vincoli verrebbero verificati sul terreno sbagliato")


def arricchisci(parcels, silenzioso=False):
    """Aggiunge 'anello' (e 'ha' catastale) a ogni particella che ne e' priva.

    Ritorna (parcels, note[]). NON alza: se il catasto manca per una particella, quella
    resta senza anello e chi chiama ripieghera' sul centroide **dichiarandolo**.
    """
    note = []
    for pid, p in parcels.items():
        if p.get('anello'):
            continue
        try:
            c = particella_del_punto(p['lat'], p['lon'])
            p['anello'] = c['anello']
            p['catasto_id'] = c['id']
            p['ha_catasto'] = c['ha']
            # (1) l'id dice una particella diversa da quella su cui cade il punto?
            n = verifica_identita(pid, c)
            if n:
                note.append(n)
                p['identita_sospetta'] = True
            # (2) superficie dichiarata molto diversa da quella catastale
            elif p.get('ha') and c['ha'] > 0:
                r = p['ha'] / c['ha']
                if r > 1.5 or r < 0.66:
                    note.append(f"{pid}: dichiarati {p['ha']:.2f} ha ma la particella catastale "
                                f"({c['comune']} Fg.{c['foglio']} P.{c['particella']}) ne misura "
                                f"{c['ha']:.2f} — controlla il punto o la superficie")
        except CatastoNonDisponibile as e:
            note.append(f'{pid}: geometria catastale non disponibile ({str(e)[:70]}) '
                        '-> overlay sul centroide (stima per difetto)')
            if not silenzioso:
                print(f'  ! catasto {pid}: {str(e)[:70]}')
    return parcels, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lat', type=float, required=True)
    ap.add_argument('--lon', type=float, required=True)
    A = ap.parse_args()
    try:
        c = particella_del_punto(A.lat, A.lon)
    except CatastoNonDisponibile as e:
        sys.exit(f'✗ {e}')
    print(f"{c['comune']} Foglio {c['foglio']} Particella {c['particella']}")
    print(f"  superficie catastale: {c['ha']} ha · {len(c['anello'])} vertici")
    print(f"  id: {c['id']}")


if __name__ == '__main__':
    main()
