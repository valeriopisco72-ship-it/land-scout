"""land-scout scan — screening di un'AREA ARBITRARIA (bbox) con voto 0-10.
Uso: .venv/Scripts/python landscout/scan.py --bbox 42.3482,13.7424,42.3762,13.7794 --tech BESS --min-ha 0.5 --out demo/scan_zonaA
"""
import argparse, urllib.request, urllib.parse, json, math, os, re, sys, time, csv

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)   # radice auto-rilevata (no path assoluti)
sys.path.insert(0, BASE)
sys.stdout.reconfigure(encoding='utf-8')
from landscout.engine import score_parcel, price_parcel, voto_10, m_per_deg
from landscout.config import latlon
from shapely.geometry import Polygon, LineString, Point, shape
from shapely.ops import unary_union

UA = {'User-Agent': 'land-scout-scan/0.1'}
def get(url, timeout=120):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode('utf-8', 'replace')


def main(argv=None):
    """Corpo dello scan.

    ⚠️ 12/08/2026: prima stava tutto a livello di MODULO, con `argparse` che
    girava all'import — quindi `import landscout.scan` alzava SystemExit(2) e il
    modulo non era importabile ne' testabile. Erano 357 righe di porta d'ingresso
    del tool senza un solo test, e senza modo di scriverne uno. Il corpo qui sotto
    e' identico a quello di prima, solo indentato — tranne le righe interne alle
    stringhe multiriga, lasciate com'erano perche' indentarle cambierebbe il testo
    della query Overpass (che finisce anche nella chiave di cache). Verificato
    confrontando gli AST."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--bbox', required=True)           # latmin,lonmin,latmax,lonmax
    ap.add_argument('--tech', default='BESS', choices=['BESS', 'agriPV'])
    ap.add_argument('--min-ha', type=float, default=0.5)
    ap.add_argument('--vincoli', action='store_true',
                    help='Fase 7: arricchisci ogni particella con vincoli UFFICIALI (habitat 6220 divieto FV, SIC, SITAP usi civici/tratturo/bosco/art136) → entra nel voto')
    ap.add_argument('--out', required=True)
    A = ap.parse_args(argv)   # argv=None -> sys.argv, come prima
    latmin, lonmin, latmax, lonmax = [float(x) for x in A.bbox.split(',')]
    LAT0 = (latmin + latmax) / 2
    MLAT, MLON = m_per_deg(LAT0)
    def to_xy(lat, lon): return (lon * MLON, lat * MLAT)

    OUT = os.path.join(BASE, A.out)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    # ---------- 1. catasto (tile) ----------
    def fetch_tile(bbox):
        p = {'SERVICE': 'WFS', 'VERSION': '2.0.0', 'REQUEST': 'GetFeature', 'TYPENAMES': 'CP:CadastralParcel',
             'SRSNAME': 'urn:ogc:def:crs:EPSG::6706',
             'BBOX': f'{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},urn:ogc:def:crs:EPSG::6706',
             'COUNT': '500', 'STARTINDEX': '0'}
        d = get('https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php?' + urllib.parse.urlencode(p))
        out = {}
        for m in d.split('<wfs:member>')[1:]:
            gid = re.search(r'gml:id="CadastralParcel\.(IT\.AGE\.PLA\.[^"]+)"', m)
            pl = re.findall(r'<gml:posList[^>]*>([\d\.\s\-]+)</gml:posList>', m)
            if gid and pl:
                n = pl[0].split()
                out[gid.group(1)] = [(float(n[i]), float(n[i+1])) for i in range(0, len(n)-1, 2)]
        return out

    CACHE = OUT + '_parcels_cache.json'
    if os.path.exists(CACHE):
        raw = json.load(open(CACHE))
    else:
        raw, lat = {}, latmin
        while lat < latmax:
            lon = lonmin
            while lon < lonmax:
                t = fetch_tile((lat, lon, min(lat+0.007, latmax), min(lon+0.010, lonmax)))
                raw.update(t)
                print(f'  tile {lat:.3f},{lon:.3f}: +{len(t)} (tot {len(raw)})')
                lon += 0.010
                time.sleep(0.7)
            lat += 0.007
        json.dump(raw, open(CACHE, 'w'))
    print('particelle grezze:', len(raw))

    parc = []
    for pid, ring in raw.items():
        m = re.match(r'IT\.AGE\.PLA\.([A-Z]\d{3})_0*(\d+)00\.(.+)$', pid)
        if not m or not m.group(3)[0].isdigit():
            continue  # esclude poligoni STRADA/ACQUA/etichette non-particella
        poly = Polygon([to_xy(la, lo) for la, lo in ring])
        if not poly.is_valid:
            poly = poly.buffer(0)
        ha = poly.area / 10000
        if ha >= A.min_ha:
            parc.append({'com': m.group(1), 'fg': str(int(m.group(2))), 'pla': m.group(3),
                         'ring': ring, 'poly': poly, 'ha': ha})
    print(f'particelle >= {A.min_ha} ha: {len(parc)}')

    # ---------- 2. Natura 2000 (EEA live, per bbox) ----------
    n2k_polys = []
    eea = 'https://bio.discomap.eea.europa.eu/arcgis/rest/services/ProtectedSites/Natura2000Sites/MapServer'
    for lyr in (0, 1, 2):
        p = {'f': 'json', 'geometry': f'{lonmin-0.02},{latmin-0.02},{lonmax+0.02},{latmax+0.02}',
             'geometryType': 'esriGeometryEnvelope', 'inSR': '4326', 'outSR': '4326',
             'spatialRel': 'esriSpatialRelIntersects', 'outFields': 'SITECODE,SITENAME', 'where': '1=1',
             'returnGeometry': 'true'}
        try:
            d = json.loads(get(f'{eea}/{lyr}/query?' + urllib.parse.urlencode(p)))
            for f in d.get('features', []):
                code = f['attributes']['SITECODE']
                for ringg in f['geometry']['rings']:
                    n2k_polys.append((code, Polygon([to_xy(v[1], v[0]) for v in ringg])))
        except Exception as e:
            print('EEA layer', lyr, 'fail:', str(e)[:60])
        time.sleep(0.4)
    n2k_u = unary_union([g for _, g in n2k_polys]) if n2k_polys else None
    print('N2K: siti-anelli', len(n2k_polys), '| codici:', sorted({c for c, _ in n2k_polys}))

    # ---------- 3. PAI ----------
    # ⚠ `srsName` NON e' opzionale. Il bbox in urn:...EPSG::4326 dice al server in che
    # sistema legge la richiesta, non in che sistema deve rispondere: IdroGEO risponde
    # nel CRS nativo del layer (EPSG:3857, verificato l'08/08/2026) e il GeoJSON esce
    # in metri. Senza questa riga i poligoni del PAI finiscono a milioni di km dai
    # terreni, non intersecano piu' nulla e OGNI particella risulta senza vincolo
    # frane/idraulica — un blocker spento in silenzio.
    def wfs_idro(layer):
        p = {'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature', 'typeNames': layer,
             'outputFormat': 'application/json', 'count': '1000', 'srsName': 'EPSG:4326',
             'bbox': f'{latmin-0.01},{lonmin-0.01},{latmax+0.01},{lonmax+0.01},urn:ogc:def:crs:EPSG::4326'}
        return json.loads(get('https://idrogeo.isprambiente.it/geoserver/idrogeo/ows?' + urllib.parse.urlencode(p)))

    def geo2xy(geom):
        """GeoJSON -> piano metrico locale, con controllo del sistema di coordinate.

    La versione precedente indovinava: se la coppia non sembrava (lat, lon) la
    trattava come (lon, lat). Su coordinate proiettate l'indovinello non fallisce
    mai in modo visibile — proietta e basta, lontanissimo — quindi il tool taceva.
    Qui cio' che non e' riconoscibile ALZA: meglio un errore che un "pulito" falso.
    """
        def conv(cc):
            return [to_xy(*latlon(x, y)) for x, y in cc]
        if geom.geom_type == 'Polygon':
            return Polygon(conv(geom.exterior.coords))
        return unary_union([Polygon(conv(g.exterior.coords)) for g in geom.geoms])

    pai_fr, pai_idr = [], []
    pai_ok = True
    pai_nota = ''
    try:
        for f in wfs_idro('idrogeo:pericolosita_frane').get('features', []):
            pai_fr.append((geo2xy(shape(f['geometry'])), f['properties'].get('cod_per_it', -1)))
        for lvl, lay in [(1, 'p1'), (2, 'p2'), (3, 'p3')]:
            for f in wfs_idro('idrogeo:pericolosita_idraulica_' + lay).get('features', []):
                pai_idr.append((geo2xy(shape(f['geometry'])), lvl))
            time.sleep(0.4)
    except Exception as e:
        # un PAI che non si scarica non e' un'area senza frane: e' un'area non verificata.
        pai_ok = False
        pai_nota = f'{type(e).__name__}: {e}'
        pai_fr, pai_idr = [], []
        print(f'ATTENZIONE: PAI NON verificato ({pai_nota}) — le particelle usciranno '
          f'con il vincolo frane/idraulica DA CONTROLLARE, non come pulite')
    print('PAI: frane', len(pai_fr), '| idraulica', len(pai_idr),
          '' if pai_ok else '| NON VERIFICATO')

    # ---------- 4. OSM (rete + acque + boschi + edifici) ----------
    OSMC = OUT + '_osm_cache.json'
    if os.path.exists(OSMC):
        od = json.load(open(OSMC))
    else:
        bb = f'{latmin-0.01},{lonmin-0.013},{latmax+0.01},{lonmax+0.013}'
        # la rete elettrica va cercata ben oltre il bbox: la SE piu' vicina puo' stare a km
        bbw = f'{latmin-0.055},{lonmin-0.07},{latmax+0.055},{lonmax+0.07}'
        q = f'''[out:json][timeout:120];
(way[power=line]({bbw}); way[power=substation]({bbw}); node[power=substation]({bbw});
 way[natural=water]({bb}); way[waterway=river]({bb}); way[waterway=stream]({bb});
 way[natural=wood]({bb}); way[landuse=forest]({bb}); way[building]({bb});
 way[landuse~"industrial|commercial"]({bb}););out geom tags;'''
        od = None
        for m in ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter',
                  'https://maps.mail.ru/osm/tools/overpass/api/interpreter']:
            try:
                r = urllib.request.Request(m, data=urllib.parse.urlencode({'data': q}).encode(), headers=UA)
                od = json.loads(urllib.request.urlopen(r, timeout=150).read())
                break
            except Exception as e:
                print('overpass fail', str(e)[:50]); time.sleep(4)
        if od: json.dump(od, open(OSMC, 'w'))

    lines150, subs, waters, rivers, streams, woods, builds = [], [], [], [], [], [], []
    for e in (od['elements'] if od else []):
        t = e.get('tags', {})
        if 'geometry' not in e and e['type'] != 'node':
            continue
        if e['type'] == 'way':
            pts = [(p['lat'], p['lon']) for p in e['geometry']]
        if t.get('power') == 'line' and '150000' in t.get('voltage', ''):
            lines150.append(LineString([to_xy(*p) for p in pts]))
        elif t.get('power') == 'substation':
            if e['type'] == 'node':
                subs.append(Point(to_xy(e['lat'], e['lon'])))
            elif len(pts) >= 4:
                subs.append(Polygon([to_xy(*p) for p in pts]))
        elif t.get('natural') == 'water' and len(pts) >= 4:
            waters.append(Polygon([to_xy(*p) for p in pts]))
        elif t.get('waterway') == 'river':
            rivers.append(LineString([to_xy(*p) for p in pts]))
        elif t.get('waterway') == 'stream':
            streams.append(LineString([to_xy(*p) for p in pts]))
        elif (t.get('natural') == 'wood' or t.get('landuse') == 'forest') and len(pts) >= 4:
            woods.append(Polygon([to_xy(*p) for p in pts]))
        elif ('building' in t or t.get('landuse') in ('industrial', 'commercial')) and len(pts) >= 4:
            builds.append(Polygon([to_xy(*p) for p in pts]))
    print(f'OSM: linee150 {len(lines150)} | SE {len(subs)} | boschi {len(woods)} | edifici {len(builds)} | torrenti {len(streams)}')
    lines_u = unary_union(lines150) if lines150 else None
    subs_u = unary_union(subs) if subs else None
    lakes = [w for w in waters if w.area / 10000 > 100]
    fascia_lago = unary_union([l.buffer(300) for l in lakes]) if lakes else None
    fascia_fiume = unary_union([r.buffer(150) for r in rivers]) if rivers else None
    stream_buf = unary_union([s.buffer(150) for s in streams]) if streams else None
    wood_u = unary_union([w.buffer(0) for w in woods]) if woods else None
    build_u = unary_union([b.buffer(0) for b in builds]) if builds else None

    # ---------- 5. DEM (SRTM per tutti; EU-DEM per top-30 provvisori) ----------
    def dem_batch(items, dataset):
        """items: [(key, clat, clon, r)] -> {key: slope}"""
        out = {}
        for i in range(0, len(items), 20):
            chunk = items[i:i+20]
            pts = []
            for _, clat, clon, r in chunk:
                dlat = r/111132.0; dlon = r/(111320.0*math.cos(math.radians(clat)))
                pts += [(clat, clon), (clat+dlat, clon), (clat-dlat, clon), (clat, clon+dlon), (clat, clon-dlon)]
            locs = '|'.join(f'{a:.6f},{b:.6f}' for a, b in pts)
            url = f'https://api.opentopodata.org/v1/{dataset}?locations=' + urllib.parse.quote(locs, safe=',|')
            for att in range(4):
                try:
                    el = [x['elevation'] for x in json.loads(get(url, 60))['results']]
                    for j, (k, _, _, r) in enumerate(chunk):
                        e = el[j*5:(j+1)*5]
                        if None not in e and len(e) == 5:
                            out[k] = round(math.hypot(abs(e[1]-e[2])/(2*r)*100, abs(e[3]-e[4])/(2*r)*100), 1)
                    break
                except Exception as ex:
                    print('  dem retry', str(ex)[:40]); time.sleep(4)
            time.sleep(1.1)
        return out

    items = []
    for p in parc:
        ring = p['ring']
        clat = sum(q[0] for q in ring)/len(ring); clon = sum(q[1] for q in ring)/len(ring)
        p['c'] = (clat, clon)
        items.append((f"{p['com']}_{p['fg']}_{p['pla']}", clat, clon,
                      max(40, min(120, math.sqrt(p['ha']*10000)/2))))
    DEMC = OUT + '_dem_cache.json'
    dem = json.load(open(DEMC)) if os.path.exists(DEMC) else {}
    todo = [it for it in items if it[0] not in dem]
    if todo:
        print(f'DEM SRTM: {len(todo)} particelle...')
        dem.update(dem_batch(todo, 'srtm30m'))
        json.dump(dem, open(DEMC, 'w'))

    # ---------- 5b. vincoli ufficiali (Fase 7, opt-in --vincoli) ----------
    sic_u = None; sit = {}; VINC = {}; sit_ok = True
    if A.vincoli:
        from landscout import vincoli as VC
        plist = [{'id': f"{p['com']}_{p['fg']}_{p['pla']}", 'lat': p['c'][0], 'lon': p['c'][1], 'ha': p['ha']} for p in parc]
        print(f'Vincoli Fase 7 su {len(plist)} particelle: SITAP + SIC + habitat...')
        # natura2000 ora ritorna anche n2k_ok: False = EEA non ha risposto -> NON e' "fuori da SIC"
        try:
            _, sic_u, n2k_ok = VC.natura2000(plist, to_xy)
            if not n2k_ok:
                sic_u = None
                print('  ! EEA non raggiunta: SIC NON verificato su questo scan (non assumere "fuori")')
        except Exception as e: print('  ! natura2000:', e)
        try: sit, sit_ok = VC.sitap_paesaggio(plist, to_xy)
        except Exception as e: sit_ok = False; print('  ! sitap:', e)
        try:
            VINC = VC.habitat_ban({x['id']: x for x in plist})
            if VINC is None:                    # fonte non raggiunta: nessun habitat verificato
                VINC = {}
                print('  ! Carta Habitat non raggiunta: divieto habitat NON verificato su questo scan')
        except Exception as e: print('  ! habitat:', e)

    # ---------- 6. scoring ----------
    rows = []
    for p in parc:
        poly = p['poly']
        k = f"{p['com']}_{p['fg']}_{p['pla']}"
        zpct = 100*poly.intersection(n2k_u).area/poly.area if (n2k_u is not None and poly.intersects(n2k_u)) else 0.0
        zbd = poly.distance(n2k_u) if (n2k_u is not None and zpct == 0) else (-1 if zpct > 0 else 9e9)
        # se il layer non e' stato scaricato, `None`: "non controllato" != "nessun vincolo"
        fr = max([c for g, c in pai_fr if poly.intersects(g)], default=-1) if pai_ok else None
        idr = max([l for g, l in pai_idr if poly.intersects(g)], default=0) if pai_ok else None
        d_se = poly.distance(subs_u) if subs_u is not None else 9e9
        d_kv = poly.distance(lines_u) if lines_u is not None else 9e9
        pdata = {'ha': p['ha'], 'slope': dem.get(k), 'zps_pct': zpct, 'zps_border_m': zbd,
                 'pai_fr': fr, 'pai_idr': idr, 'pai_incompleto': not pai_ok,
                 'd_se_m': d_se, 'd_150kv_m': d_kv,
                 'fascia_lago': bool(fascia_lago is not None and poly.intersects(fascia_lago)),
                 'fascia_fiume': bool(fascia_fiume is not None and poly.intersects(fascia_fiume)),
                 'note_occupazione': None}
        if A.vincoli:
            cod = VINC.get(k)
            pdata['habitat'] = cod
            pdata['habitat_ban'] = bool(cod and (cod.startswith('6220') or cod.startswith('6210')))
            pdata['in_sic'] = bool(sic_u is not None and poly.intersects(sic_u))
            for nm in ('usi_civici', 'bosco_142g', 'tratturo', 'art136'):
                g = sit.get(nm)
                pdata[nm] = bool(g is not None and poly.intersects(g))
            if sit.get('lago_300m') is not None and poly.intersects(sit['lago_300m']): pdata['fascia_lago'] = True
            if sit.get('fiume_150m') is not None and poly.intersects(sit['fiume_150m']): pdata['fascia_fiume'] = True
            pdata['paesaggio_incompleto'] = (not sit_ok)
        score, classe, flags = score_parcel(pdata, tech=A.tech)
        # flag extra OSM
        if wood_u is not None and poly.intersects(wood_u):
            wpct = 100*poly.intersection(wood_u).area/poly.area
            if wpct > 5:
                flags.append(f'possibile bosco 142-g ~{wpct:.0f}% (OSM)')
                score = max(0, score - 8)
        if build_u is not None and poly.intersects(build_u):
            flags.append('edifici/aree produttive OSM sulla particella')
            score = max(0, score - 10)
        if stream_buf is not None and poly.intersects(stream_buf):
            flags.append('entro 150 m da torrente OSM (lett. c solo se in elenchi)')
        voto = voto_10(score, classe)
        prezzo = price_parcel(pdata, score, classe, tech=A.tech)
        rows.append({'com': p['com'], 'fg': p['fg'], 'pla': p['pla'], 'ha': round(p['ha'], 2),
                     'voto': voto, 'classe': classe, 'score': score,
                     'd_se_m': round(d_se), 'd_150kv_m': round(d_kv), 'slope': dem.get(k),
                     'n2k_pct': round(zpct, 1), 'n2k_border_m': round(zbd) if 0 < zbd < 9e8 else None,
                     'pai_fr': fr, 'pai_idr': idr,
                     # ⚠️ 12/08/2026: la riga portava solo fr/idr, e quando il PAI
                     # non era verificato uscivano None -> nel CSV una CELLA VUOTA,
                     # che e' la forma piu' pericolosa di "non verificato": Excel
                     # non mostra niente e niente si legge come "a posto". Il flag
                     # esplicito viaggia con la riga e sta anche fra le colonne.
                     'pai_incompleto': not pai_ok,
                     'eur_ha_target': prezzo.get('eur_ha', {}).get('target'),
                     'tot_target': prezzo.get('totale_eur', {}).get('target'),
                     'lat': round(p['c'][0], 5), 'lon': round(p['c'][1], 5),
                     'habitat': pdata.get('habitat'), 'habitat_ban': pdata.get('habitat_ban', False),
                     'usi_civici': pdata.get('usi_civici', False), 'in_sic': pdata.get('in_sic', False),
                     # il perimetro, non solo il centroide: senza questo lo scan resta una
                     # graduatoria da leggere a mano, e `blocco` — che lavora sui poligoni —
                     # non puo' riceverne l'esito. E' il ponte fra "trova la terra" e
                     # "costruisci il blocco" (vedi blocco.da_scan).
                     'poly': [(round(la, 6), round(lo, 6)) for la, lo in p['ring']],
                     'flags': flags})
    rows.sort(key=lambda r: (-r['voto'], -r['score'], -r['ha']))

    # EU-DEM cross-check sui top 30
    top = [r for r in rows if r['classe'] != 'D'][:30]
    ed_items = [(f"{r['com']}_{r['fg']}_{r['pla']}", r['lat'], r['lon'],
                 max(40, min(120, math.sqrt(r['ha']*10000)/2))) for r in top]
    eud = dem_batch(ed_items, 'eudem25m')
    for r in rows:
        k = f"{r['com']}_{r['fg']}_{r['pla']}"
        if k in eud:
            r['slope_eudem'] = eud[k]
            if r['slope'] is not None and abs(r['slope'] - eud[k]) > 3:
                r['flags'].append(f"DEM divergenti (SRTM {r['slope']} vs EU-DEM {eud[k]}): rilievo")

    json.dump({'bbox': A.bbox, 'tech': A.tech, 'min_ha': A.min_ha, 'n_parcelle': len(rows),
               'risultati': rows}, open(OUT + '.json', 'w'), indent=1)
    with open(OUT + '.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        cols = ['com', 'fg', 'pla', 'ha', 'voto', 'classe', 'score', 'd_se_m', 'd_150kv_m', 'slope',
                'slope_eudem', 'n2k_pct', 'n2k_border_m', 'pai_fr', 'pai_idr', 'pai_incompleto',
                'eur_ha_target', 'tot_target', 'flags']
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c) if c != 'flags' else ' | '.join(r['flags']) for c in cols])

    print(f"\n=== TOP 15 su {len(rows)} particelle (tech {A.tech}) ===")
    print(f"{'particella':22s} {'ha':>5s} {'voto':>5s} {'cl':>2s} {'SE m':>6s} {'pend':>5s} {'N2K':>5s}")
    for r in rows[:15]:
        print(f"{r['com']} Fg.{r['fg']:>3} P.{r['pla']:>5} {r['ha']:5.2f} {r['voto']:5.1f} {r['classe']:>2} "
          f"{r['d_se_m']:6d} {str(r['slope']):>5s} {r['n2k_pct']:4.0f}%")
    print('\nsalvati:', OUT + '.json', '+ .csv')


if __name__ == '__main__':
    main()
