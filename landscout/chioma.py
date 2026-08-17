"""land-scout chioma — quanti alberi ci sono DAVVERO su una particella.

Il layer SITAP art.142-g mappa il **vincolo forestale**, non la vegetazione: dice
dove il bosco e' tutelato, non dove ci sono le piante. Su Morcone la differenza
e' costata cinque volte, sempre nello stesso modo: una particella "pulita" per il
vincolo e boscata nella realta' entra nel blocco, e gli ettari annunciati non
esistono.

Servono due misure diverse e non intercambiabili: il **vincolo** (dice se serve
un'autorizzazione, e sta in `vincoli.py`) e la **copertura** (dice quanti ettari
ospitano davvero i moduli e quanto costa sgomberare). Questo modulo fa la
seconda.

### Fonte primaria: Copernicus HRL Tree Cover Density 2018 (EEA)

Raster ufficiale a 10 m, valori 0-100 = percentuale di chioma nel pixel.
Interrogato via l'operazione `getSamples` dell'ImageServer EEA: un poligono, una
chiamata, centinaia di campioni. La **media dei campioni** e' la copertura della
particella — non la quota di pixel sopra una soglia, che su fondi piccoli conta
soprattutto i bordi (siepi e alberate confinanti) e gonfia il risultato.

Calibrazione su quattro casi a esito noto del blocco Morcone (01/08/2026):

| particella | atteso | TCD medio |
|---|---|---|
| Fg82/32  | seminativo pulito          |  3,9% |
| Fg70/136 | **12% verificato il 25/07** | **12,3%** |
| Fg70/774 | aperta con filari d'ulivo in un angolo | 16,3% |
| Fg70/257 | fascia boscata quasi piena | 48,6% |

Il secondo e' la conferma che conta: il valore ricalcolato coincide con quello
ottenuto in modo indipendente il 25/07.

### ⚠️ I due limiti veri, da dichiarare in ogni dossier

1. **Il dato e' del 2018.** La ricolonizzazione degli ultimi anni non c'e'. Un
   fondo abbandonato dopo il 2018 risulta piu' pulito di quanto sia — ed e'
   proprio il caso di Fg70/136 (12% nel 2018, chioma ben visibile oggi). Il TCD
   basso quindi **non assolve**: dice "nel 2018 non era bosco", che serve a
   difendere una perizia forestale, non a promettere ettari.
2. **Pixel da 10 m.** Su particelle strette o piccole i pixel di bordo prendono
   dentro siepi e alberate dei vicini. Sotto ~0,2 ha il numero va guardato con
   sospetto e confrontato con la foto.

### Metodo secondario (tessitura) — 🔴 NON VALIDATO, non usarlo

`analizza_tessitura()` misura la deviazione standard locale della luminanza
sull'ortofoto. Sui 5 controlli ne ha superati 4, ma ha fallito **quello
decisivo**: Fg70/257 misurava 7,6% ed usciva "APERTA". Motivo: la tessitura
riconosce gli alberi ISOLATI (chiome staccate, ombre nette) ed e' **cieca sul
bosco fitto**, che a zoom 18 e' una macchia verde uniforme a bassa varianza —
cioe' l'unico caso per cui serviva. Resta in repo come fallback offline e come
promemoria, con i suoi numeri marcati inaffidabili.

Uso:
    from landscout import chioma
    R = chioma.screening({id: {'anello': ring, 'ha': ha}})
    chioma.print_report(R)
"""
import json
import math
import urllib.parse
import urllib.request

try:
    from . import satcheck
except ImportError:  # eseguito come script sciolto
    import satcheck

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageStat  # noqa: F401
except ImportError:  # pragma: no cover
    Image = None

EP_TCD = ('https://image.discomap.eea.europa.eu/arcgis/rest/services/'
          'GioLandPublic/HRL_TreeCoverDensity_2018/ImageServer')
UA = {'User-Agent': 'land-scout/1.0 (screening terreni; contatto via repo)'}
TIMEOUT = 90
CAMPIONI = 300

# Soglie sulla MEDIA del TCD (0-100 = % di chioma).
PCT_COPERTA = 30.0      # oltre: e' bosco o frutteto fitto, non un campo
PCT_ALBERATA = 10.0     # fra le due: alberata a macchie, ettari da scontare

# Tessitura (metodo secondario, non validato)
SIGMA_ALBERO = 18.0
RAGGIO_PX = 3


class TCDNonDisponibile(Exception):
    """Copernicus non ha risposto. Chi chiama DEVE dichiararlo: 'non misurata'
    non e' 'nessun albero' — e' l'errore che questo progetto ha gia' fatto sei
    volte con SITAP, EEA e il catasto."""


def _anello_valido(ring):
    return ring and len(ring) >= 4


