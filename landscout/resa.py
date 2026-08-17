"""land-scout — modulo RESA (v0.1, 15/07/2026): quanta energia produce il terreno.

Interroga PVGIS (JRC Commissione Europea, gratuito, copre tutta Europa) per la
resa specifica del sito e la traduce in: MWp installabili, MWh/anno, ricavi lordi
stimati dell'impianto.

Configurazioni:
  agriPV  -> tracker monoassiale inclinato (inclined_axis) = agrivoltaico avanzato
             (moduli elevati su tracker, quello usato da RWE a Morcone)
  PV      -> fisso ad angolo ottimale
Nota: PVGIS restituisce SIA 'fixed' SIA la chiave del tracking: va letta quella giusta.

I ricavi sono dell'IMPIANTO (quindi del developer), non del proprietario: servono a
capire la torta su cui si negozia il valore della terra.

CLI:
  .venv/Scripts/python -m landscout.resa --lat 42.333 --lon 13.711 --ha 12.28 --tech agriPV
"""
import argparse, json, math, os, sys, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
from landscout.config import EP, UA, TIMEOUT, MWP_HA, EUR_MWH
from landscout.cache import JsonCache

API = EP['pvgis']
LOSS_DEFAULT = 14           # perdite di sistema % (default PVGIS)


def pvgis(lat, lon, tech='agriPV', loss=LOSS_DEFAULT, use_cache=True):
    """Resa specifica del sito. Ritorna dict o {'error':...}.
    agriPV -> tracker 1 asse inclinato; PV -> fisso ottimale."""
    key = f'{round(lat,3)},{round(lon,3)}|{tech}|{loss}'
    c = JsonCache('pvgis') if use_cache else None
    if c is not None:
        hit = c.get(key)
        if hit is not None:
            return hit
    p = {'lat': lat, 'lon': lon, 'peakpower': 1, 'loss': loss, 'outputformat': 'json',
         'pvtechchoice': 'crystSi', 'mountingplace': 'free'}
    if tech == 'agriPV':
        p.update({'inclined_axis': 1, 'inclined_optimum': 1}); want = 'inclined_axis'
        conf = 'tracker monoassiale inclinato (agrivoltaico avanzato)'
    else:
        p.update({'optimalangles': 1}); want = 'fixed'
        conf = 'fisso ad angolo ottimale'
    try:
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(API + '?' + urllib.parse.urlencode(p), headers=UA), timeout=TIMEOUT).read().decode())
    except Exception as e:
        return {'error': str(e)[:160]}
    tot = d.get('outputs', {}).get('totals', {})
    blk = tot.get(want) or tot.get('fixed')
    if not blk:
        return {'error': 'risposta PVGIS senza totals'}
    out = {'kwh_per_kwp': round(blk.get('E_y', 0), 1),
           'irraggiamento_kwh_m2': round(blk.get('H(i)_y', 0), 1),
           'perdite_pct': blk.get('l_total'),
           'config': conf, 'fonte': 'PVGIS v5.2 (JRC-EU)',
           'db': d.get('inputs', {}).get('meteo_data', {}).get('radiation_db')}
    if c is not None:
        c.set(key, out)
    return out


def resa_terreno(ha, lat, lon, tech='agriPV', loss=LOSS_DEFAULT):
    """Da ettari a MWp / MWh anno / ricavi impianto (banda)."""
    y = pvgis(lat, lon, tech=tech, loss=loss)
    if 'error' in y:
        return {'error': y['error']}
    lo, hi = MWP_HA.get(tech, MWP_HA['agriPV'])
    mwp = (ha * lo, ha * hi)
    kk = y['kwh_per_kwp']
    mwh = (mwp[0] * 1000 * kk / 1000, mwp[1] * 1000 * kk / 1000)   # MWh/anno
    ric = (mwh[0] * EUR_MWH[0], mwh[1] * EUR_MWH[1])
    return {**y, 'ha': round(ha, 2), 'tech': tech,
            'mwp': (round(mwp[0], 1), round(mwp[1], 1)),
            'mwh_anno': (round(mwh[0]), round(mwh[1])),
            'ricavi_impianto_eur_anno': (round(ric[0]/1000)*1000, round(ric[1]/1000)*1000),
            'eur_mwh_ipotesi': EUR_MWH}


def print_resa(r):
    if 'error' in r:
        print('  ! PVGIS non raggiungibile:', r['error']); return
    e = lambda x: ('€{:,}'.format(int(x))).replace(',', '.')
    print('=' * 74)
    print(f'  RESA ENERGETICA DEL TERRENO — {r["ha"]} ha · {r["tech"]}')
    print('=' * 74)
    print(f'  Configurazione ...... {r["config"]}')
    print(f'  Resa specifica ...... {r["kwh_per_kwp"]} kWh/kWp/anno   (irragg. {r["irraggiamento_kwh_m2"]} kWh/m²)')
    print(f'  Potenza installabile  {r["mwp"][0]}–{r["mwp"][1]} MWp   ({MWP_HA[r["tech"]][0]}–{MWP_HA[r["tech"]][1]} MWp/ha)')
    print(f'  Produzione .......... {r["mwh_anno"][0]:,}–{r["mwh_anno"][1]:,} MWh/anno'.replace(',', '.'))
    print(f'  Ricavi IMPIANTO ..... {e(r["ricavi_impianto_eur_anno"][0])}–{e(r["ricavi_impianto_eur_anno"][1])}/anno '
          f'(ipotesi {r["eur_mwh_ipotesi"][0]}–{r["eur_mwh_ipotesi"][1]} €/MWh)')
    print(f'  Fonte ............... {r["fonte"]}' + (f' · db {r["db"]}' if r.get('db') else ''))
    print('  NB: i ricavi sono dell\'impianto (del developer), NON del proprietario:')
    print('      servono a dimensionare la torta su cui si negozia il valore della terra.')
    print('=' * 74)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lat', type=float); ap.add_argument('--lon', type=float)
    ap.add_argument('--ha', type=float)
    ap.add_argument('--tech', default='agriPV', choices=['agriPV', 'PV'])
    ap.add_argument('--parcels', help='JSON {id:{lat,lon,ha}} — usa centroide e somma ha')
    ap.add_argument('--out')
    A = ap.parse_args()
    if A.parcels:
        p = json.load(open(A.parcels, encoding='utf-8'))
        lat = sum(v['lat'] for v in p.values())/len(p); lon = sum(v['lon'] for v in p.values())/len(p)
        ha = sum(v['ha'] for v in p.values())
    else:
        lat, lon, ha = A.lat, A.lon, A.ha
    if lat is None or ha is None:
        print('Uso: --lat --lon --ha [--tech]  oppure  --parcels file.json'); return
    r = resa_terreno(ha, lat, lon, A.tech)
    print_resa(r)
    if A.out and 'error' not in r:
        json.dump(r, open(A.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('salvato:', A.out)


if __name__ == '__main__':
    main()
