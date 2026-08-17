"""land-scout offerta — quanto posso offrire a QUESTO proprietario.

`valore.py` dice quanto vale il progetto. Questo modulo risponde alla domanda
che si fa sul campo, citofono per citofono: **a questa persona, per questa
particella, che cifra posso mettere sul tavolo restando in margine?**

TRE COSE CHE CAMBIANO IL PREZZO, E NON SONO IL VALORE AGRICOLO
--------------------------------------------------------------
1. **Gli ettari che contano sono quelli INSTALLABILI.** Un fondo per meta'
   sotto erosione o attraversato da una carraia produce meno MWp, e il prezzo
   deve seguire quelli, non i metri quadri di visura. Il tool li ha gia'
   (`installabile.py`): qui si usano.
2. **Chi puo' bloccare il progetto vale di piu'.** Non e' un giudizio morale:
   e' il motivo per cui l'ultimo proprietario di un blocco strappa condizioni
   migliori del primo. Il premio da veto va messo a bilancio *prima*, non
   scoperto in trattativa.
3. **Il tetto e' il margine del progetto, non il valore agricolo.** Il prezzo
   massimo sostenibile scende con la probabilita' autorizzativa e con la
   saturazione della rete: su un nodo saturo il progetto vale meno, quindi si
   puo' offrire meno. Se il tool ignorasse la rete, farebbe offrire cifre che
   il progetto non ripaga.

COSA NON FA
-----------
Non decide la trattativa. Restituisce **tre soglie** — apertura, obiettivo,
massimo sostenibile — perche' un prezzo unico nasconde proprio l'informazione
che serve a trattare: quanto spazio c'e'.

Uso:
    from landscout import offerta
    o = offerta.per_proprietario(controparti, blocco, mwp=8.9, p_auth=0.65,
                                 prov='BN', criticita=3)
    offerta.print_offerte(o)
"""
import csv
import os

try:
    from . import valore as VAL
except ImportError:  # eseguito come script sciolto
    import valore as VAL

# Valore del progetto autorizzato (RTB), gia' in valore.py: 72-150 k€/MWp.
# Da questo si ricava quanto del margine puo' andare al proprietario del suolo.
QUOTA_SUOLO = (0.10, 0.22)     # frazione del valore RTB che tipicamente va al fondo
# Premio per chi puo' bloccare: si applica sopra una soglia di quota del blocco.
PREMIO_VETO = {15: 1.15, 25: 1.30, 40: 1.50}
# Sconto per chi ha solo diritti di godimento: serve il consenso, non si compra terra.
QUOTA_GODIMENTO = 0.15
# Un canone annuo pluriennale, alternativa alla vendita.
ANNI_CONCESSIONE = 30


def _premio(quota_pct):
    p = 1.0
    for soglia, k in sorted(PREMIO_VETO.items()):
        if quota_pct >= soglia:
            p = k
    return p


def tetto_progetto(mwp, p_auth=0.65, criticita=None, cabina_satura=False):
    """Quanto vale il suolo dell'intero progetto, al netto del rischio.

    Il valore RTB e' il prezzo di un progetto *autorizzato*: moltiplicarlo per
    la probabilita' autorizzativa e' il minimo. La rete entra come secondo
    sconto perche' agisce su un rischio diverso — si puo' avere l'autorizzazione
    e non riuscire a connettersi.
    """
    lo, hi = VAL.EUR_MWP_RTB
    v_lo, v_hi = lo * mwp * p_auth, hi * mwp * p_auth

    sconto, motivi = 1.0, []
    if criticita is not None and criticita >= 4:
        sconto *= 0.70
        motivi.append('provincia fra le piu sature (criticita 4/4): -30%')
    elif criticita is not None and criticita == 3:
        sconto *= 0.85
        motivi.append('provincia congestionata (criticita 3/4): -15%')
    if cabina_satura:
        sconto *= 0.80
        motivi.append('cabina con inversione di flusso: -20%')

    suolo_lo = v_lo * sconto * QUOTA_SUOLO[0]
    suolo_hi = v_hi * sconto * QUOTA_SUOLO[1]
    return {'mwp': mwp, 'p_auth': p_auth,
            'valore_rtb_eur': (round(v_lo), round(v_hi)),
            'sconto_rete': round(sconto, 3), 'motivi_sconto': motivi,
            'monte_suolo_eur': (round(suolo_lo), round(suolo_hi)),
            'nota': 'il monte suolo e cio che il progetto puo pagare a TUTTI i '
                    'proprietari messi insieme, non a ciascuno'}


