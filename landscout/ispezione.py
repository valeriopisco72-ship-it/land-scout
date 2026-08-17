# -*- coding: utf-8 -*-
"""land-scout ispezione — quello che l'immagine dice e i layer non dicono.

Dalla Fase 34 il tool produce sempre i fogli-contatti satellitari. Ma li guarda
un essere umano, e solo se se lo ricorda: **un'immagine prodotta e mai letta e'
un controllo che non esiste**. Ogni volta che qualcuno le ha guardate davvero ha
trovato qualcosa — il nastro lungo il torrente di Fg82/117, le strade che
attraversavano il blocco F, le case dentro il perimetro di Morcone. Tutte cose
che i vincoli e il catasto non potevano vedere.

## Cosa fa questo modulo, e cosa NON pretende di fare

Non classifica il terreno. Su un'ortofoto RGB senza infrarosso non si distingue
in modo affidabile un pascolo da un prato, e chi lo afferma sta vendendo fumo.
Quello che si puo' fare, e che serve davvero, e' **confrontare due fonti che
dovrebbero concordare** e segnalare quando non lo fanno:

  * il layer chioma (Copernicus TCD, 10 m, anno 2018) dice 3% di alberi e
    l'immagine mostra una macchia scura e tessiturata sul 40% della particella
    → o il layer e' vecchio, o e' sbagliato. In ogni caso **quella particella va
    guardata prima delle altre**;
  * `occupazione` dice LIBERA e nell'immagine c'e' un tetto → il catasto
    fabbricati non l'aveva, ma qualcosa c'e';
  * il blocco e' dichiarato "campo" e l'immagine mostra una superficie uniforme
    e scura su meta' della sua estensione.

L'esito non e' un verdetto: e' una **coda di ispezione ordinata**, con
l'immagine ritagliata accanto a ogni riga. Il tool dice dove guardare, l'occhio
decide. E' l'unico patto onesto possibile con un'euristica su tre canali.

## Limiti dichiarati, che vanno letti prima dei numeri

1. **L'ortofoto Esri non ha una data.** E' un mosaico di riprese diverse: non si
   puo' dire "al 2026 c'erano alberi", si puo' dire "nell'immagine disponibile
   ci sono alberi". Se il layer e l'immagine discordano, non e' detto che sia il
   layer a sbagliare — puo' essere l'immagine a essere piu' vecchia.
2. **Ombre e stagione ingannano.** Un versante in ombra a gennaio somiglia a un
   bosco. Per questo la soglia di segnalazione e' alta e il modulo non esclude
   mai una particella da solo.
3. **Le euristiche sono su RGB.** Nessun NDVI, nessuna classificazione: verde
   relativo, luminosita', tessitura locale. Bastano a ordinare, non a decidere.

Uso:
    from landscout import ispezione
    R = ispezione.controlla(blocco['particelle'], vincoli=vinc, occupazione=occ)
    print(ispezione.print_report(R))
    ispezione.esporta_ritagli(R, 'out/ispezione')
"""
import math
import os

# soglie: alte di proposito. Una segnalazione che si ignora e' peggio di nessuna.
VERDE_SCURO_ALLARME = 0.35     # quota di pixel "chioma-simile" che fa scattare il confronto
SCARTO_CHIOMA = 25.0           # punti percentuali di differenza col layer TCD
TETTO_ALLARME = 0.02           # quota di pixel "manufatto" su una particella dichiarata libera
Z_DEFAULT = 18

# ── soglie del rilevatore di manufatti, TARATE, non scelte ──────────────────
# La prima versione usava (r>g+12, r>b+12, lum>80) e sul blocco vero di Morcone
# ha segnalato 35 particelle su 37: classificava come laterizio il **terreno
# arato bruno-rossastro**, che li' e' ovunque. Il test sintetico non l'aveva
# preso perche' usava un campo verde, non uno arato — l'errore stava nel
# fixture, non nel codice.
# Taratura del 10/08/2026 contro il catasto fabbricati AdE (l'unico riferimento
# indipendente disponibile) su 37 particelle: 35 senza fabbricati, 1 con il
# 13,3% (Fg69/772).
#     (12,12, 80)  max 92,2% sui puliti   17 falsi positivi su 35
#     (25,35, 90)  max 12,7%               2 falsi positivi
#     (35,50, 95)  max  0,3%   e 9,0% sul vero   ZERO falsi positivi  <- scelta
#     (45,65,100)  max  0,1%   ma 1,6% sul vero: perde il segnale
TETTO_DR, TETTO_DG, TETTO_LUM = 35, 50, 95

