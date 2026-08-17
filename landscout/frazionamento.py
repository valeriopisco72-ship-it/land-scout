"""land-scout frazionamento — quante FAMIGLIE, non quante particelle.

Intuizione di Valerio, guardando un blocco compatto da 89 particelle: *"magari
non sono 89 controparti ma 89 particelle che sono di pochi proprietari"*.

Ha ragione, e il dato per verificarlo in parte c'e' gia' nel numero di
particella. Quando un fondo viene diviso — successione, donazione, vendita
parziale — il catasto assegna ai pezzi **numeri consecutivi o ravvicinati sullo
stesso foglio**. Una sequenza come Fg82 40-41-46-50-51-52-54-55-57 non nasce per
caso: e' un fondo unico frazionato, e chi lo ha ereditato e' quasi sempre lo
stesso ceppo familiare.

⚠️ **E' un INDIZIO, non una prova.** Numeri vicini possono anche appartenere a
compratori diversi dello stesso frazionamento. Il modulo produce quindi una
**stima ottimistica** (limite inferiore delle controparti) da usare accanto al
conteggio per particella (limite superiore): la verita' sta in mezzo, e solo le
visure la fissano. Nessuna decisione economica va presa su questa stima da sola.

Uso:
    from landscout import frazionamento
    s = frazionamento.stima(blk['particelle'])
    frazionamento.print_stima(s)
"""
import re
from collections import defaultdict

# Due particelle dello stesso foglio con numeri entro questa distanza sono
# probabilmente figlie dello stesso frazionamento. Stretto di proposito: allargarlo
# fonde ceppi diversi e fa sembrare il deal piu' facile di quanto sia.
SALTO_MAX = 6


def _num(pla):
    m = re.match(r'^(\d+)', str(pla))
    return int(m.group(1)) if m else None


def gruppi(particelle, salto_max=SALTO_MAX, solo_da_acquisire=True):
    """Raggruppa per foglio + vicinanza di numero.

    Solo particelle CONTIGUE fra loro finiscono nello stesso gruppo: due fondi
    con numeri vicini ma lontani sul terreno non sono lo stesso frazionamento.
    """
    sel = [p for p in particelle
           if not (solo_da_acquisire and p.get('ancora'))]
    per_fg = defaultdict(list)
    for p in sel:
        n = _num(p['pla'])
        if n is not None:
            per_fg[str(p['fg'])].append((n, p))

    out = []
    for fg, lst in sorted(per_fg.items()):
        lst.sort(key=lambda t: t[0])
        cur = [lst[0]]
        for prev, nxt in zip(lst, lst[1:]):
            if nxt[0] - prev[0] <= salto_max:
                cur.append(nxt)
            else:
                out.append((fg, cur))
                cur = [nxt]
        out.append((fg, cur))
    return [{'fg': fg, 'particelle': [p for _, p in g],
             'numeri': [n for n, _ in g],
             'ha': round(sum(p.get('netti') or 0 for _, p in g), 3)}
            for fg, g in out]


def stima(particelle, salto_max=SALTO_MAX):
    """Stima OTTIMISTICA delle controparti (limite inferiore).

    Restituisce anche il limite superiore (una particella = un proprietario), per
    non lasciare mai la stima da sola.
    """
    g = gruppi(particelle, salto_max)
    n_part = sum(len(x['particelle']) for x in g)
    n_grp = len(g)
    multipli = [x for x in g if len(x['particelle']) > 1]
    return {
        'particelle_da_acquisire': n_part,
        'controparti_max': n_part,            # una particella, un proprietario
        'controparti_min_stimate': n_grp,     # ogni frazionamento, una famiglia
        'riduzione_pct': round(100 * (1 - n_grp / n_part), 0) if n_part else 0,
        'gruppi_multipli': sorted(multipli, key=lambda x: -len(x['particelle'])),
        'ha_in_gruppi_multipli': round(sum(x['ha'] for x in multipli), 2),
        'salto_max': salto_max,
        'nota': ('STIMA da numerazione catastale, non da visura: numeri vicini sullo '
                 'stesso foglio indicano un frazionamento, ma possono essere finiti a '
                 'compratori diversi. Il vero numero sta fra il minimo e il massimo, e '
                 'solo le visure lo fissano.'),
    }


def print_stima(s, top=8):
    print('\n=== CONTROPARTI: quante FAMIGLIE, non quante particelle ===')
    print(f"  {s['particelle_da_acquisire']} particelle da acquisire")
    print(f"  controparti: da ~{s['controparti_min_stimate']} (se ogni frazionamento "
          f"e' una famiglia) a {s['controparti_max']} (una per particella)")
    if s['riduzione_pct']:
        print(f"  la numerazione catastale suggerisce fino a -{s['riduzione_pct']:.0f}% "
              f"di controparti")
    if s['gruppi_multipli']:
        print(f"  frazionamenti riconosciuti ({len(s['gruppi_multipli'])}, "
              f"{s['ha_in_gruppi_multipli']} ha):")
        for x in s['gruppi_multipli'][:top]:
            nums = '-'.join(str(n) for n in x['numeri'])
            print(f"    Fg{x['fg']}: {nums}  ({len(x['particelle'])} part., {x['ha']} ha)")
    print(f"  ~ {s['nota']}")
