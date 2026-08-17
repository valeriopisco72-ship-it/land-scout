# -*- coding: utf-8 -*-
"""land-scout decisione — cosa verificare per primo, e perche'.

Il tool sa produrre fatti. Ne produce tanti: vincoli, pendenza, rete, firme,
precedenti, prezzo. Alla fine di un'analisi di Morcone escono sette righe di
rischio, tutte vere, tutte sullo stesso piano, in ordine di modulo. Chi legge
deve capire da solo **quale di quelle righe puo' chiudere la partita** e quale
costa solo qualche euro in piu' di cavidotto. E' esattamente il lavoro che uno
strumento dovrebbe togliere di mezzo.

Questo modulo fa una cosa sola, e la fa in modo dichiarato: ordina le verifiche
per **valore dell'informazione**.

    prima le domande che costano poco e possono chiudere la partita

Non e' un principio inventato per l'occasione: e' come lavora chiunque faccia
due diligence. Una visura da 5 euro che puo' rivelare un uso civico vale piu' di
tre settimane di studio di produzione su un terreno che forse non e' vendibile.
Il criterio e' esplicito e i suoi ingredienti sono visibili riga per riga:

  · **killer**  — se l'esito e' negativo il progetto NON esiste (non "costa di
                  piu'": non esiste);
  · **costo**   — ore o euro per avere la risposta, dichiarati come STIMA;
  · **stato**   — verificato / non verificato / gia' violato.

Le tre cose insieme danno l'ordine. Un killer non verificato che costa mezz'ora
sta davanti a tutto. Un costo noto e accettato non sta in coda alle verifiche:
sta nel prezzo.

## Cosa NON fa

Non decide. Non dice "compra" o "lascia": dice cosa sapere prima di decidere, e
cosa succede se non lo si sa. E non inventa esiti: una verifica non fatta resta
non fatta anche se il resto va bene — anzi, e' proprio quando tutto il resto va
bene che una verifica saltata fa il danno peggiore.

I costi in ore sono **stime dichiarate**, non tariffe rilevate: servono a
ordinare, non a preventivare.

Uso:
    from landscout import decisione as DEC
    D = DEC.valuta(blocco_json, comune='Morcone', prov='BN')
    print(DEC.print_decisione(D))
"""
import json
import os