def per_proprietario(controparti, ha_installabili, tetto, vam_eur_ha=None,
                     anni=ANNI_CONCESSIONE):
    """Tre soglie di offerta per ciascun proprietario.

    `controparti` = output di `visure.aggrega()`. Senza visure non si puo'
    fare: si tornerebbe a ragionare per particella, ed e' proprio l'errore che
    il modulo evita.
    """
    if not controparti or not controparti.get('controparti'):
        return {'errore': 'nessuna controparte nota: servono le visure '
                          '(vedi visure.aggrega)', 'offerte': []}

    tot_ha = sum(x['ha_controllati'] for x in controparti['controparti']) or 1.0
    m_lo, m_hi = tetto['monte_suolo_eur']
    # il monte si distribuisce sugli ettari INSTALLABILI, non su quelli catastali
    resa = (ha_installabili / tot_ha) if tot_ha else 1.0

    out = []
    for x in controparti['controparti']:
        ha = x['ha_controllati']
        quota = x['quota_blocco_pct']
        ha_inst = ha * resa
        prem = _premio(quota)

        if x.get('solo_diritti_deboli'):
            # non possiede terra: si compra un consenso, non ettari
            base_lo = m_lo * QUOTA_GODIMENTO / max(1, len(controparti['controparti']))
            base_hi = m_hi * QUOTA_GODIMENTO / max(1, len(controparti['controparti']))
            tipo = 'consenso (usufrutto/uso): non possiede il fondo'
        else:
            base_lo = m_lo * (ha / tot_ha)
            base_hi = m_hi * (ha / tot_ha)
            tipo = 'proprieta'

        apertura = base_lo
        obiettivo = (base_lo + base_hi) / 2
        massimo = base_hi * prem

        # Il VAM arriva come dict da `vam.vam()` o come banda (min, max). Come
        # soglia di rifiuto si usa il MINIMO: e' il pavimento sotto cui l'offerta
        # e' certamente inaccettabile. Il VAM stesso e' un valore di esproprio,
        # sotto il mercato (Corte Cost. 181/2011): pavimento, mai prezzo.
        v = vam_eur_ha.get('eur_ha') if isinstance(vam_eur_ha, dict) else vam_eur_ha
        v_ha = (min(v) if isinstance(v, (tuple, list)) else v)
        floor = (v_ha * ha) if v_ha else None
        # Due soglie diverse, e la distinzione conta: se l'OBIETTIVO sta sotto il
        # valore agricolo, al prezzo realistico il proprietario non ha ragione di
        # aderire (puo' sempre tenersi il campo); se ci sta sotto perfino il
        # MASSIMO, non c'e' prezzo che chiuda ed e' inutile bussare.
        sotto_floor = bool(floor and obiettivo < floor)
        senza_speranza = bool(floor and massimo < floor)

        out.append({
            'nome': x['nome'], 'tipo': tipo,
            'ha': round(ha, 2), 'ha_installabili': round(ha_inst, 2),
            'quota_blocco_pct': quota,
            'premio_veto': prem,
            'apertura_eur': round(apertura), 'obiettivo_eur': round(obiettivo),
            'massimo_eur': round(massimo),
            'eur_ha_obiettivo': round(obiettivo / ha) if ha else None,
            'canone_annuo_obiettivo_eur': round(obiettivo / anni) if anni else None,
            'valore_agricolo_eur': round(floor) if floor else None,
            'sotto_valore_agricolo': sotto_floor,
            'nessun_prezzo_possibile': senza_speranza,
            'ordine_contatto': None,
        })

    # Ordine di contatto: prima chi puo' bloccare. Sondare il veto costa poco e
    # cambia tutto; scoprirlo dopo aver chiuso venti accordi costa il progetto.
    out.sort(key=lambda o: (-o['quota_blocco_pct'], -o['ha']))
    for i, o in enumerate(out, 1):
        o['ordine_contatto'] = i

    return {'offerte': out, 'tetto': tetto,
            'monte_distribuito_eur': (round(sum(o['apertura_eur'] for o in out)),
                                      round(sum(o['massimo_eur'] for o in out))),
            'ha_installabili': ha_installabili,
            'avvertenze': _avvertenze(out, tetto)}


