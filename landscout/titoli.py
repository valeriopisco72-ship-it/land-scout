# -*- coding: utf-8 -*-
"""land-scout titoli — cosa devi sanare PRIMA di poter far firmare.

`visure.py` risponde a "con chi tratto". Manca la domanda che viene subito dopo,
e che decide il calendario vero: **quella firma, quando puo' materialmente
arrivare?** Perche' un proprietario d'accordo su tutto non firma lo stesso se
c'e' un usufrutto di mezzo, se la successione non e' aperta, se il fondo e' a
enfiteusi, o se gli intestatari sono sette e uno vive in Argentina.

E' la strada critica dell'aggregazione, e nel caso di casa e' gia' successo:
Fg82/78 e Fg82/393 sono a **enfiteusi** — il Convitto Nazionale di Benevento
concedente, l'enfiteuta. Senza affrancazione quella terra non si vende,
per quanto d'accordo siano tutti.

## Regola di questo modulo

Elenca **situazioni** e **azioni**, non articoli da citare in atto. I tempi sono
**stime** dichiarate: servono a mettere le cose in ordine, non a promettere una
data. La verifica sta dal notaio, e il modulo lo scrive in ogni riga che produce.

Uso:
    from landscout import titoli
    T = titoli.analizza(controparti)     # uscita di visure.aggrega()
    print(titoli.print_prerequisiti(T))
"""
import json

# gravita': BLOCCA = senza questo non si firma · RALLENTA = si firma, ma dopo ·
# ATTENZIONE = si firma, ma qualcuno in piu' deve essere d'accordo.
BLOCCA, RALLENTA, ATTENZIONE = 'BLOCCA', 'RALLENTA', 'ATTENZIONE'

# [STIMA] Ordini di grandezza, non promesse. Chiedere al notaio prima di
# metterli in un cronoprogramma che qualcuno leggera' come un impegno.
TEMPI_MESI = {
    'enfiteusi': (3, 12),
    'successione': (2, 8),
    'comproprieta_ampia': (1, 6),
    'usufrutto': (0, 1),
    'persona_giuridica': (0, 1),
    'senza_intestatario': (1, 6),
}


def _voce(tipo, gravita, dove, cosa, azione, mesi, chi='notaio'):
    lo, hi = TEMPI_MESI.get(mesi, (None, None)) if isinstance(mesi, str) else mesi
    return {'tipo': tipo, 'gravita': gravita, 'dove': dove, 'cosa': cosa,
            'azione': azione, 'mesi_stimati': [lo, hi], 'verifica': chi,
            'nota': 'tempi STIMATI: la verifica e del notaio, non di questo tool'}


