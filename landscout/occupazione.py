"""land-scout occupazione — cosa c'e' DAVVERO sopra la particella.

Il catasto terreni dice come la particella e' *classificata* (seminativo, uliveto,
pascolo). Non dice se ci sta sopra una casa: il fabbricato vive nel catasto
FABBRICATI, che e' un archivio separato. Risultato: una mappa costruita dalle
visure terreni disegna allegramente il perimetro del giardino di qualcuno e lo
chiama "seminativo".

Qui si guarda il layer `fabbricati` del WMS catastale dell'Agenzia delle Entrate
— sorgente autorevole e nazionale, molto piu' completa di OSM in campagna, dove
OSM mappa forse una casa su tre. Si renderizza il layer sul bbox della particella,
si rasterizza il poligono catastale e si misura quanta della particella e'
coperta da fabbricato.

Perche' serve: sull'agrivoltaico un fabbricato non e' un dettaglio estetico.
1. Fisicamente la superficie sotto la casa non ospita moduli.
2. Nessuno vende o affitta la casa in cui abita: quella particella non e'
   acquisibile a nessun prezzo, e va tolta dal conteggio degli ettari PRIMA di
   scriverli in un teaser.
3. Una particella minuscola tutta edificata e' una controparte in piu' a costo
   zero di ettari: peggiora la frammentazione senza dare superficie.

Nota normativa: NON esiste una distanza minima di legge tra impianto
agrivoltaico e abitazioni, ne' statale ne' in Campania (le LiTAR 4.1 — DD
193 del 05/06/2026 — dicono solo di "evitare per quanto possibile di
interessare case sparse e isolate"), e il Consiglio di Stato ha ribadito che i
Comuni non possono imporre distanze arbitrarie. Il buffer 500 m del DM
21/06/2024 riguarda i BENI TUTELATI, non le case. Percio' l'edificio vicino
NON e' un blocker: e' un vincolo di progetto e un rischio di accettabilita'.
Qui viene segnalato, non usato per escludere.

Disciplina del dato: se il WMS non risponde il verdetto e' NON_VERIFICATO, mai
LIBERA. E ogni run vuole i suoi controlli: una particella nota edificata e una
nota libera. Un test che non puo' fallire non e' un test.
"""
import io
import json
import math
import time
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw

WMS = 'https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php'
UA = {'User-Agent': 'Mozilla/5.0 (land-scout occupazione)'}

# soglie: vedi docstring per il razionale
PCT_ESCLUDE = 15.0      # oltre: la particella E' un lotto edificato
PCT_RIDUCE = 2.0        # tra RIDUCE e ESCLUDE: utile al netto del sedime
HA_MIN_UTILE = 0.10     # residuo sotto cui non vale una trattativa
HA_FRAMMENTO = 0.05     # particella troppo piccola in assoluto
D_PERTINENZA_M = 20.0   # aia/orto attorno alla casa: non ci vanno moduli


def _bbox(ring, pad=0.00035):
    la = [p[0] for p in ring]
    lo = [p[1] for p in ring]
    return min(la) - pad, min(lo) - pad, max(la) + pad, max(lo) + pad


PX_MAX = 2048   # oltre, il WMS AdE risponde ServiceException invece di un PNG


def getmap(ring, layers='fabbricati', px=700, crs='EPSG:6706', retry=2, pad=0.00035):
    """Renderizza un layer WMS catastale sul bbox della particella.

    EPSG:6706 vuole gli assi in ordine lat,lon — con 4326 il servizio risponde
    ma inverte, e ci si ritrova a misurare un pezzo di Molise.

    `pad` allarga il riquadro attorno alla particella (serve per vedere i
    fabbricati appena fuori confine). Chi incolla riquadri adiacenti deve
    passare pad=0: un margine non dichiarato sposta il mosaico rispetto al
    catasto, e i fabbricati finiscono sulla particella del vicino.
    """
    px = min(px, PX_MAX)
    y0, x0, y1, x1 = _bbox(ring, pad=pad)
    q = {'service': 'WMS', 'version': '1.3.0', 'request': 'GetMap',
         'layers': layers, 'styles': '', 'crs': crs,
         'bbox': f'{y0},{x0},{y1},{x1}', 'width': px, 'height': px,
         'format': 'image/png', 'transparent': 'true'}
    url = WMS + '?' + urllib.parse.urlencode(q)
    for k in range(retry + 1):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
            if raw[:8] != b'\x89PNG\r\n\x1a\n':
                raise ValueError('risposta non PNG: ' + raw[:120].decode('utf-8', 'replace'))
            return Image.open(io.BytesIO(raw)).convert('RGBA'), (y0, x0, y1, x1)
        except Exception:
            if k == retry:
                raise
            time.sleep(1.5 * (k + 1))