# ---------------------------------------------------------------------------
# Catalogo delle domande che contano. Ogni voce dichiara: se puo' uccidere il
# progetto, quanto costa rispondere (STIMA in ore), e cosa succede se e' vera.
# I riferimenti sono quelli verificati sul campo a Morcone fra luglio e agosto
# 2026 — dove manca un riferimento, il campo `fonte` resta None e si vede.
# ---------------------------------------------------------------------------
CATALOGO = [
    {'id': 'habitat', 'killer': True, 'ore': 0.5,
     'domanda': 'il terreno e su habitat 6210(*) o 6220*?',
     'come': 'carta habitat regionale (il tool la interroga) + conferma nel sentito',
     'se_vero': ('divieto di modifica della destinazione d uso: niente agriPV e '
                 'niente BESS. Non e un costo, e la fine del progetto su quella '
                 'particella'),
     'fonte': 'DGR Campania 617/2024; rigetto CUP 31 Morcone (sentito Parco prot. 558/2026)'},
    {'id': 'area_protetta', 'killer': True, 'ore': 1.0,
     'domanda': 'la particella ricade dentro un parco nazionale o regionale?',
     'come': 'cartografia allegata al decreto istitutivo + certificato di destinazione urbanistica',
     'se_vero': ('cambia l ente che rilascia il sentito e le aree idonee si '
                 'riducono; in zona 1 o 2 un impianto non passa'),
     'fonte': 'DM MASE 101 del 22/04/2025 (Parco Nazionale del Matese)'},
    {'id': 'titolo', 'killer': True, 'ore': 2.0,
     'domanda': 'chi e il proprietario, e il titolo e libero (usi civici, enfiteusi, comproprieta)?',
     'come': 'visure catastali e ipotecarie sulle particelle del blocco',
     'se_vero': ('un uso civico o un enfiteusi non affrancato blocca la vendita '
                 'finche non si affranca; una comproprieta moltiplica le firme'),
     'fonte': 'visure — costo materiale pochi euro a particella'},
    {'id': 'rete', 'killer': True, 'ore': 8.0,
     'domanda': 'c e capacita di connessione sul nodo, o la coda e satura?',
     'come': 'richiesta al gestore di rete; le code per nodo NON sono pubbliche',
     'se_vero': 'un terreno perfetto su un nodo saturo non vale niente',
     'fonte': 'capacita.py: aree critiche e-Distribuzione; le code Terna non sono a macchina'},
    {'id': 'fuoco', 'killer': True, 'ore': 1.0,
     'domanda': 'l area e stata percorsa dal fuoco negli ultimi 15 anni?',
     'come': 'catasto incendi comunale (EFFIS vede solo da ~30 ha in su)',
     'se_vero': 'divieto di cambio di destinazione per 15 anni, edificazione per 10',
     'fonte': 'L. 353/2000 art. 10 c. 1'},
    {'id': 'bosco', 'killer': False, 'ore': 1.0,
     'domanda': 'quanta superficie del blocco e bosco ai sensi del 142-g?',
     'come': 'SITAP + qualita colturale in visura + verifica a vista',
     'se_vero': ('non si libera tagliando: il ceduo tagliato resta bosco. Serve '
                 'trasformazione del bosco, autorizzazione discrezionale'),
     'fonte': 'art. 3 c.3 e art. 8 D.Lgs 34/2018; art. 142 c.1 g) D.Lgs 42/2004'},
    {'id': 'cdu', 'killer': False, 'ore': 2.0,
     'domanda': 'qual e la zonizzazione urbanistica, e fa scattare un criterio di idoneita?',
     'come': 'certificato di destinazione urbanistica o WebGIS comunale',
     'se_vero': ('agricolo entro 500 m da zona industriale = area idonea ex art. 20 '
                 'c.8 lett. c-ter: e la strada su cui e passato il 20 MWp di RWE a '
                 'Pontelandolfo'),
     'fonte': 'D.Lgs 199/2021 art. 20 c.8 c-ter; DD Campania 43 del 20/02/2026'},
    {'id': 'firme', 'killer': False, 'ore': 0.0,
     'domanda': 'quante controparti servono per ettaro?',
     'come': 'gia calcolato dal blocco (e dalle visure, se ci sono)',
     'se_vero': 'sopra ~1,3 controparti per ettaro il blocco esiste sulla mappa e non come trattativa',
     'fonte': 'soglia STIMATA, non osservata sul mercato'},
    {'id': 'pai', 'killer': False, 'ore': 0.2,
     'domanda': 'ci sono classi di pericolosita frane o idraulica?',
     'come': 'ISPRA IdroGEO (il tool lo interroga)',
     'se_vero': 'P3/P4 tolgono superficie e complicano il progetto, raramente lo fermano',
     'fonte': 'PAI — Piani di Assetto Idrogeologico'},
    {'id': 'distanza_rete', 'killer': False, 'ore': 0.1,
     'domanda': 'quanto dista la sottostazione?',
     'come': 'gia calcolato (OSM); da confermare col gestore',
     'se_vero': 'oltre ~3 km il cavidotto si mangia il vantaggio: e un costo, non un divieto',
     'fonte': 'coerente con il raggio di caccia.py'},
]

STATI = ('violato', 'non_verificato', 'verificato_ok')


def _voce(vid):
    for v in CATALOGO:
        if v['id'] == vid:
            return v
    raise KeyError(f'domanda sconosciuta: {vid}')