def analizza_copernicus(ring, campioni=CAMPIONI, timeout=TIMEOUT):
    """% media di chioma nel poligono, dal raster HRL TCD 2018 (10 m).

    Ritorna {'pct', 'n_campioni', 'fonte', 'anno', 'nota'}. Alza
    TCDNonDisponibile se il servizio non risponde o non restituisce campioni:
    meglio un'eccezione che uno zero silenzioso.
    """
    if not _anello_valido(ring):
        raise TCDNonDisponibile('anello non valido')
    geom = {'rings': [[[lo, la] for la, lo in ring]],
            'spatialReference': {'wkid': 4326}}
    p = {'geometry': json.dumps(geom), 'geometryType': 'esriGeometryPolygon',
         'inSR': 4326, 'sampleCount': campioni,
         'returnFirstValueOnly': 'false', 'f': 'json'}
    url = EP_TCD + '/getSamples?' + urllib.parse.urlencode(p)
    try:
        r = json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=timeout))
    except Exception as e:
        raise TCDNonDisponibile(f'EEA non raggiungibile: {type(e).__name__} {str(e)[:60]}')
    if 'error' in r:
        raise TCDNonDisponibile(f"errore servizio: {str(r['error'])[:80]}")
    vals = []
    for s in r.get('samples') or []:
        v = s.get('value')
        if v in (None, '', 'NoData'):
            continue
        try:
            f = float(v)
        except ValueError:
            continue
        if 0 <= f <= 100:              # 255 = NoData nel raster U8
            vals.append(f)
    if not vals:
        raise TCDNonDisponibile('nessun campione valido nel poligono '
                                '(fuori copertura o particella piu piccola del pixel)')
    media = sum(vals) / len(vals)
    return {'pct': round(media, 1), 'n_campioni': len(vals),
            'fonte': 'Copernicus HRL Tree Cover Density 2018 (EEA), 10 m',
            'anno': 2018,
            'nota': ('dato 2018: la ricolonizzazione successiva NON e\' inclusa, '
                     'quindi un valore basso non assolve la particella')}


