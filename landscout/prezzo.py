"""land-scout prezzo — quanto posso offrire a QUESTO proprietario.

Il tool sapeva dire quanto vale il blocco. Non sapeva dire la cosa che serve
davvero quando si alza il telefono: **a questa persona, quanto offro.**

UN PARAMETRO INVENTATO PUO' PRODURRE UN VERDETTO FALSO
------------------------------------------------------
La prima versione di questo modulo fissava a mano una "quota del valore RTB
destinata alla terra" (10-18%) e da li' ricavava un tetto. Su Morcone ne usciva
**6.457 EUR/ha: meta' del valore agricolo del fondo** — e la conclusione
"il deal non regge". Ma quel numero non veniva da nessuna fonte: l'avevo scelto
io, e il verdetto stava in piedi solo grazie a lui.

Adesso il verso e' rovesciato. Il prezzo si ancora al **mercato osservato**
(VAM come pavimento, prassi di settore come riferimento) e la quota di valore
RTB assorbita dalla terra diventa un **risultato da guardare**, non un'ipotesi
da assumere. Se quella quota e' alta, il modulo non dice "la terra costa
troppo": dice che il problema e' la **densita'** del progetto.

TRE NUMERI, NON UNO
-------------------
- **Pavimento**: VAM, il valore agricolo ufficiale. E' un valore di esproprio e
  sta sotto il mercato: come pavimento va bene, come prezzo no.
- **Minimo credibile**: pavimento x moltiplicatore di opzionalita'. Sotto
  questa soglia nessuno cede un fondo che come campo vale di piu'.
- **Mercato**: la prassi per terreni con potenziale rinnovabile.

IL PREZZO DEVE ESSERE UNIFORME (e questa e' la parte che conta)
--------------------------------------------------------------
La tentazione dell'aggregatore e' pagare di piu' chi ha il fondo pivotale.
Tecnicamente e' razionale. In un comune di 5.000 abitanti e' **il modo piu'
veloce per far saltare tutto**: i vicini si parlano, e chi scopre di aver preso
meno del cugino non rinegozia — si sfila, e porta via anche gli altri.

Quindi: **un unico EUR/ha per tutti**. La leva negoziale si usa sull'**ordine
delle telefonate**, non sul prezzo. Un premio si giustifica solo se sapresti
spiegarlo al vicino (una servitu' di passaggio, il fondo che ospita la cabina);
uno che dovresti nascondere e' un premio che non puoi permetterti.

VENDITA O CANONE
----------------
Per l'agrivoltaico la forma normale non e' la vendita ma la **concessione
30ennale**: il comparabile RWE-Pontelandolfo e' un canone, non un prezzo. Il
modulo calcola entrambi e non lascia confondere le due cose.

Uso:
    from landscout import prezzo
    P = prezzo.piano(blocco, controparti=C, prov='BN', mwp=8.9)
    prezzo.print_piano(P)
"""

# Mercato osservato per terreni con potenziale rinnovabile (DD Morcone 06/07/2026:
# fonti di settore 2025-26; i comparabili locali confermano che il range esiste).
EUR_HA_MERCATO_RINNOVABILI = (25_000, 50_000)   # vendita
EUR_HA_ANNO_MERCATO = (1_500, 3_000)            # canone standard; punte 4.000-8.000
EUR_MWP_RTB = (72_000, 150_000)                 # progetto FV/agriPV autorizzato
MOLT_OPZIONALITA = (1.5, 2.5)                   # quanto si paga sopra l'agricolo
# Oltre questa quota di valore RTB assorbita dalla terra, al developer non resta
# abbastanza per sviluppo, connessione e margine.
# ⚠ E' una REGOLA EMPIRICA, non una fonte: va calibrata sul comparabile locale.
# Nota utile emersa dai test: ai prezzi di mercato dichiarati dalle fonti di
# settore (25-50 k EUR/ha) l'allarme scatta a QUALUNQUE densita' realistica,
# FV a terra incluso (0,75 MWp/ha -> 45%). Due letture possibili, entrambe da
# tenere aperte: o quei prezzi sono richieste di vendita e non transazioni
# concluse, oppure la terra si compra molto sotto il prezzo esposto. In ogni
# caso il numero da guardare e' il rapporto, non la soglia.
QUOTA_TERRA_ALLARME = 0.35
ANNI_CONCESSIONE = 30
TASSO_ATTUALIZZAZIONE = 0.06


def _b(banda, q):
    return banda[0] + (banda[1] - banda[0]) * q