def valuta(stato, comune='', prov='', note=None):
    """`stato`: {id_domanda: 'violato'|'non_verificato'|'verificato_ok'}.

    Tutto cio' che non e' nel dizionario e' **non verificato**: e' il default
    giusto, perche' il default sbagliato (verificato_ok) e' esattamente il modo
    in cui una due diligence si convince da sola.
    """
    stato = dict(stato or {})
    for k, v in stato.items():
        if v not in STATI:
            raise ValueError(f'stato non ammesso per "{k}": {v} (ammessi: {", ".join(STATI)})')
    righe = []
    for v in CATALOGO:
        s = stato.get(v['id'], 'non_verificato')
        righe.append({**v, 'stato': s, 'nota': (note or {}).get(v['id'])})

    violati = [r for r in righe if r['stato'] == 'violato']
    killer_aperti = [r for r in righe if r['killer'] and r['stato'] == 'non_verificato']
    # ORDINE: prima chi puo' chiudere la partita, poi chi costa meno scoprire.
    # A parita', prima le domande gia' violate: sono le uniche il cui esito e'
    # gia' noto, e vanno lette prima di spendere un'ora su qualunque altra cosa.
    def chiave(r):
        return (0 if r['stato'] == 'violato' else 1,
                0 if r['killer'] else 1,
                0 if r['stato'] == 'non_verificato' else 1,
                r['ore'])

    coda = [r for r in sorted(righe, key=chiave) if r['stato'] != 'verificato_ok']

    if violati:
        killer_violati = [r for r in violati if r['killer']]
        if killer_violati:
            giudizio = 'FERMO'
            perche = (f"{killer_violati[0]['domanda']} — esito negativo gia accertato. "
                      f"{killer_violati[0]['se_vero']}")
        else:
            giudizio = 'PROCEDIBILE CON COSTI'
            perche = (f"{len(violati)} vincoli accertati che pesano sul progetto ma non "
                      f"lo fermano: vanno messi nel prezzo, non nelle verifiche")
    elif killer_aperti:
        giudizio = 'DA VERIFICARE'
        perche = (f"{len(killer_aperti)} domande che possono chiudere la partita sono "
                  f"ancora senza risposta; la piu economica costa "
                  f"{min(r['ore'] for r in killer_aperti):g} ore")
    else:
        giudizio = 'NESSUN KILLER APERTO'
        perche = ('tutte le domande che possono fermare il progetto hanno risposta: '
                  'il resto e prezzo e tempo')

    ore_killer = sum(r['ore'] for r in killer_aperti)
    return {'comune': comune, 'prov': prov, 'giudizio': giudizio, 'perche': perche,
            'righe': righe, 'coda': coda, 'violati': violati,
            'killer_aperti': killer_aperti,
            'ore_per_chiudere_i_killer': round(ore_killer, 1),
            'n_non_verificati': sum(1 for r in righe if r['stato'] == 'non_verificato'),
            'nota': ('le ore sono STIME dichiarate, servono a ordinare non a '
                     'preventivare. Una domanda assente dal quadro e NON verificata, '
                     'mai verificata-ok: il default comodo e il modo in cui una due '
                     'diligence si convince da sola.')}


def prossima_mossa(D):
    """La riga sola da fare adesso. Se non ce n'e', lo dice."""
    if not D['coda']:
        return None
    r = D['coda'][0]
    if r['stato'] == 'violato':
        return (f"LEGGI PRIMA QUESTO — {r['domanda']} e gia risolta in negativo: "
                f"{r['se_vero']}")
    return (f"{r['domanda']}  ({r['ore']:g} h stimate, {r['come']})"
            + ('  ⚠ puo chiudere la partita' if r['killer'] else ''))


