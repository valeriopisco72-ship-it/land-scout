"""land-scout — FORBICE DI VERIFICA: quanto vale un voto costruito su controlli mancanti.

Perche' esiste (28/09/2026)
---------------------------
Nella graduatoria dello scan un 8,2 con il PAI verificato pulito e un 8,2 con il
PAI non raggiunto sono lo stesso numero. Il secondo puo' diventare 2,5 alla prima
consultazione di IdroGEO. Il flag "PAI NON verificato" c'e', ma sta in fondo a
una lista — e chi ordina per voto guarda il numero.

Il principio del tool e' che una fonte muta non e' un'assenza di vincoli. Qui lo
si porta dal flag al NUMERO: per ogni particella si ricalcola il voto nei due
scenari estremi — ogni lacuna sfavorevole, ogni lacuna favorevole — e si
ordinano le lacune per quanto pesano, prima quelle che possono BLOCCARE.

    voto 8,2  [2,5 – 8,6]  · verifica prima: PAI frane/idraulica (puo' bloccare)

Non inventa vincoli e non li toglie: il voto attuale resta quello del motore.
Dice fin dove puo' muoversi, e quale telefonata (o quale rilancio) fare prima.

Due famiglie di lacune:
  - FONTI: controlli che il tool fa da solo e che in questa esecuzione non hanno
    risposto (EEA, IdroGEO, Carta Habitat, SITAP, DEM, Overpass). Si rilancia.
  - CONTROLLI: indicatori v0.2 che nessuna fonte automatica popola (EUAP, aree
    non idonee, incendi, colture storiche...). Di default si ELENCANO soltanto
    (`mai_controllati`), per non trasformare ogni particella d'Italia in "fragile";
    con `completa=True` entrano nella forbice.

CLI:
  .venv/Scripts/python -m landscout.forbice --scan demo/scan_zonaA.json [--top 20] [--completa]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from landscout.engine import score_parcel, voto_10, _distanza

# I campi SITAP letti da engine.score_parcel (fascia_lago/fiume possono venire anche da OSM)
CAMPI_PAESAGGIO = ('usi_civici', 'bosco_142g', 'tratturo', 'art136', 'fascia_lago', 'fascia_fiume')


def _pai_ignoto(p, tech):
    # chiave ASSENTE = non controllato: il motore la tratta come -1 ("controllato,
    # nulla") per compatibilita', la forbice no — e' proprio il buco che deve mostrare
    return bool(p.get('pai_incompleto')) or p.get('pai_fr') is None or p.get('pai_idr') is None


def _paesaggio_ignoto(p, tech):
    return bool(p.get('paesaggio_incompleto')) or all(p.get(k) is None for k in CAMPI_PAESAGGIO[:4])


# (chiave, etichetta, tipo, ignota(p, tech), peggio(p, tech), meglio(p, tech))
# L'ordine conta a parita' di peso: prima le fonti che bastano rilanciare.
LACUNE = (
    ('pai', 'PAI frane/idraulica (IdroGEO)', 'fonte', _pai_ignoto,
     lambda p, t: {'pai_fr': 4, 'pai_idr': 3, 'pai_incompleto': False},
     lambda p, t: {'pai_fr': -1, 'pai_idr': 0, 'pai_incompleto': False}),
    ('natura2000', 'Natura 2000 ZPS/SIC (EEA)', 'fonte',
     lambda p, t: p.get('zps_pct') is None,
     lambda p, t: {'zps_pct': 100.0, 'zps_border_m': -1},
     lambda p, t: {'zps_pct': 0.0, 'zps_border_m': 9e9}),
    # il divieto della DGR 617/2024 e' una misura di conservazione DENTRO la ZPS: con la
    # ZPS verificata assente l'habitat ignoto non puo' bloccare, e non va agitato
    ('habitat', 'habitat 6210/6220 (Carta Habitat)', 'fonte',
     lambda p, t: p.get('habitat_ban') is None and (p.get('zps_pct') is None
                                                    or p['zps_pct'] > 0),
     lambda p, t: {'habitat_ban': True},
     lambda p, t: {'habitat_ban': False}),
    ('pendenza', 'pendenza (DEM)', 'fonte',
     lambda p, t: p.get('slope') is None,
     lambda p, t: {'slope': 25.0},
     lambda p, t: {'slope': 0.0}),
    ('paesaggio', 'paesaggio e usi civici (SITAP)', 'fonte', _paesaggio_ignoto,
     lambda p, t: dict({k: True for k in CAMPI_PAESAGGIO}, paesaggio_incompleto=False),
     lambda p, t: dict({k: bool(p.get(k)) for k in CAMPI_PAESAGGIO}, paesaggio_incompleto=False)),
    ('rete', 'distanza dalla stazione elettrica (OSM)', 'fonte',
     lambda p, t: _distanza(p.get('d_se_m')) is None,
     lambda p, t: {'d_se_m': 9e9},
     lambda p, t: {'d_se_m': 0.0, 'd_150kv_m': 0.0}),
    # --- controlli v0.2: nessuna fonte automatica li popola ancora ---
    ('area_protetta', 'parchi/riserve (EUAP)', 'controllo',
     lambda p, t: p.get('area_protetta') is None,
     lambda p, t: {'area_protetta': 'parco/riserva (ipotesi)'},
     lambda p, t: {'area_protetta': False}),
    ('area_non_idonea', 'aree NON idonee (norma statale/regionale)', 'controllo',
     lambda p, t: p.get('area_non_idonea') is None,
     lambda p, t: {'area_non_idonea': True},
     lambda p, t: {'area_non_idonea': False}),
    ('percorsa_fuoco', 'aree percorse dal fuoco (L. 353/2000)', 'controllo',
     lambda p, t: p.get('percorsa_fuoco') is None,
     lambda p, t: {'percorsa_fuoco': True},
     lambda p, t: {'percorsa_fuoco': False}),
    ('coltura_storica', 'vigneti/oliveti storici', 'controllo',
     lambda p, t: t != 'BESS' and p.get('coltura_storica') is None,
     lambda p, t: {'coltura_storica': True},
     lambda p, t: {'coltura_storica': False}),
    ('zona_urbanistica', 'destinazione urbanistica (CDU, Zona E)', 'controllo',
     lambda p, t: p.get('zona_urbanistica') is None,
     lambda p, t: {'zona_urbanistica': 'non agricola (ipotesi)'},
     lambda p, t: {'zona_urbanistica': 'E'}),
    ('d_bene_tutelato_m', 'distanza beni tutelati (500 m)', 'controllo',
     lambda p, t: p.get('d_bene_tutelato_m') is None,
     lambda p, t: {'d_bene_tutelato_m': 100.0},
     lambda p, t: {'d_bene_tutelato_m': 5000.0}),
    ('area_idonea', 'aree idonee (iter accelerato)', 'controllo',
     lambda p, t: p.get('area_idonea') is None and not p.get('area_non_idonea'),
     lambda p, t: {'area_idonea': False},
     lambda p, t: {'area_idonea': True}),
)
_V2 = {k for k, _, tipo, *_ in LACUNE if tipo == 'controllo'}


def _voto(p, tech, agg):
    """Voto 0-10 con l'eventuale aggiustamento del chiamante (le penalita' OSM dello
    scan si applicano DOPO il motore): stesso tetto a 2,5 per i bloccati."""
    s, cl, _ = score_parcel(dict(p), tech)
    s = max(0.0, min(100.0, s + agg))
    if cl == 'D':
        s = min(s, 25.0)
    return voto_10(round(s, 1), cl), cl


def forbice(p, tech='agriPV', aggiustamento=0.0, completa=False):
    """p: dict di engine.score_parcel. Ritorna la forbice di verifica.

    {'voto', 'voto_peggiore', 'voto_migliore', 'robusto', 'bloccanti_ignoti',
     'verifica_prima', 'lacune': [...], 'mai_controllati': [...]}
    Ogni lacuna: chiave, etichetta, tipo, puo_bloccare, voto_se_peggio,
    voto_se_meglio, delta (quanto perde il voto se la lacuna va male).
    """
    base = dict(p)
    voto, cl0 = _voto(base, tech, aggiustamento)
    attive = [(i, L) for i, L in enumerate(LACUNE)
              if L[3](base, tech) and (completa or L[2] == 'fonte')]
    lacune = []
    for i, (k, etichetta, tipo, _ign, peggio, meglio) in attive:
        vp, clp = _voto(dict(base, **peggio(base, tech)), tech, aggiustamento)
        vm, _ = _voto(dict(base, **meglio(base, tech)), tech, aggiustamento)
        lacune.append({'chiave': k, 'etichetta': etichetta, 'tipo': tipo,
                       'puo_bloccare': clp == 'D' and cl0 != 'D',
                       'voto_se_peggio': vp, 'voto_se_meglio': vm,
                       'delta': round(vp - voto, 1), '_i': i})
    # prima cio' che blocca, poi le fonti (basta rilanciare), poi il peso, poi l'ordine
    lacune.sort(key=lambda x: (not x['puo_bloccare'], x['tipo'] != 'fonte', x['delta'], x['_i']))
    for x in lacune:
        x.pop('_i')

    peg, meg = dict(base), dict(base)
    for _i, (k, _e, _t, _ign, peggio, meglio) in attive:
        peg.update(peggio(base, tech))
        meg.update(meglio(base, tech))
    # min/max: i due scenari combinati non possono stare dentro il voto attuale, ma una
    # penalita' "migliore" su una chiave e un bonus su un'altra si compensano in modi
    # che non vale la pena rincorrere — la forbice deve CONTENERE il voto, sempre.
    vpeg = min(_voto(peg, tech, aggiustamento)[0], voto, *(x['voto_se_peggio'] for x in lacune))
    vmeg = max(_voto(meg, tech, aggiustamento)[0], voto, *(x['voto_se_meglio'] for x in lacune))

    mai = [L[1] for L in LACUNE if L[0] in _V2 and L[3](base, tech)
           and L[0] not in ('zona_urbanistica', 'd_bene_tutelato_m', 'area_idonea')]
    return {'voto': voto, 'voto_peggiore': vpeg, 'voto_migliore': vmeg,
            'robusto': not lacune,
            'bloccanti_ignoti': sum(1 for x in lacune if x['puo_bloccare']),
            'verifica_prima': lacune[0]['etichetta'] if lacune else None,
            'lacune': lacune,
            'mai_controllati': [] if completa else mai}


def descrivi(fb):
    """Una riga: 'voto 8.2 [2.5–8.6] · verifica prima: PAI … (puo' bloccare)'."""
    if fb['robusto']:
        return (f"voto {fb['voto']:.1f} · robusto: tutte le fonti automatiche hanno risposto")
    prima = fb['lacune'][0]
    nota = " (puo' bloccare)" if prima['puo_bloccare'] else ''
    return (f"voto {fb['voto']:.1f} [{fb['voto_peggiore']:.1f}–{fb['voto_migliore']:.1f}]"
            f" · verifica prima: {fb['verifica_prima']}{nota}")


