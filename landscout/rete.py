"""land-scout — modulo RETE (v0.1, 15/07/2026): contesto del nodo di connessione.

PERCHE' ESISTE (e perche' NON e' automatico)
La capacita'/coda di connessione e' il gate n.1 dopo il permitting: un terreno perfetto
su un nodo saturo non vale niente. Ma il dato NON e' accessibile a macchina:
  - Terna **Econnextion** = dashboard **PowerBI** caricata via JS (nessun endpoint nel HTML)
  - **dati.terna.it/api*** -> 302 (login) · Download Center -> richiede **MyTerna/registrazione**
  - **developer.terna.it** espone API con chiavi/segreti, e negli endpoint pubblici
    (Settlement, Misure, Anagrafiche, Plant Master Data) **le code non ci sono**
Scrapare un embed PowerBI sarebbe fragile e scorretto. Quindi: **registro compilato a mano
e DATATO** (`data/raw/rete/nodi.json`), e quando il nodo non c'e' si dichiara "non noto".

Regola (la stessa di tutto il tool): mai spacciare un dato non verificato per verificato.
Prima di questo modulo il contesto nodo era **hardcoded su Morcone** (`pv_queue=False,
bess_queue_mw=699`) ed era il DEFAULT del dossier: con il censimento nazionale avrebbe
detto a un terreno in Puglia "coda FV vuota, 699 MW BESS" — numeri di Morcone. Bug risolto.

CLI:
  .venv/Scripts/python -m landscout.rete --nodo Morcone --prov BN
  .venv/Scripts/python -m landscout.rete --lista
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request
from datetime import date, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
from landscout.config import RAW, UA
from landscout.cache import JsonCache
from landscout.engine import m_per_deg
from shapely.geometry import Point, Polygon, LineString, MultiPoint
from shapely.ops import unary_union

REGISTRO = RAW / 'rete' / 'nodi.json'
MESI_VALIDITA = 6          # oltre, il dato va riverificato (le code cambiano in fretta)
OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter',
            'https://maps.mail.ru/osm/tools/overpass/api/interpreter']


# ==========================================================================
#  DISTANZA dalla rete (OSM) — automatizzabile e nazionale, a differenza delle code
# ==========================================================================
def _overpass(q):
    c = JsonCache('osm_rete', ttl_giorni=90)
    k = str(hash(q))
    hit = c.get(k)
    if hit is not None:
        return hit
    for m in OVERPASS:
        try:
            r = urllib.request.Request(m, data=urllib.parse.urlencode({'data': q}).encode(), headers=UA)
            d = json.loads(urllib.request.urlopen(r, timeout=150).read())
            c.set(k, d)
            return d
        except Exception as e:
            print('  overpass fail:', str(e)[:50]); time.sleep(3)
    return None


def _volt(t):
    """massima tensione (V) dal tag voltage ('150000;20000' -> 150000)."""
    v = [int(x) for x in re.findall(r'\d{4,7}', t.get('voltage', '') or '')]
    return max(v) if v else None


def distanza_rete(punti, margine_deg=(0.055, 0.07)):
    """punti: [(lat,lon), ...]. Ritorna distanze alla SE e alla linea AT piu' vicine.
    NB: la rete si cerca ben oltre il bbox delle particelle (la SE puo' stare a km)."""
    lats = [p[0] for p in punti]; lons = [p[1] for p in punti]
    lat0 = sum(lats) / len(lats)
    MLAT, MLON = m_per_deg(lat0)
    to_xy = lambda la, lo: (lo * MLON, la * MLAT)
    bbw = (f'{min(lats)-margine_deg[0]},{min(lons)-margine_deg[1]},'
           f'{max(lats)+margine_deg[0]},{max(lons)+margine_deg[1]}')
    q = (f'[out:json][timeout:120];(way[power=line]({bbw}); way[power=substation]({bbw}); '
         f'node[power=substation]({bbw}););out geom tags;')
    od = _overpass(q)
    if not od:
        return {'verificato': False, 'nota': 'Overpass non raggiungibile: distanze rete non calcolate'}
    subs, linee = [], []
    for e in od.get('elements', []):
        t = e.get('tags', {})
        if t.get('power') == 'substation':
            if e['type'] == 'node':
                subs.append(Point(to_xy(e['lat'], e['lon'])))
            elif 'geometry' in e and len(e['geometry']) >= 4:
                subs.append(Polygon([to_xy(p['lat'], p['lon']) for p in e['geometry']]))
        elif t.get('power') == 'line' and 'geometry' in e and len(e['geometry']) >= 2:
            v = _volt(t)
            if v and v >= 40000:          # solo alta tensione (>=40 kV): la MT non regge utility-scale
                linee.append((v, LineString([to_xy(p['lat'], p['lon']) for p in e['geometry']])))
    terreno = MultiPoint([Point(to_xy(la, lo)) for la, lo in punti])
    out = {'verificato': True, 'n_se': len(subs), 'n_linee_at': len(linee)}
    out['d_se_m'] = round(unary_union(subs).distance(terreno)) if subs else None
    if linee:
        best = min(linee, key=lambda x: x[1].distance(terreno))
        out['d_linea_m'] = round(best[1].distance(terreno))
        out['linea_kv'] = round(best[0] / 1000)
        out['tensioni_kv'] = sorted({round(v / 1000) for v, _ in linee}, reverse=True)[:4]
    else:
        out['d_linea_m'] = None; out['linea_kv'] = None; out['tensioni_kv'] = []
    return out


def distanze_multi(gruppi, margine_deg=(0.055, 0.07), _fetch=None):
    """Distanze dalla rete per PIU' insiemi di punti, con UNA sola interrogazione.

    Serve al portafoglio: cinque blocchi nello stesso comune guardano la stessa
    rete, e cinque query a Overpass per la stessa risposta sono cinque query di
    troppo — lente per noi e scortesi verso un servizio pubblico gratuito.
    Il bbox e' l'unione di tutti i gruppi, allargato del margine: la sottostazione
    puo' stare a chilometri dal terreno.

    `gruppi`: {nome: [(lat, lon), ...]}. Ritorna {nome: {...}} con la stessa forma
    di `distanza_rete`, piu' una voce '_fonte' col conteggio di cio' che ha visto.
    Se Overpass tace, OGNI gruppo esce con verificato=False: mai una distanza
    inventata, e mai un None che si legge come "vicino".
    """
    if not gruppi:
        return {}
    tutti = [p for pts in gruppi.values() for p in pts]
    if not tutti:
        return {k: {'verificato': False, 'nota': 'nessun punto'} for k in gruppi}
    lats = [p[0] for p in tutti]
    lons = [p[1] for p in tutti]
    lat0 = sum(lats) / len(lats)
    MLAT, MLON = m_per_deg(lat0)

    def to_xy(la, lo):
        return (lo * MLON, la * MLAT)

    bbw = (f'{min(lats)-margine_deg[0]},{min(lons)-margine_deg[1]},'
           f'{max(lats)+margine_deg[0]},{max(lons)+margine_deg[1]}')
    q = (f'[out:json][timeout:120];(way[power=line]({bbw}); way[power=substation]({bbw}); '
         f'node[power=substation]({bbw}););out geom tags;')
    od = (_fetch or _overpass)(q)
    if not od:
        return {k: {'verificato': False,
                    'nota': 'Overpass non raggiungibile: distanze rete non calcolate'}
                for k in gruppi}

    subs, linee = [], []
    for e in od.get('elements', []):
        tg = e.get('tags', {})
        if tg.get('power') == 'substation':
            if e['type'] == 'node':
                subs.append(Point(to_xy(e['lat'], e['lon'])))
            elif 'geometry' in e and len(e['geometry']) >= 4:
                subs.append(Polygon([to_xy(p['lat'], p['lon']) for p in e['geometry']]))
        elif tg.get('power') == 'line' and 'geometry' in e and len(e['geometry']) >= 2:
            v = _volt(tg)
            if v and v >= 40000:
                linee.append((v, LineString([to_xy(p['lat'], p['lon']) for p in e['geometry']])))
    u_subs = unary_union(subs) if subs else None

    out = {}
    for nome, pts in gruppi.items():
        if not pts:
            out[nome] = {'verificato': False, 'nota': 'gruppo senza punti'}
            continue
        terreno = MultiPoint([Point(to_xy(la, lo)) for la, lo in pts])
        r = {'verificato': True, 'n_se': len(subs), 'n_linee_at': len(linee)}
        r['d_se_m'] = round(u_subs.distance(terreno)) if u_subs is not None else None
        if linee:
            best = min(linee, key=lambda x: x[1].distance(terreno))
            r['d_linea_m'] = round(best[1].distance(terreno))
            r['linea_kv'] = round(best[0] / 1000)
            r['tensioni_kv'] = sorted({round(v / 1000) for v, _ in linee}, reverse=True)[:4]
        else:
            r['d_linea_m'] = None
            r['linea_kv'] = None
            r['tensioni_kv'] = []
        out[nome] = r
    return out


def _carica():
    try:
        return json.loads(REGISTRO.read_text(encoding='utf-8')).get('nodi', {})
    except Exception:
        return {}


def _mesi_da(d):
    try:
        dt = datetime.strptime(d, '%Y-%m-%d').date()
        return (date.today() - dt).days / 30.4
    except Exception:
        return None


def nodo(comune, prov):
    """Info sul nodo. Ritorna sempre un dict con 'verificato' esplicito."""
    n = _carica().get(f'{comune}|{prov}')
    if not n:
        return {'verificato': False, 'comune': comune, 'prov': prov,
                'nota': 'coda/capacita\' del nodo NON note: verificare su Terna Econnextion '
                        '(dati.terna.it/en/econnextion, filtro per comune) prima di qualsiasi conclusione'}
    m = _mesi_da(n.get('data', ''))
    out = dict(n); out.update({'verificato': True, 'comune': comune, 'prov': prov,
                               'mesi_dal_rilievo': round(m, 1) if m is not None else None,
                               'scaduto': (m is not None and m > MESI_VALIDITA)})
    if out['scaduto']:
        out['nota'] = f"dato di {n.get('data')} ({out['mesi_dal_rilievo']:.0f} mesi fa): le code cambiano, RIVERIFICARE"
    return out


def contesto_nodo(comune, prov):
    """Dict 'node' per recommend.recommend(). Se il nodo non e' noto ritorna {} :
    cosi' recommend NON aggiunge affermazioni sul nodo (meglio tacere che inventare)."""
    n = nodo(comune, prov)
    if not n.get('verificato'):
        return {}
    c = {}
    if n.get('pv_queue_mw') is not None:
        c['pv_queue'] = bool(n['pv_queue_mw'])          # False = coda vuota = primo arrivato
    if n.get('bess_queue_mw'):
        c['bess_queue_mw'] = n['bess_queue_mw']
    c['_fonte'] = n.get('fonte'); c['_data'] = n.get('data'); c['_scaduto'] = n.get('scaduto', False)
    return c


def descrivi_distanza(d):
    if not d or not d.get('verificato'):
        return '   distanza rete: n.d. (' + (d or {}).get('nota', 'non calcolata') + ')'
    p = []
    if d.get('d_se_m') is not None:
        p.append(f"stazione elettrica più vicina a **{d['d_se_m']/1000:.1f} km**")
    else:
        p.append('nessuna stazione elettrica nel raggio cercato (~6 km)')
    if d.get('d_linea_m') is not None:
        p.append(f"linea {d['linea_kv']} kV a **{d['d_linea_m']/1000:.1f} km**")
    else:
        p.append('nessuna linea AT nel raggio cercato')
    s = '   ' + ' · '.join(p).replace('**', '')
    if d.get('tensioni_kv'):
        s += f"  (tensioni in zona: {', '.join(str(v)+' kV' for v in d['tensioni_kv'])})"
    s += '\n   fonte: OSM/Overpass — indicativa, il TICA lo fa il gestore'
    return s


def descrivi(n):
    if not n.get('verificato'):
        return f"nodo {n['comune']} ({n['prov']}): ⚠ coda NON nota — {n['nota']}"
    p = []
    if n.get('pv_queue_mw') == 0:
        p.append('coda FV VUOTA (primo arrivato sul solare)')
    elif n.get('pv_queue_mw'):
        p.append(f"{n['pv_queue_mw']:.0f} MW FV in coda")
    if n.get('bess_queue_mw'):
        p.append(f"{n['bess_queue_mw']:.0f} MW BESS in coda (mercato storage attivo ma affollato)")
    if n.get('wind_queue_mw'):
        p.append(f"{n['wind_queue_mw']:.0f} MW eolico in coda")
    if n.get('cp_satura') is False:
        p.append('cabina primaria NON satura')
    elif n.get('cp_satura'):
        p.append('⚠ cabina primaria SATURA')
    s = f"nodo {n['comune']} ({n['prov']}): " + ' · '.join(p)
    if n.get('scaduto'):
        s += f"\n   ⚠ {n['nota']}"
    else:
        s += f"\n   fonte: {n.get('fonte')} · rilievo {n.get('data')}"
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodo'); ap.add_argument('--prov')      # niente default='BN' (bug QA 16/07)
    ap.add_argument('--lista', action='store_true')
    A = ap.parse_args()
    if A.lista:
        d = _carica()
        print(f'Registro nodi: {len(d)} voci  ({REGISTRO})')
        for k, v in d.items():
            c, p = k.split('|')
            print('  -', descrivi(nodo(c, p)))
        print('\nIl dato NON e\' automatizzabile (Econnextion = PowerBI, API Terna con credenziali):')
        print('si aggiorna a mano su dati.terna.it/en/econnextion e si DATA sempre.')
        return
    if A.nodo:
        print(descrivi(nodo(A.nodo, A.prov)))
        return
    print('Uso: --nodo Morcone --prov BN  |  --lista')


if __name__ == '__main__':
    main()