def da_rischi(rischi, stato=None):
    """Ponte dai `rischi` testuali del blocco allo stato delle domande.

    Due regole, e la seconda e' quella che conta.

    1. Non deduce mai un "verificato_ok" da un silenzio: se una parola chiave
       non compare, la domanda resta come stava.
    2. **Un indizio non e' un verdetto.** Alla prima stesura questo ponte
       leggeva "rete congestionata" come "nessuna capacita" e faceva uscire un
       FERMO che nessuno aveva accertato. Una provincia congestionata rende la
       risposta piu' probabilmente negativa: non la sostituisce. Gli indizi
       finiscono in `note`, la domanda resta aperta.

    Ritorna (stato, note).
    """
    s = dict(stato or {})
    note = {}
    testo = ' '.join(rischi or []).lower()
    if 'habitat' in testo and ('vietat' in testo or 'divieto' in testo):
        s.setdefault('habitat', 'violato')
    elif 'habitat' in testo and 'non verificat' in testo:
        s.setdefault('habitat', 'non_verificato')
    if 'pai' in testo and ('p4' in testo or 'p3' in testo):
        s.setdefault('pai', 'violato')
    if 'nessuna visura' in testo or 'senza visure' in testo:
        s.setdefault('titolo', 'non_verificato')
        note['titolo'] = 'il blocco dichiara di non avere visure: il quadro proprietario e stimato'
    if 'rete alta' in testo or 'congestionat' in testo:
        # INDIZIO, non verdetto: la domanda resta aperta e piu' urgente.
        note['rete'] = ('la provincia risulta congestionata: non e un no, ma alza '
                        'la probabilita che lo sia — motivo in piu per chiedere presto')
    if 'controparti per ettaro' in testo or 'frammentazione alta' in testo:
        s.setdefault('firme', 'violato')
    return s, note


def print_decisione(D, top=10):
    L = [f"DECISIONE — {D['comune']} {D['prov']}".rstrip(),
         f"  {D['giudizio']}: {D['perche']}"]
    if D['killer_aperti']:
        L.append(f"  {D['ore_per_chiudere_i_killer']:g} ore stimate per chiudere TUTTE "
                 f"le domande che possono fermare il progetto")
    L.append('')
    L.append('  DA FARE, IN QUEST ORDINE (prima cio che costa poco e puo chiudere la partita):')
    for i, r in enumerate(D['coda'][:top], 1):
        seg = '✖' if r['stato'] == 'violato' else ('☠' if r['killer'] else '·')
        L.append(f"  {i}. {seg} [{r['ore']:>4.1f} h] {r['domanda']}")
        L.append(f"        come: {r['come']}")
        if r['stato'] == 'violato' and r['killer']:
            L.append(f"        ESITO GIA NEGATIVO: {r['se_vero']}")
        elif r['stato'] == 'violato':
            L.append(f"        ACCERTATO, pesa sul prezzo e sui tempi: {r['se_vero']}")
        elif r['killer']:
            L.append(f"        se va male: {r['se_vero']}")
        if r.get('nota'):
            L.append(f"        nota: {r['nota']}")
        if r.get('fonte'):
            L.append(f"        fonte: {r['fonte']}")
    ok = [r for r in D['righe'] if r['stato'] == 'verificato_ok']
    if ok:
        L.append('')
        L.append('  gia verificate: ' + ', '.join(r['id'] for r in ok))
    L.append('')
    L.append('  ' + D['nota'])
    return '\n'.join(L)


def main():
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description='Cosa verificare per primo su un blocco, e perche.')
    ap.add_argument('--blocco', help='blocco.json prodotto da blocco.esporta')
    ap.add_argument('--comune', default='')
    ap.add_argument('--prov', default='')
    ap.add_argument('--ok', default='', help='domande gia verificate, separate da virgola')
    ap.add_argument('--violate', default='', help='domande con esito negativo accertato')
    A = ap.parse_args()
    stato, note = {}, {}
    if A.blocco and os.path.exists(A.blocco):
        with open(A.blocco, encoding='utf-8') as f:
            b = json.load(f)
        stato, note = da_rischi((b.get('bancabilita') or {}).get('rischi') or [])
    for k in (x.strip() for x in A.ok.split(',') if x.strip()):
        stato[k] = 'verificato_ok'
    for k in (x.strip() for x in A.violate.split(',') if x.strip()):
        stato[k] = 'violato'
    D = valuta(stato, comune=A.comune, prov=A.prov, note=note)
    print(print_decisione(D))
    print()
    print('  PROSSIMA MOSSA: ' + (prossima_mossa(D) or 'nessuna verifica aperta'))


if __name__ == '__main__':
    main()