def _mask(ring, bb, size):
    """Rasterizza il poligono catastale nello stesso riquadro dell'immagine WMS."""
    y0, x0, y1, x1 = bb
    m = Image.new('L', (size, size), 0)
    pts = [((lo - x0) / (x1 - x0) * size, (y1 - la) / (y1 - y0) * size) for la, lo in ring]
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m


def analizza(ring, px=700, distanza=True):
    """% di particella coperta da fabbricato + distanza dal fabbricato piu' vicino.

    Il rapporto fra aree e' invariante rispetto allo stiramento lat/lon del
    riquadro, quindi la percentuale e' corretta anche se i pixel non sono
    quadrati in metri; le distanze invece vengono riportate in metri veri.

    `distanza=False` salta il calcolo del fabbricato esterno piu' vicino, che e'
    la parte cara: serve solo per il verdetto CAUTELA, e quando si sta
    scremando un pool di migliaia di particelle non lo si guarda.
    """
    import numpy as np
    img, bb = getmap(ring, px=px)
    y0, x0, y1, x1 = bb
    A = np.asarray(img.split()[3]) > 10                  # dove c'e' fabbricato
    M = np.asarray(_mask(ring, bb, px)) > 127            # dove c'e' la particella

    dentro = int(M.sum())
    if not dentro:
        raise ValueError('maschera vuota: poligono degenere')
    costruito = int((A & M).sum())
    pct = 100.0 * costruito / dentro

    # metri per pixel (la latitudine comanda la scala verticale)
    latm = (y1 - y0) * 111_320.0 / px
    lonm = (x1 - x0) * 111_320.0 * math.cos(math.radians((y0 + y1) / 2)) / px

    d_est = None
    if distanza and costruito == 0:
        fuori = A & ~M
        if fuori.any():
            # anelli concentrici: si dilata la particella finche' non tocca un
            # fabbricato. Costa qualche shift di matrice invece del prodotto
            # cartesiano bordo x edifici, che su 900 px erano milioni di coppie.
            passo = max(1, int(round(D_PERTINENZA_M / max(latm, lonm) / 6)))
            cur = M.copy()
            for k in range(1, 13):
                nxt = cur.copy()
                nxt[:-passo, :] |= cur[passo:, :]
                nxt[passo:, :] |= cur[:-passo, :]
                nxt[:, :-passo] |= cur[:, passo:]
                nxt[:, passo:] |= cur[:, :-passo]
                if (nxt & fuori).any():
                    d_est = round(k * passo * (latm + lonm) / 2, 1)
                    break
                cur = nxt

    return {'pct_edificato': round(pct, 2),
            'ha_edificato_stima': None,
            'd_edificio_esterno_m': d_est,
            'px_dentro': dentro,
            'fonte': 'AdE WMS layer fabbricati (catasto)'}