# ── soglie del rilevatore di chioma, TARATE il 12/08/2026 ───────────────────
# Stesso errore del rilevatore di tetti, nell'altra direzione. La prima
# versione usava (verde > 8, luminanza < 95) e sulle 18 particelle candidate
# del blocco di Morcone dichiarava 94% di copertura arborea su un prato aperto
# con alberi solo lungo il bordo (83_979) e 88% su un frutteto giovane a filari
# (70_641). Nelle ortofoto Esri l'erba di un pascolo e' verde scuro quanto una
# chioma: la soglia a 95 la contava tutta. Anche qui il test sintetico non
# l'aveva preso, perche' il suo "campo" era un verde molto piu' chiaro
# dell'erba vera.
# Taratura su 46 particelle in tre gruppi a verita' nota per costruzione:
# A = boschi 142-g SITAP con TCD>=60% (devono leggere alto), B = particelle con
# TCD<=5% (devono leggere basso), C = le 18 candidate (si misura il BIAS medio
# rispetto a Copernicus TCD, che e' una misura indipendente della stessa cosa).
#     (verde>8,  lum<95)  A 99,7%  B 43,1%  bias +34,8   <- vecchia
#     (verde>8,  lum<85)  A 98,4%  B 31,9%  bias +22,4
#     (verde>12, lum<78)  A 94,7%  B 22,1%  bias  +5,2
#     (verde>12, lum<72)  A 91,9%  B 18,5%  bias  -0,0    <- scelta
#     (verde>12, lum<66)  A 84,0%  B 10,4%  bias  -8,8: comincia a perdere i boschi
# Controllo a vista sui ritagli: 83_979 passa da 96% a 14% (prato con bordo
# alberato), 70_705 da 86% a 42% (radura dentro il bosco), 70_641 da 90% a 42%
# (frutteto). I boschi veri restano fra il 52% e il 97%.
CHIOMA_VERDE, CHIOMA_LUM = 12, 72


class ImmagineNonDisponibile(RuntimeError):
    """Nessun tile: la particella resta NON ispezionata, mai 'pulita'."""