def compatta(fb):
    """La forma che viaggia nelle righe dello scan: niente dettagli per-lacuna ridondanti."""
    return {k: fb[k] for k in ('voto', 'voto_peggiore', 'voto_migliore', 'robusto',
                               'bloccanti_ignoti', 'verifica_prima')} | {
        'lacune': [x['chiave'] for x in fb['lacune']]}


def da_riga_scan(r):
    """Riga dello scan -> dict del motore. `n2k_pct` None (o n2k_incompleto) resta None."""
    n2k = r.get('n2k_pct')
    if r.get('n2k_incompleto'):
        n2k = None
    bordo = r.get('n2k_border_m')
    return {'ha': r.get('ha') or 0.0, 'slope': r.get('slope'),
            'zps_pct': n2k,
            'zps_border_m': None if n2k is None else (bordo if bordo is not None else
                                                      (-1 if n2k > 0 else 9e9)),
            'pai_fr': r.get('pai_fr'), 'pai_idr': r.get('pai_idr'),
            'pai_incompleto': bool(r.get('pai_incompleto')),
            'habitat_ban': r.get('habitat_ban'), 'in_sic': r.get('in_sic'),
            'usi_civici': r.get('usi_civici'),
            'd_se_m': r.get('d_se_m'), 'd_150kv_m': r.get('d_150kv_m')}


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Forbice di verifica sulle particelle di uno scan.')
    ap.add_argument('--scan', required=True, help='JSON prodotto da scan.py')
    ap.add_argument('--tech', default=None, help='default: quella dello scan')
    ap.add_argument('--top', type=int, default=20)
    ap.add_argument('--completa', action='store_true',
                    help='includi anche i controlli v0.2 mai eseguiti (EUAP, incendi, ...)')
    A = ap.parse_args(argv)
    d = json.load(open(A.scan, encoding='utf-8'))
    righe = d.get('risultati', d if isinstance(d, list) else [])
    tech = A.tech or d.get('tech') or 'agriPV'
    out = []
    for r in righe:
        fb = forbice(da_riga_scan(r), tech, completa=A.completa)
        out.append((r, fb))
    out.sort(key=lambda x: (-x[1]['voto'], -x[1]['voto_peggiore']))
    fragili = sum(1 for _, fb in out[:A.top] if fb['bloccanti_ignoti'])
    print(f'FORBICE DI VERIFICA — {len(out)} particelle, tech {tech}')
    print(f'  fra le prime {min(A.top, len(out))}: {fragili} con una lacuna che puo\' BLOCCARE\n')
    for r, fb in out[:A.top]:
        print(f"  {r.get('com', '')} Fg.{r.get('fg')} P.{r.get('pla'):<6} {descrivi(fb)}")
    return out


if __name__ == '__main__':
    main()