def pavimento_eur_ha(prov, coltura='seminativo', q=0.5):
    """Valore agricolo di riferimento (VAM). None se la provincia non e' caricata."""
    try:
        from . import vam as VAM
        v = VAM.vam(prov, coltura)
    except Exception:
        v = None
    if not v or not v.get('eur_ha'):
        return {'eur_ha': None, 'verificato': False, 'coltura': coltura,
                'nota': f'VAM non disponibile per {prov}/{coltura}: pavimento NON verificato'}
    lo, hi = v['eur_ha']
    return {'eur_ha': round(_b((lo, hi), q)), 'banda': (lo, hi), 'anno': v.get('anno'),
            'coltura': coltura, 'verificato': True, 'fonte': v.get('fonte'),
            'nota': v.get('nota')}


def canone_equivalente(eur_ha, anni=ANNI_CONCESSIONE, tasso=TASSO_ATTUALIZZAZIONE):
    """Da prezzo di acquisto a canone annuo equivalente.

    Serve a non confrontare mele con pere: il comparabile locale e' un CANONE
    trentennale, non un prezzo di vendita.
    """
    if not eur_ha:
        return None
    a = (1 - (1 + tasso) ** -anni) / tasso
    return {'prezzo_eur_ha': round(eur_ha), 'canone_annuo_eur_ha': round(eur_ha / a),
            'anni': anni, 'tasso': tasso, 'nota': f'{anni} anni al {tasso:.0%}, fattore {a:.2f}'}


def sostenibilita(eur_ha, mwp_per_ha, q=0.5, eur_mwp=EUR_MWP_RTB):
    """Che quota del valore RTB assorbe la terra, a un dato prezzo per ettaro.

    E' la domanda nel verso giusto: non "quanto posso permettermi" (che
    obbligherebbe ad assumere una quota), ma "a questo prezzo di mercato, quanto
    resta al developer". Se la quota e' alta il problema non e' il prezzo della
    terra: e' la DENSITA' del progetto.
    """
    if not (eur_ha and mwp_per_ha):
        return None
    rtb_ha = mwp_per_ha * _b(eur_mwp, q)
    quota = eur_ha / rtb_ha if rtb_ha else None
    return {'eur_ha': round(eur_ha), 'mwp_per_ha': round(mwp_per_ha, 3),
            'rtb_eur_ha': round(rtb_ha), 'quota_rtb': round(quota, 3) if quota else None,
            'allarme': bool(quota and quota > QUOTA_TERRA_ALLARME),
            'nota': (f'quota del valore RTB assorbita dalla terra; sopra '
                     f'{QUOTA_TERRA_ALLARME:.0%} resta poco per sviluppo, connessione e margine')}


def budget_terra(mwp, ha_acquisire, eur_ha, q=0.5):
    """Esborso totale per la terra, dato un prezzo per ettaro."""
    return {'mwp': mwp, 'eur_ha': round(eur_ha), 'ha': round(ha_acquisire, 2),
            'esborso_eur': round(eur_ha * ha_acquisire),
            'eur_per_mwp': round(eur_ha * ha_acquisire / mwp) if mwp else None,
            'nota': 'prezzo per ettaro dal mercato osservato, non da una quota assunta'}