class Mosaico:
    """Il layer `fabbricati` scaricato UNA volta su tutta l'area, poi interrogato in locale.

    Screenare 4.000 particelle con una GetMap ciascuna sono 4.000 richieste e
    un'ora buona; le stesse particelle stanno dentro una manciata di riquadri.
    Si scarica il mosaico e si misura in memoria: due ordini di grandezza in
    meno di rete.

    ⚠ E' un PRE-FILTRO, non una misura. Il WMS disegna il contorno dei
    fabbricati con uno spessore in PIXEL: a 0,8 m/px quel tratto copre molto
    piu' terreno che a 0,2 m/px, e la percentuale risulta gonfiata (tarato su
    Morcone: 5,4% contro 1,1% reale su Fg70/825). L'errore e' sempre per
    ECCESSO, quindi il valore vale come limite superiore:
      - mosaico < soglia  -> la particella e' davvero libera (il vero e' minore)
      - mosaico >= soglia -> sospetta, va confermata con analizza() a piena
        risoluzione prima di escluderla.
    Usare `screening_due_stadi()`, che applica esattamente questa logica.
    """

    def __init__(self, bbox, px_tile=1400, ntile=3, verbose=True):
        y0, x0, y1, x1 = bbox
        self.bb = bbox
        self.n = ntile
        self.px = px_tile
        self.W = px_tile * ntile
        self.img = Image.new('L', (self.W, self.W), 0)
        dy = (y1 - y0) / ntile
        dx = (x1 - x0) / ntile
        for r in range(ntile):
            for c in range(ntile):
                ty0, ty1 = y0 + dy * (ntile - 1 - r), y0 + dy * (ntile - r)
                tx0, tx1 = x0 + dx * c, x0 + dx * (c + 1)
                ring = [(ty0, tx0), (ty0, tx1), (ty1, tx1), (ty1, tx0)]
                im, _ = getmap(ring, px=px_tile, pad=0.0)   # pad=0: vedi getmap
                self.img.paste(im.split()[3].point(lambda v: 255 if v > 10 else 0),
                               (c * px_tile, r * px_tile))
                if verbose:
                    print(f'  tile {r},{c} ok')
                time.sleep(0.2)
        self.px_data = self.img.load()

    def _xy(self, la, lo):
        y0, x0, y1, x1 = self.bb
        return ((lo - x0) / (x1 - x0) * self.W, (y1 - la) / (y1 - y0) * self.W)

    def pct(self, ring):
        """% della particella coperta da fabbricato catastale, misurata sul mosaico."""
        pts = [self._xy(la, lo) for la, lo in ring]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if min(xs) < 0 or min(ys) < 0 or max(xs) >= self.W or max(ys) >= self.W:
            return None                       # fuori mosaico: non verificata, non pulita
        x0i, y0i = int(min(xs)), int(min(ys))
        w = max(2, int(max(xs)) - x0i + 1)
        h = max(2, int(max(ys)) - y0i + 1)
        m = Image.new('L', (w, h), 0)
        ImageDraw.Draw(m).polygon([(x - x0i, y - y0i) for x, y in pts], fill=255)
        ml = m.load()
        dentro = costruito = 0
        for yy in range(h):
            for xx in range(w):
                if ml[xx, yy] > 127:
                    dentro += 1
                    if self.px_data[x0i + xx, y0i + yy] > 127:
                        costruito += 1
        return round(100.0 * costruito / dentro, 2) if dentro else None