def _avvertenze(offerte, tetto):
    a = []
    sotto = [o for o in offerte if o['sotto_valore_agricolo']]
    mai = [o for o in offerte if o.get('nessun_prezzo_possibile')]
    if mai:
        a.append(f"{len(mai)} proprietari per cui NESSUN prezzo sostenibile raggiunge il "
                 f"valore agricolo del fondo: il progetto non puo comprarli")
    if sotto:
        ha_s = sum(o['ha'] for o in sotto)
        a.append(f"al prezzo OBIETTIVO {len(sotto)} proprietari ({ha_s:.1f} ha, "
                 f"{sum(o['quota_blocco_pct'] for o in sotto):.0f}% del blocco) "
                 f"resterebbero sotto il valore agricolo del fondo: o si sale verso il "
                 f"massimo, o non hanno ragione economica di aderire")
    veto = [o for o in offerte if o['premio_veto'] > 1.0]
    if veto:
        a.append(f"{len(veto)} proprietari con potere di veto (premio {max(o['premio_veto'] for o in veto):.2f}x): "
                 f"sondarli PRIMA di impegnare risorse sugli altri")
    if tetto['sconto_rete'] < 1.0:
        a.append('il tetto e gia ridotto per lo stato della rete: '
                 + ' · '.join(tetto['motivi_sconto']))
    a.append('i valori RTB (72-150 k€/MWp) sono di mercato, non un preventivo: '
             'il prezzo vero lo fa il developer che compra')
    return a


def print_offerte(o, top=12):
    if o.get('errore'):
        print('\n=== OFFERTE ===\n  ' + o['errore'])
        return
    t = o['tetto']
    print('\n=== QUANTO POSSO OFFRIRE ===')
    print(f"  progetto {t['mwp']} MWp · p_auth {t['p_auth']:.0%} · "
          f"valore RTB {t['valore_rtb_eur'][0]:,} - {t['valore_rtb_eur'][1]:,} EUR"
          .replace(',', '.'))
    if t['motivi_sconto']:
        print('  sconto rete: ' + ' · '.join(t['motivi_sconto']))
    print(f"  monte suolo (TUTTI i proprietari): {t['monte_suolo_eur'][0]:,} - "
          f"{t['monte_suolo_eur'][1]:,} EUR".replace(',', '.'))
    print(f"\n  {'#':>2} {'proprietario':<26} {'ha':>6} {'%':>5} "
          f"{'apertura':>10} {'obiettivo':>10} {'massimo':>10} {'€/ha':>7}")
    for x in o['offerte'][:top]:
        flag = ' !' if x['sotto_valore_agricolo'] else ('  *' if x['premio_veto'] > 1 else '')
        print(f"  {x['ordine_contatto']:>2} {(x['nome'] or '?')[:26]:<26} {x['ha']:>6.2f} "
              f"{x['quota_blocco_pct']:>4.0f}% {x['apertura_eur']:>10,} "
              f"{x['obiettivo_eur']:>10,} {x['massimo_eur']:>10,} "
              f"{(x['eur_ha_obiettivo'] or 0):>7,}".replace(',', '.') + flag)
    print('  (* = premio da veto · ! = sotto il valore agricolo del fondo)')
    for w in o['avvertenze']:
        print(f'  ~ {w}')


def esporta_csv(o, path):
    """Foglio da portare in trattativa, gia' in ordine di contatto."""
    if o.get('errore'):
        return None
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['ordine', 'proprietario', 'tipo', 'ha', 'ha_installabili',
                    'quota_blocco_%', 'premio_veto', 'apertura_EUR', 'obiettivo_EUR',
                    'massimo_EUR', 'EUR_per_ha_obiettivo', 'canone_annuo_EUR',
                    'valore_agricolo_EUR', 'sotto_valore_agricolo', 'esito', 'note'])
        for x in o['offerte']:
            w.writerow([x['ordine_contatto'], x['nome'], x['tipo'], x['ha'],
                        x['ha_installabili'], x['quota_blocco_pct'], x['premio_veto'],
                        x['apertura_eur'], x['obiettivo_eur'], x['massimo_eur'],
                        x['eur_ha_obiettivo'], x['canone_annuo_obiettivo_eur'],
                        x['valore_agricolo_eur'],
                        'SI' if x['sotto_valore_agricolo'] else '', '', ''])
    return path
