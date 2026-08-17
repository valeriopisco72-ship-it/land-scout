"""land-scout satcheck — verifica satellitare dell'occupazione reale delle particelle.

Scarica imagery ESRI World Imagery, disegna i perimetri catastali e produce:
- un PNG per particella (zoom 18)
- un foglio-contatti (griglia) per revisione rapida
- un indice JSON

Uso:
  .venv/Scripts/python landscout/satcheck.py --scan demo/scan_zonaA.json \
      --rings demo/scan_zonaA_parcels_cache.json \
      --keys "C719_8_210,F717_37_634,..."   (oppure --top 20 [--min-voto 8])
      --out demo/sat_zonaA
"""
import argparse, json, math, io, os, re, sys, time, urllib.request

sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image, ImageDraw

UA = {'User-Agent': 'Mozilla/5.0 (land-scout satcheck)'}
TILE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'

def deg2tile(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y

_tile_cache = {}
def get_tile(z, x, y):
    k = (z, x, y)
    if k not in _tile_cache:
        req = urllib.request.Request(TILE.format(z=z, x=x, y=y), headers=UA)
        try:
            _tile_cache[k] = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=30).read())).convert('RGB')
        except Exception:
            _tile_cache[k] = Image.new('RGB', (256, 256), (30, 30, 30))
        time.sleep(0.15)
    return _tile_cache[k]