def analizza_tessitura(ring, z=18):
    """🔴 NON VALIDATO — cieco sul bosco fitto (fallisce su Fg70/257).

    Resta solo come fallback offline. Il campo 'affidabile' e' False apposta:
    chi legge il risultato deve inciamparci.
    """
    if Image is None:
        return {'pct': None, 'affidabile': False, 'nota': 'PIL non disponibile'}
    lats = [p[0] for p in ring]
    lons = [p[1] for p in ring]
    pad = 0.0002
    x0, y0 = satcheck.deg2tile(max(lats) + pad, min(lons) - pad, z)
    x1, y1 = satcheck.deg2tile(min(lats) - pad, max(lons) + pad, z)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 64:
        return {'pct': None, 'affidabile': False, 'nota': 'troppo estesa per z18'}
    big = Image.new('RGB', ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            t = satcheck.get_tile(z, tx, ty)
            if ImageStat.Stat(t.convert('L')).stddev[0] < 1.0:
                return {'pct': None, 'affidabile': False,
                        'nota': 'tile satellitari non arrivate'}
            big.paste(t, ((tx - tx0) * 256, (ty - ty0) * 256))
    pts = [satcheck.deg2tile(la, lo, z) for la, lo in ring]
    xs = [(x - tx0) * 256 for x, _ in pts]
    ys = [(y - ty0) * 256 for _, y in pts]
    box = (max(0, int(min(xs)) - 4), max(0, int(min(ys)) - 4),
           min(big.width, int(max(xs)) + 4), min(big.height, int(max(ys)) + 4))
    img = big.crop(box)
    if img.width < 6 or img.height < 6:
        return {'pct': None, 'affidabile': False, 'nota': 'troppo piccola per z18'}
    mask = Image.new('L', img.size, 0)
    ImageDraw.Draw(mask).polygon(
        [((x - tx0) * 256 - box[0], (y - ty0) * 256 - box[1]) for x, y in pts], fill=255)
    g = img.convert('L')
    mu = g.filter(ImageFilter.BoxBlur(RAGGIO_PX))
    mu2 = Image.eval(g, lambda v: min(255, v * v // 255)).filter(ImageFilter.BoxBlur(RAGGIO_PX))
    gp, mp, m2p, kp = g.load(), mu.load(), mu2.load(), mask.load()
    tot = alberi = 0
    for yy in range(img.height):
        for xx in range(img.width):
            if not kp[xx, yy]:
                continue
            tot += 1
            var = m2p[xx, yy] * 255 - mp[xx, yy] ** 2
            if var > 0 and math.sqrt(var) > SIGMA_ALBERO:
                alberi += 1
    if tot < 40:
        return {'pct': None, 'affidabile': False, 'nota': f'solo {tot} pixel'}
    return {'pct': round(100.0 * alberi / tot, 1), 'affidabile': False,
            'fonte': 'tessitura ortofoto z18',
            'nota': 'METODO NON VALIDATO: cieco sul bosco fitto, non usare il numero'}


def analizza(ring, fonte='copernicus', **kw):
    if fonte == 'tessitura':
        return analizza_tessitura(ring, **kw)
    return analizza_copernicus(ring, **kw)


def verdetto(r, ha=None):
    """APERTA | ALBERATA | COPERTA | NON_MISURATA + ettari utili stimati."""
    if r is None or r.get('pct') is None:
        return {'verdetto': 'NON_MISURATA', 'ha_utili': None,
                'motivo': (r or {}).get('nota', 'nessuna misura')}
    p = r['pct']
    ha_utili = round(ha * (1 - p / 100.0), 3) if ha is not None else None
    if p >= PCT_COPERTA:
        v, m = 'COPERTA', f'{p:.0f}% di chioma nel 2018: bosco o frutteto fitto, non un campo'
    elif p >= PCT_ALBERATA:
        v, m = 'ALBERATA', f'{p:.0f}% di chioma nel 2018: alberata a macchie, ettari da scontare'
    else:
        v, m = 'APERTA', f'{p:.0f}% di chioma nel 2018: superficie aperta'
    return {'verdetto': v, 'ha_utili': ha_utili, 'motivo': m}


def screening(parcels, fonte='copernicus', verbose=True, **kw):
    """parcels: {id: {'anello': ring, 'ha': float}} -> {id: misura + verdetto}.

    Una particella che il servizio non riesce a misurare NON viene messa a zero:
    esce come NON_MISURATA e va contata a parte.
    """
    out = {}
    for i, (k, p) in enumerate(parcels.items(), 1):
        try:
            r = analizza(p['anello'], fonte=fonte, **kw)
        except TCDNonDisponibile as e:
            r = {'pct': None, 'nota': str(e)}
        v = verdetto(r, p.get('ha'))
        out[k] = dict(r, **v)
        if verbose:
            print(f"  [{i:3d}/{len(parcels)}] {k:<10s} {v['verdetto']:<13s} "
                  + (f"{r['pct']:5.1f}%" if r.get('pct') is not None else '  n.d.'))
    return out


def applica(A, R, escludi_coperte=True):
    """Applica la copertura arborea all'output di blocco.ammissibilita().

    - sottrae dagli ettari netti la quota di chioma
    - toglie dal blocco le particelle COPERTE (se richiesto)
    - una particella NON_MISURATA resta com'e' ma viene marcata e contata:
      non misurata non e' pulita.
    """
    ammesse, scarti = [], dict(A.get('scarti') or {})
    n_ridotte = n_nm = 0
    ha_tolti = 0.0
    for a in A['ammesse']:
        k = f"{a['fg']}_{a['pla']}"
        v = R.get(k)
        if not v:
            ammesse.append(dict(a, chioma='non misurata'))
            n_nm += 1
            continue
        if escludi_coperte and v['verdetto'] == 'COPERTA':
            d = scarti.setdefault('chioma: bosco/frutteto fitto', {'n': 0, 'ha': 0.0})
            d['n'] += 1
            d['ha'] += a['ha']
            ha_tolti += a['netti']
            continue
        a = dict(a, chioma=v['verdetto'])
        if v['verdetto'] == 'NON_MISURATA':
            n_nm += 1
            a['chioma_nota'] = v['motivo']
        elif v.get('pct'):
            prima = a['netti']
            a['netti'] = round(a['netti'] * (1 - v['pct'] / 100.0), 3)
            a['detrazioni'] = dict(a.get('detrazioni') or {}, chioma_pct=v['pct'])
            ha_tolti += prima - a['netti']
            n_ridotte += 1
        ammesse.append(a)
    return dict(A, ammesse=ammesse, scarti=scarti,
                ha_ammessi_netti=round(sum(x['netti'] for x in ammesse), 1),
                chioma={'valutate': len(R), 'ridotte': n_ridotte,
                        'non_misurate': n_nm, 'ha_sottratti': round(ha_tolti, 2),
                        'fonte': 'Copernicus HRL TCD 2018'})


def print_report(R, top=40):
    ok = [v for v in R.values() if v.get('pct') is not None]
    nm = [k for k, v in R.items() if v.get('pct') is None]
    print('\n=== COPERTURA ARBOREA — Copernicus HRL TCD 2018 (10 m) ===')
    print(f'  {len(ok)}/{len(R)} particelle misurate'
          + (f' — {len(nm)} NON misurate: {", ".join(nm[:8])}' if nm else ''))
    for lab in ('COPERTA', 'ALBERATA', 'APERTA'):
        sel = [(k, v) for k, v in R.items() if v.get('verdetto') == lab]
        if not sel:
            continue
        print(f'  {lab} ({len(sel)}):')
        for k, v in sorted(sel, key=lambda t: -(t[1].get('pct') or 0))[:top]:
            print(f"     {k:<10s} {v['pct']:5.1f}% chioma"
                  + (f" · utili {v['ha_utili']:.2f} ha" if v.get('ha_utili') is not None else ''))
    if nm:
        print('  [!] le NON misurate non sono "senza alberi": sono senza misura.')
    print('  ~ dato 2018: la ricolonizzazione successiva non e\' inclusa. '
          'Un TCD basso difende una perizia forestale, non promette ettari.')
    return R
