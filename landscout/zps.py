"""land-scout — STUDIO DI FATTIBILITA' ZPS / VInCA per un BLOCCO di particelle.

Perche' un modulo a parte, se `vincoli.py` gia' dice ZPS si'/no per particella:
il progetto non si autorizza una particella alla volta. La domanda vera e'
"questo BLOCCO e' autorizzabile, con quale iter, e con quali argomenti?".
Servono tre cose che lo scoring per-particella non da':

  1. AGGREGAZIONE: quanti ettari del blocco stanno in ZPS, non quante particelle.
     Il 91% di Morcone in ZPS non e' "91 particelle su 100": e' superficie.
  2. La differenza fra DIVIETO e ITER: la DGR Campania 617/2024 vieta il FV a terra
     sugli habitat 6210/6220 IN ZPS. Fuori da quegli habitat la ZPS non vieta:
     impone la VInCA (Dir. Uccelli 2009/147/CE). Confondere le due cose fa scartare
     progetti fattibili — o peggio, promettere progetti vietati.
  3. PRECEDENTI: in una VInCA l'argomento piu' forte e' "in questa stessa ZPS un
     impianto analogo e' gia' passato". Il censimento VIA ce l'ha: qui lo si usa.

Filosofia invariata: fonte che non risponde -> None -> "NON VERIFICATO", mai "pulito".

Uso:
  .venv/Scripts/python -m landscout.zps --parcels <{id:{lat,lon,ha}}.json> --prov BN [--comune Morcone]
"""
import argparse, csv, json, os, sys

from landscout.config import CENSUS, BAN_CODES, norm_prov
from landscout.vincoli import feasibility

# Soglia sotto la quale una frazione di habitat e' rumore di digitalizzazione e non
# un divieto: stessa soglia usata nell'overlay habitat (0,05%).
SOGLIA_HABITAT_PCT = 0.05

RIFERIMENTI = [
    'Dir. 2009/147/CE (Uccelli) — la ZPS tutela l\'avifauna: la VInCA e\' sull\'incidenza, non un divieto',
    'DPR 357/1997 art.5 — procedura di Valutazione di Incidenza (screening / valutazione appropriata)',
    'DGR Campania 617/2024 — FV a terra VIETATO sugli habitat 6210/6220 in ZPS',
    'DM 17/10/2007 — eolico escluso in ZPS (non riguarda agriPV/BESS)',
    'D.Lgs 178/2025 — FV a terra vietato su agricolo: resta l\'agrivoltaico avanzato',
]


def _f(v):
    """None-safe: somma solo cio' che e' stato misurato davvero."""
    return v if isinstance(v, (int, float)) else None