def arretramento(ring, metri=(20, 30, 50), px=700, pad_extra_m=60):
    """Quanto RESTA della particella arretrando di N metri da ogni fabbricato.

    `analizza()` risponde a "c'e' una casa dentro?" e "quanto e' vicina?".
    Questa risponde alla domanda che decide davvero se il fondo serve:
    **dopo l'arretramento, quanta superficie ospita ancora i moduli?**

    Non esiste una distanza minima di legge fra agrivoltaico e abitazioni (ne'
    statale ne' in Campania: la LiTAR dice solo "evitare per quanto possibile le
    case sparse"). L'arretramento e' quindi una scelta di progetto e un argomento
    di accettabilita' — RWE a Pontelandolfo dichiara 50 m. Ma una particella che
    a 30 m si azzera **non e' un fondo con una casa vicino: e' il giardino di
    quella casa**, e va tolta dal blocco prima di prometterne gli ettari.

    Il buffer si misura anche sui fabbricati FUORI dal perimetro (per questo il
    riquadro e' allargato di `pad_extra_m`): la casa del vicino arretra la tua
    terra esattamente come la tua.

    Ritorna {metri: {'ha_residui_pct', 'utile'}} + la misura base.
    """
    import numpy as np
    pad = 0.00035 + pad_extra_m / 111_320.0
    img, bb = getmap(ring, px=px, pad=pad)
    y0, x0, y1, x1 = bb
    A = np.asarray(img.split()[3]) > 10
    M = np.asarray(_mask(ring, bb, px)) > 127
    dentro = int(M.sum())
    if not dentro:
        raise ValueError('maschera vuota: poligono degenere')
    latm = (y1 - y0) * 111_320.0 / px
    lonm = (x1 - x0) * 111_320.0 * math.cos(math.radians((y0 + y1) / 2)) / px
    m_per_px = (latm + lonm) / 2.0

    out = {'pct_edificato': round(100.0 * int((A & M).sum()) / dentro, 2),
           'm_per_px': round(m_per_px, 2), 'per_metri': {}}
    if not A.any():
        for d in metri:
            out['per_metri'][d] = {'residuo_pct': 100.0, 'utile': True}
        out['nota'] = 'nessun fabbricato nel riquadro: arretramento ininfluente'
        return out

    # distanza euclidea da ogni fabbricato, in pixel -> soglia in pixel per ogni d
    try:
        from scipy.ndimage import distance_transform_edt
        dist = distance_transform_edt(~A) * m_per_px
    except ImportError:
        # dilatazione iterativa: piu' lenta ma senza dipendenze nuove
        dist = np.full(A.shape, np.inf)
        cur = A.copy()
        step = max(1, int(round(2.0 / m_per_px)))       # ~2 m per passo
        for i in range(1, int(max(metri) / 2.0) + 2):
            dist[cur & np.isinf(dist)] = (i - 1) * 2.0
            nuovo = cur.copy()
            for sh in (1, -1):
                nuovo |= np.roll(cur, sh * step, axis=0)
                nuovo |= np.roll(cur, sh * step, axis=1)
            cur = nuovo
        dist[np.isinf(dist)] = 1e9

    for d in metri:
        residuo = int((M & (dist >= d)).sum())
        pct = 100.0 * residuo / dentro
        out['per_metri'][d] = {'residuo_pct': round(pct, 1), 'utile': pct >= 40.0}
    return out


def verdetto(occ, ha):
    """Traduce la misura in una decisione, con il motivo scritto accanto."""
    if occ is None:
        return 'NON_VERIFICATO', 'WMS fabbricati non ha risposto: occupazione ignota'
    pct = occ['pct_edificato']
    ha_netti = round(ha * (1 - pct / 100.0), 3)
    occ['ha_edificato_stima'] = round(ha * pct / 100.0, 3)

    if ha < HA_FRAMMENTO:
        return 'ESCLUSA', f'frammento {ha:.3f} ha (< {HA_FRAMMENTO}): una controparte senza superficie'
    if pct >= PCT_ESCLUDE:
        return 'ESCLUSA', f'{pct:.0f}% coperto da fabbricato: e\' un lotto edificato, non un fondo'
    if pct >= PCT_RIDUCE:
        if ha_netti < HA_MIN_UTILE:
            return 'ESCLUSA', f'{pct:.0f}% edificato, residuo {ha_netti:.2f} ha: sotto la soglia utile'
        return 'RIDOTTA', f'{pct:.0f}% edificato: utili {ha_netti:.2f} ha su {ha:.2f}'
    d = occ.get('d_edificio_esterno_m')
    if d is not None and d <= D_PERTINENZA_M:
        return 'CAUTELA', (f'fabbricato a {d:.0f} m dal confine: nessun divieto di legge, '
                           f'ma pertinenza da rispettare e rischio accettabilita\'')
    return 'LIBERA', 'nessun fabbricato catastale sulla particella'