def _tile_mosaico(anello, z=Z_DEFAULT, pad=0.00035):
    """Mosaico Esri attorno all'anello + funzione di proiezione pixel."""
    from PIL import Image
    from . import satcheck as SC
    lats = [q[0] for q in anello]
    lons = [q[1] for q in anello]
    x0, y0 = SC.deg2tile(max(lats) + pad, min(lons) - pad, z)
    x1, y1 = SC.deg2tile(min(lats) - pad, max(lons) + pad, z)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 64:
        raise ImmagineNonDisponibile('area troppo grande per un ritaglio per particella')
    img = Image.new('RGB', ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            img.paste(SC.get_tile(z, tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))

    def px(la, lo):
        x, y = SC.deg2tile(la, lo, z)
        return ((x - tx0) * 256, (y - ty0) * 256)
    return img, px


def _maschera(img, anello, px):
    """Maschera booleana dei pixel DENTRO il poligono (ray casting su griglia)."""
    import numpy as np
    from PIL import Image, ImageDraw
    m = Image.new('L', img.size, 0)
    ImageDraw.Draw(m).polygon([px(a, b) for a, b in anello], fill=255)
    return np.array(m) > 0


def indicatori(img, mask):
    """Indicatori RGB dentro la maschera. Nessuno di questi e' una classificazione."""
    import numpy as np
    a = np.asarray(img).astype('float32')
    if not mask.any():
        return None
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = (r + g + b) / 3.0
    # verde relativo: quanto il canale G supera gli altri due
    verde = g - (r + b) / 2.0
    dentro = mask
    n = int(dentro.sum())

    # tessitura: scarto locale della luminanza (3x3 approssimato per differenze)
    dx = np.zeros_like(lum); dy = np.zeros_like(lum)
    dx[:, 1:] = np.abs(lum[:, 1:] - lum[:, :-1])
    dy[1:, :] = np.abs(lum[1:, :] - lum[:-1, :])
    tess = (dx + dy) / 2.0

    # verde SATURO e scuro: chioma. Le due soglie sono tarate (vedi in testa):
    # con lum<95 l'erba di un pascolo contava come bosco.
    chioma = (verde > CHIOMA_VERDE) & (lum < CHIOMA_LUM)
    prato = (verde > 8) & ~chioma              # verde ma non chioma: erba/colture
    nudo = (verde <= 8) & (lum >= 90)          # arato/secco/strade
    # laterizio: rosso SATURO e chiaro. Le soglie sono tarate (vedi in testa),
    # perche' il terreno arato di Morcone e' bruno-rossastro e passava per tetto.
    manufatto = (r > g + TETTO_DR) & (r > b + TETTO_DG) & (lum > TETTO_LUM)
    return {
        'pixel': n,
        'chioma_pct': round(100.0 * float((chioma & dentro).sum()) / n, 1),
        'prato_pct': round(100.0 * float((prato & dentro).sum()) / n, 1),
        'nudo_pct': round(100.0 * float((nudo & dentro).sum()) / n, 1),
        'manufatto_pct': round(100.0 * float((manufatto & dentro).sum()) / n, 1),
        'luminanza': round(float(lum[dentro].mean()), 1),
        'tessitura': round(float(tess[dentro].mean()), 2),
        'uniformita': round(float(1.0 / (1.0 + tess[dentro].mean())), 3),
    }


def confronta(ind, tcd_pct=None, occupazione=None, coltura=None):
    """Discordanze fra cio' che i layer dichiarano e cio' che l'immagine mostra."""
    segn = []
    if ind is None:
        return segn
    if tcd_pct is not None and ind['chioma_pct'] - tcd_pct > SCARTO_CHIOMA:
        segn.append({
            'tipo': 'chioma', 'gravita': 'alta',
            'testo': (f"l'immagine mostra {ind['chioma_pct']:.0f}% di copertura arborea, "
                      f"il layer Copernicus ne dichiara {tcd_pct:.0f}% "
                      f"(+{ind['chioma_pct'] - tcd_pct:.0f} punti)")})
    elif tcd_pct is None and ind['chioma_pct'] >= 100 * VERDE_SCURO_ALLARME:
        # senza il layer non c'e' DISCORDANZA, c'e' una lacuna: si segnala come
        # 'da confrontare', e non entra nella coda dei sospetti — altrimenti la
        # coda si riempie di righe che non dicono niente e nessuno la legge piu'.
        segn.append({
            'tipo': 'chioma_non_confrontabile', 'gravita': 'nota',
            'testo': (f"l'immagine mostra {ind['chioma_pct']:.0f}% di copertura arborea: "
                      f"il layer Copernicus non e stato letto qui, non c'e nulla da "
                      f"confrontare")})
    verd = (occupazione or {}).get('verdetto')
    if verd in ('LIBERA', 'RIDOTTA') and ind['manufatto_pct'] > 100 * TETTO_ALLARME:
        segn.append({
            'tipo': 'edificato', 'gravita': 'alta',
            'testo': (f"occupazione dichiara {verd} ma l'immagine ha "
                      f"{ind['manufatto_pct']:.1f}% di pixel da manufatto: verificare "
                      f"il catasto fabbricati")})
    if coltura and str(coltura).lower().startswith(('semin', 'aperta')) \
            and ind['chioma_pct'] > 30:
        segn.append({
            'tipo': 'coltura', 'gravita': 'media',
            'testo': (f"la visura dice '{coltura}' ma l'immagine e alberata al "
                      f"{ind['chioma_pct']:.0f}%")})
    return segn


def controlla(particelle, vincoli=None, occupazione=None, chioma=None, colture=None,
              z=Z_DEFAULT, verbose=True, _mosaico=None):
    """Ispeziona ogni particella e restituisce la coda ordinata per sospetto."""
    mos = _mosaico or _tile_mosaico
    out, errori = {}, []
    for i, p in enumerate(particelle, 1):
        k = f"{p['fg']}_{p['pla']}"
        anello = p.get('poly') or p.get('anello')
        if not anello:
            out[k] = {'ispezionata': False, 'motivo': 'nessuna geometria'}
            continue
        try:
            img, px = mos(anello, z=z)
            mask = _maschera(img, anello, px)
            ind = indicatori(img, mask)
        except Exception as e:
            out[k] = {'ispezionata': False, 'motivo': f'{type(e).__name__}: {str(e)[:50]}'}
            errori.append(k)
            continue
        tcd = ((chioma or {}).get(k) or {}).get('pct')
        segn = confronta(ind, tcd_pct=tcd,
                         occupazione=(occupazione or {}).get(k),
                         coltura=(colture or {}).get(k))
        out[k] = {'ispezionata': True, 'indicatori': ind, 'segnalazioni': segn,
                  'sospetto': sum({'alta': 3, 'media': 1}.get(s['gravita'], 0) for s in segn),
                  'ha': p.get('netti') or p.get('ha')}
        if verbose:
            stato = f"{len(segn)} segnalazioni" if segn else 'ok'
            print(f"  [{i:3d}/{len(particelle)}] {k:<10s} chioma {ind['chioma_pct']:5.1f}% "
                  f"manufatto {ind['manufatto_pct']:4.1f}%  {stato}")
    coda = sorted((k for k, v in out.items() if v.get('sospetto')),
                  key=lambda k: -out[k]['sospetto'])
    n_isp = sum(1 for v in out.values() if v.get('ispezionata'))
    return {
        'particelle': out, 'coda': coda,
        'n_ispezionate': n_isp, 'n_totale': len(out),
        'n_non_ispezionate': len(out) - n_isp, 'errori': errori,
        'n_segnalate': len(coda),
        'nota': ("euristiche RGB su ortofoto SENZA DATA: servono a ordinare le "
                 "verifiche a vista, non a decidere. Una discordanza puo' voler dire "
                 "che il layer sbaglia oppure che l'immagine e' piu' vecchia del layer."),
    }


def rischi(R):
    out = []
    alte = [k for k in R['coda']
            if any(s['gravita'] == 'alta' for s in R['particelle'][k]['segnalazioni'])]
    if alte:
        out.append(f"{len(alte)} particelle con DISCORDANZA fra layer e immagine "
                   f"satellitare ({', '.join(alte[:5])}"
                   f"{'...' if len(alte) > 5 else ''}): da guardare a vista prima di offrire")
    if R['n_non_ispezionate']:
        out.append(f"{R['n_non_ispezionate']} particelle NON ispezionate "
                   f"(nessuna immagine): l'occupazione reale resta non verificata a vista")
    return out


def esporta_ritagli(particelle, R, out_dir, top=12, z=Z_DEFAULT):
    """Salva il ritaglio delle particelle segnalate: la riga senza l'immagine non serve."""
    from PIL import ImageDraw
    os.makedirs(out_dir, exist_ok=True)
    idx = {f"{p['fg']}_{p['pla']}": p for p in particelle}
    file = []
    for k in R['coda'][:top]:
        p = idx.get(k)
        anello = (p or {}).get('poly') or (p or {}).get('anello')
        if not anello:
            continue
        try:
            img, px = _tile_mosaico(anello, z=z)
            dr = ImageDraw.Draw(img)
            pts = [px(a, b) for a, b in anello]
            dr.line(pts + [pts[0]], fill=(255, 60, 30), width=4)
            xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
            m = 40
            img = img.crop((max(0, int(min(xs)) - m), max(0, int(min(ys)) - m),
                            min(img.size[0], int(max(xs)) + m),
                            min(img.size[1], int(max(ys)) + m)))
            f = os.path.join(out_dir, f'{k}.png')
            img.save(f)
            file.append(f)
        except Exception:
            continue
    return file


def print_report(R, top=15):
    L = [f"ISPEZIONE SATELLITARE: {R['n_ispezionate']}/{R['n_totale']} particelle · "
         f"{R['n_segnalate']} con discordanze"]
    for k in R['coda'][:top]:
        v = R['particelle'][k]
        i = v['indicatori']
        L.append(f"  {k:<10s} {v.get('ha') or 0:5.2f} ha · chioma img {i['chioma_pct']:5.1f}% "
                 f"· manufatto {i['manufatto_pct']:4.1f}% · tessitura {i['tessitura']:5.2f}")
        for s in v['segnalazioni']:
            L.append(f"       [{s['gravita']:<5s}] {s['testo']}")
    if R['n_non_ispezionate']:
        L.append(f"  ? {R['n_non_ispezionate']} non ispezionate: {', '.join(R['errori'][:6])}")
    L.append('  ' + R['nota'])
    return '\n'.join(L)


def main():
    import argparse
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Controllo a vista delle particelle di un blocco.')
    ap.add_argument('--blocco', required=True, help='blocco.json prodotto da esporta()')
    ap.add_argument('--out', default=None, help='cartella per i ritagli segnalati')
    ap.add_argument('--top', type=int, default=12)
    A = ap.parse_args()
    d = json.load(open(A.blocco, encoding='utf-8'))
    part = (d.get('blocco') or {}).get('particelle') or d
    R = controlla(part)
    print(print_report(R, top=A.top))
    for r in rischi(R):
        print('  ! ' + r)
    if A.out:
        f = esporta_ritagli(part, R, A.out, top=A.top)
        print(f'\nritagli scritti: {len(f)} in {A.out}')


if __name__ == '__main__':
    main()