def studio(parcels, prov=None, comune=None, tech='agriPV', vinc=None):
    """parcels: {id: {lat, lon, ha [, anello]}}. vinc: risultato di vincoli.feasibility gia'
    calcolato (passalo per non rifare le chiamate di rete). Ritorna il dict dello studio."""
    if vinc is None:
        vinc = feasibility(parcels, prov=prov)

    ha_tot = sum(p.get('ha') or 0 for p in parcels.values())
    in_zps, fuori_zps, ignote = [], [], []
    ha_zps = 0.0
    ha_ban = 0.0
    ban_parcelle = []
    su_poligono = 0
    fonti_cieche = set()

    for pid, r in vinc.items():
        ha = r.get('ha') or 0
        if r.get('geometria') == 'poligono':
            su_poligono += 1
        if not r.get('n2k_ok'):
            fonti_cieche.add('Natura 2000 (EEA)')
        if r.get('habitat_ok') is False:
            fonti_cieche.add('Carta Habitat')

        z = r.get('zps_pct')
        if z is None:
            ignote.append(pid)
        elif z > 0:
            in_zps.append(pid)
            ha_zps += ha * z / 100.0
        else:
            fuori_zps.append(pid)

        bp = r.get('habitat_ban_pct')
        if bp is not None and bp > SOGLIA_HABITAT_PCT:
            ha_ban += ha * bp / 100.0
            ban_parcelle.append({'id': pid, 'pct': bp, 'ha': round(ha * bp / 100.0, 4),
                                 'habitat': r.get('habitat')})

    # ── VERDETTO DI BLOCCO ────────────────────────────────────────────────────────
    # Ordine deliberato: prima cio' che si e' VISTO (un divieto resta tale anche se
    # il resto e' incerto), poi cio' che non si e' potuto vedere.
    if ha_ban > 0:
        verdetto = 'DIVIETO PARZIALE (habitat 6210/6220)'
        sintesi = (f'{ha_ban:.2f} ha su habitat vietato: li' + ' il FV a terra e\' vietato (DGR 617/2024). '
                   'Il resto del blocco resta lavorabile arretrando il layout.')
    elif ignote and not in_zps:
        verdetto = 'NON VERIFICATO'
        sintesi = 'Le fonti Natura 2000 non hanno risposto: non si puo\' dire ne\' dentro ne\' fuori ZPS.'
    elif in_zps:
        verdetto = 'VInCA NECESSARIA (nessun divieto trovato)'
        sintesi = (f'{ha_zps:.2f} ha in ZPS ({100*ha_zps/ha_tot:.1f}% del blocco) ma 0 ha su habitat vietato: '
                   'la ZPS impone l\'iter di incidenza, non il divieto.')
    else:
        verdetto = 'FUORI ZPS'
        sintesi = 'Nessuna sovrapposizione con ZPS rilevata.'

    # ── ITER richiesto ────────────────────────────────────────────────────────────
    iter_ = []
    if in_zps:
        iter_.append('VInCA: screening di incidenza; se non esclude effetti -> valutazione appropriata (DPR 357/97 art.5)')
        iter_.append('Studio avifaunistico (la ZPS tutela gli uccelli: e\' il cuore della valutazione)')
    if tech != 'BESS':
        iter_.append('Solo AGRIVOLTAICO AVANZATO: il FV a terra su agricolo e\' vietato (D.Lgs 178/2025)')
    if ha_ban > 0:
        iter_.append(f'Arretrare il layout dai {ha_ban:.2f} ha su habitat 6210/6220 (divieto DGR 617/2024)')

    rischi = []
    if in_zps:
        rischi.append('Incidenza su avifauna: e\' il motivo per cui esiste la ZPS — voce di rischio n.1')
    if ha_tot and ha_zps / ha_tot > 0.8:
        rischi.append(f'Blocco quasi interamente in ZPS ({100*ha_zps/ha_tot:.0f}%): nessuna parte "facile" su cui ripiegare')
    if su_poligono < len(vinc):
        rischi.append(f'{len(vinc)-su_poligono} particelle valutate sul CENTROIDE: percentuali per difetto')
    if fonti_cieche:
        rischi.append('Fonti non raggiunte: ' + ', '.join(sorted(fonti_cieche)) + ' — verdetto da riconfermare')

    st = {
        'blocco': {'particelle': len(parcels), 'ha_totali': round(ha_tot, 3),
                   'ha_in_zps': round(ha_zps, 3),
                   'pct_in_zps': round(100 * ha_zps / ha_tot, 1) if ha_tot else None,
                   'particelle_in_zps': len(in_zps), 'particelle_fuori_zps': len(fuori_zps),
                   'particelle_non_verificate': len(ignote)},
        'habitat_vietato': {'ha': round(ha_ban, 4), 'codici_vietati': list(BAN_CODES),
                            'particelle': ban_parcelle},
        'verdetto': verdetto,
        'sintesi': sintesi,
        'iter_richiesto': iter_,
        'rischi': rischi,
        'qualita_dato': {'su_poligono': su_poligono, 'su_centroide': len(vinc) - su_poligono,
                         'fonti_non_raggiunte': sorted(fonti_cieche)},
        'precedenti': precedenti(comune, prov),
        'riferimenti': RIFERIMENTI,
    }
    return st


