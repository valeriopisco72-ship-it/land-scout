# -*- coding: utf-8 -*-
"""Taratura del modello sui precedenti amministrativi gia' decisi.

PERCHE' ESISTE
--------------
L'idea arriva da un progetto di site selection eolico (Wind-Farm-Site-Selection-GIS)
che valida la propria mappa di idoneita' contro ~12.800 turbine gia' costruite: se
il modello dice "ottimo" dove nessuno ha mai installato, il modello e' sbagliato.

Applicata a Morcone l'idea si e' rotta subito — ed e' questo il risultato, non un
fallimento. Le 44 VIncA decise del comune sono:

    14 recinzione · 6 edilizia · 6 taglio_bosco · 2 viabilita'
     2 reti · 2 imboschimento · 1 agricolo · **0 FER**

Zero pratiche di impianto energetico. Il tasso di approvazione locale (35 esiti
favorevoli su 36 pratiche concluse) e' un dato vero e utile, ma NON e' il tasso
di approvazione di un fotovoltaico: e' il tasso con cui il Parco del Matese
autorizza recinzioni anti-cinghiale e tagli boschivi.

Questo modulo esiste per rendere quella distinzione impossibile da perdere.
Ogni numero che produce viaggia con la propria BASE (su cosa e' misurato) e la
propria TRASFERIBILITA' (a cosa e' lecito applicarlo). Un numero non trasferibile
non viene restituito come cifra spendibile: viene restituito come
`non_trasferibile` con la ragione scritta accanto.

Il costo dell'errore opposto e' noto in casa: il target Campolattaro di 180k€
nacque da una banda calcolata sul capex e adoperata come se fosse un prezzo
osservato. Il mercato vero era 40-70k€/ha.

COSA NON FA
-----------
Non calcola un'accuratezza del modello, e non e' un bug. Con 1 solo esito
NEGATIVO su 44 pratiche, un classificatore che risponde sempre "FAVOREVOLE"
otterrebbe il 97% e non saprebbe nulla. Peggio: quell'unico rigetto (CUP C31,
divieto assoluto su habitat 6210/6220) e' la fonte da cui `engine.score_parcel`
ha ricavato la propria regola sugli habitat — misurare il modello su di esso
sarebbe circolare, lo stesso vizio che produce gli R^2 = 0,99 nei repo di ML
geospaziale addestrati e validati sullo stesso raster.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import precedenti as PR

# Tipi che il registro assegna a un intervento di produzione/accumulo di energia.
# `precedenti.classifica()` li ricava dall'OGGETTO della pratica, mai dagli
# allegati: le misure di conservazione allegate a ogni fascicolo nominano
# impianti di accumulo e parchi eolici, e classificare sul testo intero faceva
# risultare "pratica FER" una recinzione (cfr. qa_precedenti).
TIPI_FER = ('fer', 'fotovoltaico', 'eolico', 'accumulo', 'bess', 'agrivoltaico', 'agripv')

# Esiti che chiudono una pratica. 'NON CONCLUSA' non entra in nessun tasso:
# una pratica ferma non e' ne' un si' ne' un no.
ESITI_CONCLUSI = ('FAVOREVOLE', 'FAVOREVOLE CON PRESCRIZIONI', 'NEGATIVO')
ESITI_POSITIVI = ('FAVOREVOLE', 'FAVOREVOLE CON PRESCRIZIONI')

# Sotto questa quota di pratiche pertinenti, un tasso non si trasferisce e basta.
# 0.20 non e' una soglia statistica: e' la soglia oltre la quale ci si puo'
# almeno mettere a discutere. Sotto, il numero e' rumore travestito.
QUOTA_MINIMA_PERTINENTE = 0.20


def _tipi(voce):
    """I tipi di una voce, sempre come tupla di stringhe minuscole."""
    t = voce.get('tipo') or []
    if isinstance(t, str):
        t = [t]
    return tuple(str(x).strip().lower() for x in t if str(x).strip())


def e_fer(voce):
    """True se la pratica riguarda un impianto energetico."""
    return any(t in TIPI_FER for t in _tipi(voce))


def base_osservata(comune, prov):
    """Conteggi grezzi dal registro. Nessuna interpretazione, solo somme.

    Ritorna None se il comune non ha un fascicolo letto: un comune senza
    registro non e' un comune senza precedenti, e non deve produrre uno zero.
    """
    voci = PR.cerca(comune, prov)
    if not voci:
        return None

    conclusi = [v for v in voci if v.get('esito') in ESITI_CONCLUSI]
    positivi = [v for v in conclusi if v.get('esito') in ESITI_POSITIVI]
    fer = [v for v in voci if e_fer(v)]

    per_tipo = {}
    for v in voci:
        for t in _tipi(v):
            per_tipo[t] = per_tipo.get(t, 0) + 1

    siti = {}
    for v in voci:
        s = v.get('sito') or 'n/d'
        siti[s] = siti.get(s, 0) + 1

    return {
        'comune': comune, 'prov': prov,
        'pratiche': len(voci),
        'concluse': len(conclusi),
        'non_concluse': len(voci) - len(conclusi),
        'positive': len(positivi),
        'negative': sum(1 for v in conclusi if v['esito'] == 'NEGATIVO'),
        'fer': len(fer),
        'con_particelle': sum(1 for v in voci if v.get('particelle')),
        'per_tipo': per_tipo,
        'siti': siti,
        # dettaglio dei negativi: sono i soli casi che insegnano qualcosa
        'negativi_dettaglio': [
            {'cup': v.get('cup'), 'tipo': _tipi(v),
             'motivo': (v.get('motivo') or '')[:400],
             'georiferito': bool(v.get('particelle'))}
            for v in conclusi if v['esito'] == 'NEGATIVO'
        ],
    }


def trasferibilita(base, tech='BESS'):
    """Il tasso osservato e' applicabile a `tech`? E con che riserva?

    Ritorna un dict con `trasferibile` (bool), `quota_pertinente` (float) e
    `ragione` (str). La ragione e' pensata per finire dentro un report letto da
    una controparte: deve reggere se qualcuno la contesta.
    """
    n = base['pratiche']
    quota = (base['fer'] / n) if n else 0.0

    if base['fer'] == 0:
        return {
            'trasferibile': False, 'quota_pertinente': 0.0,
            'ragione': (
                f"nessuna delle {n} pratiche riguarda un impianto energetico "
                f"(tipi presenti: {', '.join(sorted(base['per_tipo'])) or 'n/d'}). "
                f"Il tasso misura con che frequenza l'ente autorizza interventi "
                f"di altra natura, non un {tech}."),
        }

    if quota < QUOTA_MINIMA_PERTINENTE:
        return {
            'trasferibile': False, 'quota_pertinente': round(quota, 3),
            'ragione': (
                f"solo {base['fer']} pratiche su {n} ({quota:.0%}) riguardano "
                f"impianti: base troppo sottile per un tasso applicabile a {tech}."),
        }

    return {
        'trasferibile': True, 'quota_pertinente': round(quota, 3),
        'ragione': (
            f"{base['fer']} pratiche su {n} ({quota:.0%}) riguardano impianti: "
            f"il tasso e' discutibile come indicazione per {tech}, non come previsione."),
    }


def potere_discriminante(base):
    """Quanto il registro puo' insegnare a un modello.

    Un registro tutto-positivo non discrimina: qualunque modello che dica
    sempre 'passa' lo eguaglia. Qui si dichiara, non si nasconde dietro
    un'accuratezza alta.
    """
    conclusi = base['concluse']
    neg = base['negative']
    if conclusi == 0:
        return {'utilizzabile': False, 'ragione': 'nessuna pratica conclusa'}

    quota_neg = neg / conclusi
    baseline = max(base['positive'], neg) / conclusi  # accuratezza del modello banale

    if neg == 0:
        rag = ('nessun rigetto nel registro: non esiste un caso negativo su cui '
               'misurare un falso positivo.')
    elif neg < 5:
        rag = (f'solo {neg} rigetto/i su {conclusi} pratiche concluse '
               f'({quota_neg:.0%}): un modello che rispondesse sempre "favorevole" '
               f'otterrebbe {baseline:.0%} di accuratezza senza sapere nulla. '
               f'Qualunque metrica di accuratezza su questa base e\' priva di significato.')
    else:
        rag = (f'{neg} rigetti su {conclusi} pratiche concluse ({quota_neg:.0%}): '
               f'base minima per confrontare le predizioni con gli esiti.')

    georif = sum(1 for d in base['negativi_dettaglio'] if d['georiferito'])
    return {
        'utilizzabile': neg >= 5,
        'negativi': neg,
        'negativi_georiferiti': georif,
        'baseline_banale': round(baseline, 3),
        'ragione': rag,
    }


def taratura(comune, prov, tech='BESS'):
    """Verdetto completo: cosa il registro dice, e fin dove lo dice."""
    base = base_osservata(comune, prov)
    if base is None:
        return {'disponibile': False,
                'ragione': f'nessun fascicolo VIncA letto per {comune} ({prov}). '
                           f'Non equivale ad assenza di precedenti.'}

    tr = trasferibilita(base, tech)
    pd = potere_discriminante(base)

    tasso = (base['positive'] / base['concluse']) if base['concluse'] else None

    return {
        'disponibile': True,
        'base': base,
        'tech': tech,
        'trasferibilita': tr,
        'potere_discriminante': pd,
        # il numero esiste sempre; e' il suo USO che viene vincolato
        'tasso_positivo': round(tasso, 3) if tasso is not None else None,
        'tasso_spendibile': round(tasso, 3) if (tasso is not None and tr['trasferibile']) else None,
    }


def argomenti_trattativa(T):
    """Cosa si puo' dire a una controparte, e cosa no.

    La seconda lista conta piu' della prima: sono le frasi che suonano bene e
    non reggono a una verifica, cioe' quelle che fanno perdere credibilita' nel
    momento peggiore.
    """
    if not T.get('disponibile'):
        return {'difendibili': [], 'da_non_dire': [], 'nota': T.get('ragione')}

    b, tr, pd = T['base'], T['trasferibilita'], T['potere_discriminante']
    sito_top = max(b['siti'].items(), key=lambda kv: kv[1]) if b['siti'] else ('n/d', 0)

    ok = [
        f"[osservato] Su {b['concluse']} pratiche VIncA concluse a {b['comune']} "
        f"({b['prov']}), {b['positive']} hanno avuto esito favorevole e "
        f"{b['negative']} negativo.",
        f"[osservato] {sito_top[1]} delle {b['pratiche']} pratiche insistono su "
        f"{sito_top[0]}: l'ente istruisce regolarmente dentro il sito Natura 2000, "
        f"la presenza del vincolo non chiude l'istruttoria in partenza.",
    ]
    if b['non_concluse']:
        ok.append(
            f"[osservato] {b['non_concluse']} pratiche risultano non concluse: "
            f"il rischio locale e' il tempo di istruttoria, non il diniego.")

    for d in b['negativi_dettaglio']:
        ok.append(f"[osservato] L'unico diniego (CUP {d['cup']}, "
                  f"{'/'.join(d['tipo']) or 'tipo n/d'}) e' motivato cosi': "
                  f"{d['motivo'][:180]}")

    no = []
    if not tr['trasferibile']:
        pct = T['tasso_positivo']
        no.append(
            f"NON dire «qui il {pct:.0%} delle pratiche passa, quindi passera' "
            f"anche il nostro {T['tech']}»: {tr['ragione']}")
    if not pd['utilizzabile']:
        no.append(f"NON presentare il modello come «validato sui precedenti»: {pd['ragione']}")
    if b['negative'] and not any(d['georiferito'] for d in b['negativi_dettaglio']):
        no.append(
            "NON dire «il diniego riguardava un'altra zona»: l'unico rigetto non "
            "ha particelle indicate nel fascicolo, quindi non e' collocabile sul "
            "territorio ne' a favore ne' contro.")

    return {'difendibili': ok, 'da_non_dire': no, 'nota': None}


def print_taratura(T):
    """Report leggibile. Ritorna la stringa (i test la ispezionano)."""
    if not T.get('disponibile'):
        s = f"TARATURA SUI PRECEDENTI — non disponibile\n  {T.get('ragione')}"
        print(s)
        return s

    b, tr, pd = T['base'], T['trasferibilita'], T['potere_discriminante']
    A = argomenti_trattativa(T)
    L = []
    L.append('=' * 74)
    L.append(f"  TARATURA SUI PRECEDENTI — {b['comune']} ({b['prov']})  ·  tech: {T['tech']}")
    L.append('=' * 74)
    L.append(f"  pratiche registrate .......... {b['pratiche']}")
    L.append(f"    di cui concluse ........... {b['concluse']}  "
             f"({b['positive']} favorevoli, {b['negative']} negative)")
    L.append(f"    non concluse .............. {b['non_concluse']}")
    L.append(f"    con particelle indicate ... {b['con_particelle']}")
    L.append(f"    su impianti energetici .... {b['fer']}")
    L.append('')
    L.append('  tipi di intervento:')
    for t, n in sorted(b['per_tipo'].items(), key=lambda kv: -kv[1]):
        L.append(f"    {n:3d}  {t}")
    L.append('')
    if T['tasso_positivo'] is not None:
        L.append(f"  tasso di esito favorevole ..... {T['tasso_positivo']:.0%}  [osservato]")
    L.append(f"  spendibile per {T['tech']}? ......... "
             f"{'SI' if tr['trasferibile'] else 'NO'}")
    L.append(f"    -> {tr['ragione']}")
    L.append('')
    L.append(f"  potere discriminante .......... "
             f"{'utilizzabile' if pd['utilizzabile'] else 'INSUFFICIENTE'}")
    L.append(f"    -> {pd['ragione']}")
    L.append('')
    L.append('  ARGOMENTI DIFENDIBILI:')
    for a in A['difendibili']:
        L.append(f"    · {a}")
    if A['da_non_dire']:
        L.append('')
        L.append('  DA NON DIRE:')
        for a in A['da_non_dire']:
            L.append(f"    ! {a}")
    L.append('=' * 74)
    s = '\n'.join(L)
    print(s)
    return s


def main():
    import argparse
    p = argparse.ArgumentParser(description='Taratura del modello sui precedenti VIncA')
    p.add_argument('comune', nargs='?', default='Morcone')
    p.add_argument('prov', nargs='?', default='BN')
    p.add_argument('--tech', default='BESS')
    a = p.parse_args()
    print_taratura(taratura(a.comune, a.prov, a.tech))


if __name__ == '__main__':
    main()