def piano(blocco, controparti=None, prov='BN', coltura='seminativo', mwp=None,
          q=0.5, molt=MOLT_OPZIONALITA, eur_ha=None, ha_installabili=None,
          criticita=None, cabina_satura=False, zona=None, istat_annuo=None):
    """Il piano di offerta, per proprietario se le visure ci sono.

    `eur_ha` = il prezzo che intendi offrire. Se non lo passi si usa il maggiore
    fra minimo credibile e mediana di mercato. Il modulo non impone un tetto: dice
    che quota di valore RTB quel prezzo assorbe, e lascia a te la decisione.
    """
    pav = pavimento_eur_ha(prov, coltura, q)
    base = pav['eur_ha']
    minimo = round(base * _b(molt, q)) if base else None
    # Il "mercato" era una banda nazionale scritta nel codice (25-50k EUR/ha).
    # Dove esiste un atto vicino, quello vale di piu': a Morcone RWE ha comprato
    # nel 2024 a 68.660 EUR/ha, cioe' piu' del DOPPIO del minimo della banda, e il
    # tool continuava a proporre la banda. Un comparabile osservato a poche
    # centinaia di metri batte sempre una media nazionale — e va dichiarato.
    comp = None
    try:
        from . import comparabili as CP
        b = CP.banda(zona, istat_annuo=istat_annuo) if zona else None
        if b and b['locale']:
            comp = b
            mercato = round(_b((b['lo'], b['hi']), q))
        else:
            mercato = round(_b(EUR_HA_MERCATO_RINNOVABILI, q))
    except Exception:
        mercato = round(_b(EUR_HA_MERCATO_RINNOVABILI, q))
    offerta = round(eur_ha) if eur_ha else max(x for x in (minimo, mercato) if x)

    ha_acq = blocco.get('ha_acquisti') or sum(
        p['netti'] for p in blocco['particelle'] if not p.get('ancora'))
    ha_inst = ha_installabili or blocco.get('ha_installabile')
    dens = (mwp / ha_inst) if (mwp and ha_inst) else None
    sost = sostenibilita(offerta, dens, q) if dens else None
    bud = budget_terra(mwp, ha_acq, offerta, q) if mwp else None

    # La terra che gia' controlli non si compra. `aggrega()` mappa TUTTO il blocco,
    # famiglia inclusa: senza questo filtro il piano metteva un comproprietario interno fra le
    # controparti da pagare, e l'esborso totale non tornava con gli ettari da
    # acquisire. Si prezza solo cio' che manca.
    ancore = {(str(p['fg']), str(p['pla'])) for p in blocco['particelle'] if p.get('ancora')}
    righe, per = [], 'proprietario'
    if controparti and controparti.get('controparti'):
        for c in controparti['controparti']:
            det = [d for d in (c.get('dettaglio') or [])
                   if (str(d['fg']), str(d['pla'])) not in ancore]
            ha = (sum(d['ha_quota'] for d in det) if c.get('dettaglio')
                  else c['ha_controllati'])
            if ha <= 0:
                continue                      # possiede solo terra gia' tua
            righe.append({'chi': c['nome'], 'ha': round(ha, 3),
                          'n_particelle': len(det) if c.get('dettaglio') else c['n_particelle'],
                          'quota_blocco_pct': round(100 * ha / ha_acq, 1) if ha_acq else 0,
                          'offerta_eur': round(offerta * ha),
                          'pavimento_eur': round((base or 0) * ha),
                          'pivotale': bool(ha_acq and 100 * ha / ha_acq >= 15),
                          'solo_diritti_deboli': c.get('solo_diritti_deboli')})
    else:
        per = 'particella (visure mancanti: non si sa a CHI offrire)'
        for p_ in blocco['particelle']:
            if p_.get('ancora'):
                continue
            righe.append({'chi': f"Fg{p_['fg']}/{p_['pla']}", 'ha': round(p_['netti'], 3),
                          'n_particelle': 1,
                          'quota_blocco_pct': (round(100 * p_['netti'] / ha_acq, 1)
                                               if ha_acq else 0),
                          'offerta_eur': round(offerta * p_['netti']),
                          'pavimento_eur': round((base or 0) * p_['netti']),
                          'pivotale': False, 'solo_diritti_deboli': None})
    righe.sort(key=lambda r: -r['ha'])
    tot = sum(r['offerta_eur'] for r in righe)

    # ── il TETTO, che questo modulo da solo non aveva ────────────────────────
    # `piano()` diceva quanto offrire partendo dal basso (VAM x opzionalita') e
    # dichiarava che quota di valore RTB assorbe. Non diceva mai quanto il
    # progetto puo' pagare in TUTTO: quel conto stava in offerta.py, scritto la
    # stessa sera e rimasto senza chiamanti. Comporli invece di sceglierne uno
    # e' l'unico modo di non avere due cifre diverse per la stessa domanda.
    tetto = None
    if mwp:
        try:
            from . import offerta as OF
            tetto = OF.tetto_progetto(mwp, criticita=criticita,
                                      cabina_satura=cabina_satura)
        except Exception:
            tetto = None

    avvisi = []
    if tetto:
        m_lo, m_hi = tetto['monte_suolo_eur']
        # i separatori si sistemano SUI NUMERI, non sulla frase: un replace sul
        # testo intero trasforma le virgole della prosa in punti
        _e = lambda v: f'{v:,.0f}'.replace(',', '.')
        if tot > m_hi:
            avvisi.append(
                f"l'esborso proposto ({_e(tot)} EUR) SUPERA il monte suolo che il "
                f"progetto puo' sostenere ({_e(m_lo)}-{_e(m_hi)} EUR, gia' scontato "
                f"per rischio autorizzativo e rete): a questo prezzo il developer "
                f"non compra, o compra e non costruisce")
        elif tot > m_lo:
            avvisi.append(
                f"l'esborso proposto ({_e(tot)} EUR) sta nella meta' ALTA del monte "
                f"suolo sostenibile ({_e(m_lo)}-{_e(m_hi)} EUR): difendibile, ma "
                f"senza margine per rilanci")
    if not pav['verificato']:
        avvisi.append(f"pavimento NON verificato ({pav['nota']}): offerta indicativa, "
                      f"non difendibile in trattativa")
    elif minimo and offerta < minimo:
        avvisi.append(f"offerta ({offerta} EUR/ha) sotto il minimo credibile "
                      f"({minimo} EUR/ha = VAM x opzionalita): nessuno cede a meno di "
                      f"quanto il fondo vale come campo")
    if sost and sost['allarme']:
        avvisi.append(f"la terra assorbe il {sost['quota_rtb']:.0%} del valore RTB "
                      f"({sost['rtb_eur_ha']} EUR/ha a {sost['mwp_per_ha']} MWp/ha): "
                      f"il problema NON e il prezzo della terra ma la DENSITA del progetto "
                      f"— servono piu MWp sugli stessi ettari, o il margine sparisce")
    if not controparti:
        avvisi.append('senza visure il piano e per particella: si sa quanto offrire, '
                      'non a chi, e i cointestatari restano invisibili')
    piv = [r for r in righe if r['pivotale']]
    if piv:
        avvisi.append(f"{len(piv)} controparti pivotali (>=15% del blocco): trattarle per "
                      f"PRIME, ma allo stesso EUR/ha degli altri")

    return {'pavimento': pav, 'minimo_credibile_eur_ha': minimo, 'mercato_eur_ha': mercato,
            'comparabile_locale': comp,
            'offerta_eur_ha': offerta, 'sostenibilita': sost, 'budget': bud,
            'tetto': tetto,
            'ha_da_acquisire': round(ha_acq, 2), 'totale_offerto_eur': tot,
            'canone': canone_equivalente(offerta), 'per': per, 'righe': righe,
            'avvisi': avvisi,
            'regola_uniformita': (
                'un solo EUR/ha per tutti: in un comune piccolo i vicini si parlano, e chi '
                'scopre di aver preso meno non rinegozia — si sfila. La leva negoziale si usa '
                "sull'ORDINE delle telefonate, non sul prezzo.")}