def precedenti(comune=None, prov=None, limite=12):
    """Progetti del censimento VIA nello stesso comune/provincia.

    In una VInCA il precedente vale piu' di mille pagine: se un impianto analogo e' gia'
    passato nella stessa area protetta, l'incidenza "non significativa" ha un ancoraggio
    concreto. Qui NON si afferma che quei progetti siano stati autorizzati in ZPS: si
    elencano come piste da verificare (il censimento ha il testo, non l'esito VInCA).
    """
    if not os.path.exists(CENSUS):
        return {'disponibile': False, 'motivo': f'censimento VIA non trovato in {CENSUS}', 'progetti': []}
    com = (comune or '').strip().lower()
    pr = norm_prov(prov)
    hit = []
    try:
        with open(CENSUS, encoding='utf-8', errors='replace', newline='') as fh:
            for row in csv.DictReader(fh):
                blob = ' '.join(str(v) for v in row.values() if v).lower()
                if com and com in blob:
                    prossimita = 2
                elif pr and (f' {pr.lower()} ' in f' {blob} ' or f'({pr.lower()})' in blob):
                    prossimita = 1
                else:
                    continue
                # Pertinenza TECNOLOGICA: un parco eolico non e' un precedente utile per
                # l'agrivoltaico in ZPS — l'eolico li' e' vietato a monte (DM 17/10/2007),
                # quindi la sua VInCA non dice nulla su un impianto solare. Vale il contrario
                # per agriPV/FV/accumulo, che affrontano la stessa istruttoria.
                if any(t in blob for t in ('agrivoltaic', 'fotovoltaic', 'solare')):
                    pertinenza, nota = 2, 'pertinente (stessa istruttoria del solare)'
                elif 'accumulo' in blob or 'bess' in blob:
                    pertinenza, nota = 1, 'parzialmente pertinente (accumulo)'
                elif 'eolic' in blob:
                    pertinenza, nota = 0, 'NON pertinente in ZPS: eolico vietato dal DM 17/10/2007'
                else:
                    pertinenza, nota = 1, ''
                rec = {k: row.get(k) for k in list(row)[:6]}
                rec['_pertinenza'] = nota
                hit.append((pertinenza, prossimita, rec))
    except Exception as e:
        return {'disponibile': False, 'motivo': f'censimento illeggibile: {e}', 'progetti': []}
    # prima la pertinenza tecnologica, poi la vicinanza: un FV in provincia vale piu'
    # di un eolico nello stesso comune.
    hit.sort(key=lambda x: (-x[0], -x[1]))
    utili = [h for h in hit if h[0] > 0]
    return {'disponibile': True,
            'nota': 'Piste da verificare: il censimento riporta il progetto, non l\'esito della VInCA.',
            'progetti': [h[2] for h in hit[:limite]],
            'totale_trovati': len(hit),
            'pertinenti_solare': len([h for h in hit if h[0] == 2]),
            'utili': len(utili)}


def print_studio(st):
    b = st['blocco']
    print('\n' + '=' * 78)
    print('  STUDIO DI FATTIBILITA\' ZPS / VInCA — blocco di ' + str(b['particelle']) + ' particelle')
    print('=' * 78)
    print(f"  Superficie totale ........ {b['ha_totali']} ha")
    print(f"  In ZPS ................... {b['ha_in_zps']} ha ({b['pct_in_zps']}%)"
          f"  [{b['particelle_in_zps']} part. dentro, {b['particelle_fuori_zps']} fuori,"
          f" {b['particelle_non_verificate']} non verificate]")
    hv = st['habitat_vietato']
    print(f"  Habitat vietato {'/'.join(hv['codici_vietati'])} ... {hv['ha']} ha"
          + (f"  su {len(hv['particelle'])} particelle" if hv['particelle'] else '  (nessuna)'))
    print(f"\n  VERDETTO: {st['verdetto']}")
    print(f"  {st['sintesi']}")
    if st['iter_richiesto']:
        print('\n  ITER RICHIESTO:')
        for i in st['iter_richiesto']:
            print('   - ' + i)
    if st['rischi']:
        print('\n  RISCHI:')
        for r in st['rischi']:
            print('   ! ' + r)
    q = st['qualita_dato']
    print(f"\n  Qualita' del dato: {q['su_poligono']} su poligono, {q['su_centroide']} su centroide"
          + (('  | fonti NON raggiunte: ' + ', '.join(q['fonti_non_raggiunte'])) if q['fonti_non_raggiunte'] else ''))
    pr = st['precedenti']
    if pr.get('disponibile'):
        print(f"\n  PRECEDENTI in zona: {pr['totale_trovati']} trovati, di cui "
              f"{pr.get('pertinenti_solare', 0)} SOLARI (i soli davvero pertinenti). {pr['nota']}")
        for p in pr['progetti'][:6]:
            nota = p.get('_pertinenza') or ''
            vals = [str(v) for k, v in p.items() if v and k != '_pertinenza']
            print('   · ' + ' | '.join(vals)[:100])
            if nota:
                print('       -> ' + nota)
    else:
        print(f"\n  PRECEDENTI: non disponibili ({pr.get('motivo')})")
    print('\n  Riferimenti:')
    for r in st['riferimenti']:
        print('   § ' + r)
    print()


def main():
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass
    ap = argparse.ArgumentParser(description='Studio di fattibilita ZPS/VInCA per un blocco')
    ap.add_argument('--parcels', required=True, help='JSON {id:{lat,lon,ha[,anello]}}')
    ap.add_argument('--prov', default=None)
    ap.add_argument('--comune', default=None)
    ap.add_argument('--tech', default='agriPV')
    ap.add_argument('--out', default=None)
    A = ap.parse_args()
    parcels = json.load(open(A.parcels, encoding='utf-8'))
    st = studio(parcels, prov=A.prov, comune=A.comune, tech=A.tech)
    print_studio(st)
    if A.out:
        json.dump(st, open(A.out, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        print(f'  salvato: {A.out}')


if __name__ == '__main__':
    main()