def analizza(controparti, min_comproprietari=4):
    """controparti = uscita di `visure.aggrega()` -> prerequisiti alla firma."""
    voci = []

    # 1. enfiteusi / livello: due titolari, e senza il concedente non si vende
    for x in (controparti.get('titoli_da_sanare') or []):
        sogg = ', '.join(f"{s['nome']} ({s['diritto']})" for s in x.get('soggetti', []))
        voci.append(_voce(
            'enfiteusi', BLOCCA, f"Fg{x['fg']}/{x['pla']}",
            f'enfiteusi o livello: {sogg}',
            'affrancare (art. 971 c.c.) oppure far intervenire in atto il concedente. '
            'Finche non e affrancato il fondo NON e liberamente vendibile',
            'enfiteusi'))

    # 2. particelle del blocco senza intestatario noto
    for k in (controparti.get('senza_intestatari') or []):
        dove = f'Fg{k[0]}/{k[1]}' if isinstance(k, (list, tuple)) else str(k)
        voci.append(_voce(
            'senza_intestatario', BLOCCA, dove,
            'nessun intestatario leggibile nella visura',
            'riscaricare la visura per immobile; se manca davvero, e tipicamente una '
            'SUCCESSIONE NON APERTA: serve la denuncia di successione prima di poter firmare',
            'senza_intestatario'))

    # 3. particelle attese e mai coperte da una visura
    manc = controparti.get('particelle_mancanti') or []
    if manc:
        voci.append(_voce(
            'visura_mancante', RALLENTA,
            ', '.join(f'Fg{a}/{b}' for a, b in manc[:6]) + ('...' if len(manc) > 6 else ''),
            f'{len(manc)} particelle del blocco senza visura',
            'scaricarle dall area riservata: finche mancano, quelle firme non sono '
            'nemmeno contate', (0, 1), chi='tu'))

    # 4. usufrutto / diritti di godimento: si firma, ma non da soli
    for c in (controparti.get('controparti') or []):
        if c.get('solo_diritti_deboli'):
            voci.append(_voce(
                'usufrutto', ATTENZIONE, c['nome'],
                'titolare di soli diritti di godimento (usufrutto/uso/abitazione): '
                'zero ettari in proprieta, ma il consenso serve lo stesso',
                'farlo intervenire in atto. Per un contratto trentennale il suo '
                'consenso e necessario anche se non incassa il prezzo',
                'usufrutto'))
        if c.get('persona_giuridica'):
            voci.append(_voce(
                'persona_giuridica', ATTENZIONE, c['nome'],
                'controparte e una persona giuridica',
                'visura camerale aggiornata + verifica dei poteri di firma di chi si '
                'presenta: chi tratta puo non essere chi puo obbligare la societa',
                'persona_giuridica', chi='notaio/camerale'))

    # 5. comproprieta' ampia sulla stessa particella: serve l'unanimita'
    per_part = {}
    for c in (controparti.get('controparti') or []):
        for d in (c.get('dettaglio') or []):
            per_part.setdefault((str(d['fg']), str(d['pla'])), set()).add(c['nome'])
    for (fg, pla), chi in sorted(per_part.items()):
        if len(chi) >= min_comproprietari:
            voci.append(_voce(
                'comproprieta_ampia', RALLENTA, f'Fg{fg}/{pla}',
                f'{len(chi)} comproprietari sulla stessa particella',
                'serve il consenso di TUTTI: un solo irreperibile ferma la particella. '
                'Valutare se il blocco regge senza, prima di investirci mesi',
                'comproprieta_ampia', chi='tu'))

    ordine = {BLOCCA: 0, RALLENTA: 1, ATTENZIONE: 2}
    voci.sort(key=lambda v: (ordine[v['gravita']], -(v['mesi_stimati'][1] or 0)))
    blocca = [v for v in voci if v['gravita'] == BLOCCA]
    mesi_max = max([v['mesi_stimati'][1] or 0 for v in voci], default=0)
    return {'voci': voci, 'n': len(voci),
            'n_bloccanti': len(blocca),
            'mesi_strada_critica': mesi_max or None,
            'nota': ('prerequisiti alla FIRMA, non vincoli del terreno: un fondo '
                     'perfetto con la successione non aperta non si compra lo stesso.')}


def rischi(T):
    """Righe pronte per la bancabilita' del blocco."""
    out = []
    for v in T['voci']:
        if v['gravita'] == BLOCCA:
            out.append(f"TITOLO {v['dove']}: {v['cosa']} -> {v['azione'].split('.')[0]} "
                       f"(stima {v['mesi_stimati'][0]}-{v['mesi_stimati'][1]} mesi)")
    if T['n_bloccanti']:
        out.append(f"strada critica dei titoli: ~{T['mesi_strada_critica']} mesi stimati "
                   f"prima che {T['n_bloccanti']} firme siano materialmente possibili")
    return out


def print_prerequisiti(T, top=20):
    L = [f"PREREQUISITI ALLA FIRMA: {T['n']} voci "
         f"({T['n_bloccanti']} bloccanti)"
         + (f" · strada critica ~{T['mesi_strada_critica']} mesi [STIMA]"
            if T['mesi_strada_critica'] else '')]
    for v in T['voci'][:top]:
        lo, hi = v['mesi_stimati']
        tempo = f'{lo}-{hi} mesi' if hi else 'n.d.'
        L.append(f"  [{v['gravita']:<10s}] {v['dove'][:28]:<28s} {v['cosa'][:52]}")
        L.append(f"               -> {v['azione'][:96]}  ({tempo}, {v['verifica']})")
    L.append('  ' + T['nota'])
    return '\n'.join(L)


def main():
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Prerequisiti alla firma, dalle visure.')
    ap.add_argument('--controparti', required=True,
                    help='controparti.json prodotto da blocco.esporta() con --visure')
    ap.add_argument('--out', default=None)
    A = ap.parse_args()
    C = json.load(open(A.controparti, encoding='utf-8'))
    T = analizza(C)
    print(print_prerequisiti(T))
    if A.out:
        json.dump(T, open(A.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\nscritto: {A.out}')


if __name__ == '__main__':
    main()