def print_piano(P, top=12):
    def e(x):
        return f'{x:,.0f}'.replace(',', '.')

    print(f"\n=== PIANO DI OFFERTA (per {P['per']}) ===")
    pav = P['pavimento']
    if pav['verificato']:
        print(f"  pavimento agricolo (VAM {pav['anno']}, {pav['coltura']}): "
              f"{e(pav['eur_ha'])} EUR/ha   <- quanto vale come campo")
    else:
        print('  pavimento agricolo: NON VERIFICATO')
    if P['minimo_credibile_eur_ha']:
        print(f"  minimo credibile    : {e(P['minimo_credibile_eur_ha'])} EUR/ha "
              f"(VAM x opzionalita)")
    print(f"  mercato rinnovabili : {e(P['mercato_eur_ha'])} EUR/ha "
          f"(prassi {e(EUR_HA_MERCATO_RINNOVABILI[0])}-{e(EUR_HA_MERCATO_RINNOVABILI[1])})")
    c = P['canone']
    print(f"  --> OFFERTA: {e(P['offerta_eur_ha'])} EUR/ha = canone "
          f"{e(c['canone_annuo_eur_ha'])} EUR/ha/anno per {c['anni']} anni")
    s = P.get('sostenibilita')
    if s:
        print(f"  sostenibilita: la terra assorbe il {s['quota_rtb']:.0%} del valore RTB "
              f"({e(s['rtb_eur_ha'])} EUR/ha a {s['mwp_per_ha']} MWp/ha)")
    print(f"  {P['ha_da_acquisire']} ha da acquisire · esborso totale "
          f"{e(P['totale_offerto_eur'])} EUR")
    print(f"  {'chi':<34s} {'ha':>7s} {'part':>5s} {'offerta':>12s}")
    for r in P['righe'][:top]:
        flag = '  <-- PIVOTALE' if r['pivotale'] else ''
        print(f"  {str(r['chi'])[:34]:<34s} {r['ha']:>7.2f} {r['n_particelle']:>5d} "
              f"{e(r['offerta_eur']):>12s}{flag}")
    if len(P['righe']) > top:
        print(f"  ... e altre {len(P['righe']) - top}")
    for a in P['avvisi']:
        print(f"  ! {a}")
    print(f"  ~ {P['regola_uniformita']}")