def screening(parcels, controlli=None, px=700, verbose=True):
    """parcels: {id: {'anello': [[lat,lon],...], 'ha': float}} -> report per id.

    `controlli` = {'edificata': id, 'libera': id}: due particelle a esito noto.
    Se il controllo positivo non risulta edificato la misura non sta funzionando
    e il report esce marcato inaffidabile invece di essere creduto.
    """
    out = {}
    for pid, p in parcels.items():
        ring = p.get('anello') or p.get('ring') or p.get('poly')
        ha = p.get('ha') or 0
        try:
            occ = analizza(ring, px=px)
        except Exception as e:
            occ = None
            if verbose:
                print(f'  {pid}: ERRORE {e}')
        v, motivo = verdetto(occ, ha)
        out[pid] = {'ha': ha, 'verdetto': v, 'motivo': motivo, 'occupazione': occ}
        if verbose:
            pc = f"{occ['pct_edificato']:5.1f}%" if occ else '   n.d.'
            print(f'  {pid:>10s} {ha:6.2f} ha  edif {pc}  -> {v}: {motivo}')
        time.sleep(0.2)

    esito = {'parcelle': out, 'controlli': None, 'affidabile': None}
    if controlli:
        ce, cl = controlli.get('edificata'), controlli.get('libera')
        pe = out.get(ce, {}).get('occupazione')
        pl = out.get(cl, {}).get('occupazione')
        ok = bool(pe and pl and pe['pct_edificato'] >= PCT_RIDUCE
                  and pl['pct_edificato'] < PCT_RIDUCE)
        esito['controlli'] = {
            'edificata': {'id': ce, 'pct': pe['pct_edificato'] if pe else None},
            'libera': {'id': cl, 'pct': pl['pct_edificato'] if pl else None}}
        esito['affidabile'] = ok
        if verbose:
            print(f"\ncontrolli: {ce}={pe['pct_edificato'] if pe else 'n.d.'}% (atteso alto) | "
                  f"{cl}={pl['pct_edificato'] if pl else 'n.d.'}% (atteso ~0) -> "
                  f"{'MISURA ATTENDIBILE' if ok else 'MISURA NON ATTENDIBILE'}")
    elif verbose:
        print('\nATTENZIONE: nessun controllo passato, esito non validato')
    return esito


def screening_due_stadi(parcels, mosaico, soglia=PCT_RIDUCE, px=900, verbose=True):
    """Mosaico per scremare, GetMap dedicata per decidere.

    Il mosaico sbaglia per eccesso (vedi Mosaico): chi sta sotto soglia e'
    libero davvero e non si ricontrolla; chi la supera viene rimisurato a piena
    risoluzione, perche' escludere una particella buona costa quanto tenerne
    una cattiva. Restituisce {id: {ha, pct, verdetto, motivo, stadio}}.
    """
    sospette = {}
    out = {}
    for pid, p in parcels.items():
        ring = p.get('anello') or p.get('ring') or p.get('poly')
        ha = p.get('ha') or 0
        pm = mosaico.pct(ring)
        if pm is None:
            out[pid] = {'ha': ha, 'pct': None, 'verdetto': 'NON_VERIFICATO',
                        'motivo': 'fuori dal mosaico', 'stadio': 'mosaico'}
        elif pm < soglia:
            v, m = verdetto({'pct_edificato': pm, 'd_edificio_esterno_m': None}, ha)
            out[pid] = {'ha': ha, 'pct': pm, 'verdetto': v, 'motivo': m, 'stadio': 'mosaico'}
        else:
            sospette[pid] = (ring, ha, pm)

    if verbose:
        print(f'stadio 1 (mosaico): {len(parcels)} particelle -> {len(sospette)} da rimisurare')
    for n, (pid, (ring, ha, pm)) in enumerate(sospette.items(), 1):
        try:
            occ = analizza(ring, px=px, distanza=False)
        except Exception as e:
            occ = None
            if verbose:
                print(f'  {pid}: ERRORE {e}')
        v, m = verdetto(occ, ha)
        out[pid] = {'ha': ha, 'pct': occ['pct_edificato'] if occ else None,
                    'pct_mosaico': pm, 'verdetto': v, 'motivo': m, 'stadio': 'preciso'}
        if verbose and n % 25 == 0:
            print(f'  ...{n}/{len(sospette)}')
        time.sleep(0.15)
    return out


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--parcels', required=True, help='JSON {id:{anello,ha}}')
    ap.add_argument('--out', default=None)
    ap.add_argument('--ctrl-edificata', default=None)
    ap.add_argument('--ctrl-libera', default=None)
    A = ap.parse_args()
    P = json.load(open(A.parcels, encoding='utf-8'))
    c = None
    if A.ctrl_edificata and A.ctrl_libera:
        c = {'edificata': A.ctrl_edificata, 'libera': A.ctrl_libera}
    r = screening(P, controlli=c)
    if A.out:
        json.dump(r, open(A.out, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        print('salvato', A.out)