def render_parcel(ring, z=18, pad=0.0006):
    lats = [p[0] for p in ring]; lons = [p[1] for p in ring]
    x0, y0 = deg2tile(max(lats) + pad, min(lons) - pad, z)
    x1, y1 = deg2tile(min(lats) - pad, max(lons) + pad, z)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    img = Image.new('RGB', ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            img.paste(get_tile(z, tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))
    dr = ImageDraw.Draw(img)
    pts = []
    for la, lo in ring:
        x, y = deg2tile(la, lo, z)
        pts.append(((x - tx0) * 256, (y - ty0) * 256))
    dr.line(pts + [pts[0]], fill=(255, 60, 40), width=4)
    # ritaglia attorno al perimetro con margine
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    m = 60
    box = (max(0, int(min(xs)) - m), max(0, int(min(ys)) - m),
           min(img.width, int(max(xs)) + m), min(img.height, int(max(ys)) + m))
    return img.crop(box)

def _contact_sheet(thumbs, out):
    """Griglia di miniature etichettate: si rivede un blocco in un colpo d'occhio."""
    if not thumbs:
        return None
    cols = min(4, len(thumbs))
    rws = (len(thumbs) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * 445, rws * 475), (0, 0, 0))
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * 445, (i // cols) * 475))
    path = os.path.join(out, '_contact_sheet.png')
    sheet.save(path)
    return path


def render_block(parcels, out, z=18, ordina_per_ha=True):
    """Screening satellitare di un BLOCCO passato direttamente come dict.

    parcels: {id: {'anello': [[lat,lon],...], 'ha': float [, 'nota': str]}}

    Perche' serviva: la CLI storica pretende `--scan` (formato scanner) + `--rings`
    (cache catastale con id INSPIRE). Chi ha gia' i poligoni — cioe' chiunque usi
    `catasto.py` o costruisca un blocco a mano — non poteva usare satcheck.
    Il catasto dice cosa e' la particella *sulla carta*; qui si guarda cosa c'e'
    davvero sopra: fabbricati, serre, bosco, cave, impianti gia' esistenti.
    Sul blocco EDP questo passaggio elimino' 3 ancore su 15 (una "voto 10" era la
    sottostazione stessa): NON e' un abbellimento, e' un filtro.
    """
    os.makedirs(out, exist_ok=True)
    items = list(parcels.items())
    if ordina_per_ha:
        items.sort(key=lambda kv: -(kv[1].get('ha') or 0))
    thumbs, index = [], []
    for pid, p in items:
        ring = p.get('anello') or p.get('ring')
        if not ring:
            print('  ring mancante:', pid)
            continue
        img = render_parcel(ring, z=z)
        name = str(pid).replace('/', '_').replace('\\', '_')
        img.save(os.path.join(out, name + '.png'))
        index.append({'id': pid, 'ha': p.get('ha'), 'file': name + '.png',
                      'nota': p.get('nota'), 'occupazione': None})   # da compilare a revisione
        th = img.copy(); th.thumbnail((420, 420))
        canvas = Image.new('RGB', (440, 470), (15, 15, 15))
        canvas.paste(th, (10 + (420 - th.width) // 2, 10 + (420 - th.height) // 2))
        d = ImageDraw.Draw(canvas)
        et = f"{pid}  {(p.get('ha') or 0):.2f} ha" + (('  ' + str(p['nota'])) if p.get('nota') else '')
        d.text((12, 440), et[:62], fill=(255, 255, 255))
        thumbs.append(canvas)
        print(f"  ok {name} ({(p.get('ha') or 0):.2f} ha)")
    sheet = _contact_sheet(thumbs, out)
    json.dump(index, open(os.path.join(out, '_index.json'), 'w'), indent=1, ensure_ascii=False)
    print(f"\nsalvati {len(index)} PNG" + (' + _contact_sheet.png' if sheet else '') + f" in {out}")
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', required=False)
    ap.add_argument('--rings', required=False)
    ap.add_argument('--parcels', default=None,
                    help='JSON {id:{anello,ha[,nota]}}: usa direttamente i poligoni (niente --scan/--rings)')
    ap.add_argument('--keys', default='')
    ap.add_argument('--top', type=int, default=0)
    ap.add_argument('--min-voto', type=float, default=0)
    ap.add_argument('--z', type=int, default=18)
    ap.add_argument('--out', required=True)
    A = ap.parse_args()

    # via diretta: chi ha gia' i poligoni non deve passare dai formati dello scanner
    if A.parcels:
        render_block(json.load(open(A.parcels, encoding='utf-8')), A.out, z=A.z)
        return
    if not (A.scan and A.rings):
        ap.error('servono --parcels, oppure --scan insieme a --rings')

    rows = json.load(open(A.scan))['risultati']
    raw = json.load(open(A.rings))
    rings = {}
    for pid, ring in raw.items():
        m = re.match(r'IT\.AGE\.PLA\.([A-Z]\d{3})_0*(\d+)00\.(.+)$', pid)
        if m:
            rings[(m.group(1), str(int(m.group(2))), m.group(3))] = ring

    if A.keys:
        sel = []
        for kk in A.keys.split(','):
            c, f, p = kk.strip().split('_')
            r = next((r for r in rows if (r['com'], r['fg'], r['pla']) == (c, f, p)), None)
            if r: sel.append(r)
    else:
        sel = [r for r in rows if r['voto'] >= A.min_voto and r['classe'] != 'D']
        if A.top: sel = sel[:A.top]

    os.makedirs(A.out, exist_ok=True)
    thumbs, index = [], []
    for r in sel:
        k = (r['com'], r['fg'], r['pla'])
        ring = rings.get(k)
        if not ring:
            print('  ring mancante:', k); continue
        img = render_parcel(ring, z=A.z)
        name = f"{r['com']}_Fg{r['fg']}_P{r['pla']}"
        img.save(os.path.join(A.out, name + '.png'))
        index.append({'key': '_'.join(k), 'ha': r['ha'], 'voto': r['voto'], 'file': name + '.png'})
        # thumbnail etichettata per il foglio-contatti
        th = img.copy(); th.thumbnail((420, 420))
        canvas = Image.new('RGB', (440, 470), (15, 15, 15))
        canvas.paste(th, (10 + (420 - th.width) // 2, 10 + (420 - th.height) // 2))
        d = ImageDraw.Draw(canvas)
        d.text((12, 440), f"Fg.{r['fg']} P.{r['pla']}  {r['ha']:.2f} ha  voto {r['voto']}", fill=(255, 255, 255))
        thumbs.append(canvas)
        print(f"  ok {name} ({r['ha']:.2f} ha)")

    if thumbs:
        cols = min(4, len(thumbs))
        rws = (len(thumbs) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * 445, rws * 475), (0, 0, 0))
        for i, t in enumerate(thumbs):
            sheet.paste(t, ((i % cols) * 445, (i // cols) * 475))
        sheet.save(os.path.join(A.out, '_contact_sheet.png'))
    json.dump(index, open(os.path.join(A.out, '_index.json'), 'w'), indent=1)
    print(f"\nsalvati {len(index)} PNG + _contact_sheet.png in {A.out}")

if __name__ == '__main__':
    main()
