# -*- coding: utf-8 -*-
"""QA offerta — quanto posso offrire a questo proprietario."""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from landscout import offerta as O

OK = FAIL = 0
GRAVI = []


def t(nome, cond, dett='', grave=False):
    global OK, FAIL
    if cond:
        OK += 1
        print(f'  ok   {nome}')
    else:
        FAIL += 1
        print(f'  FAIL {nome} {dett}')
        if grave:
            GRAVI.append(nome)


def cp(*righe):
    """controparti sintetiche: (nome, ha, quota%, solo_deboli)"""
    return {'controparti': [
        {'nome': n, 'ha_controllati': ha, 'quota_blocco_pct': q,
         'solo_diritti_deboli': d, 'n_particelle': 1} for n, ha, q, d in righe]}


print('=' * 76)
print('  QA OFFERTA — tetto di progetto, soglie per proprietario, ordine contatti')
print('=' * 76)

# ------------------------------------------------------------------ 1. tetto
print('\n[1] il tetto scende col rischio')
base = O.tetto_progetto(mwp=10.0, p_auth=1.0)
meta = O.tetto_progetto(mwp=10.0, p_auth=0.5)
t('p_auth dimezzata dimezza il valore',
  abs(meta['valore_rtb_eur'][1] - base['valore_rtb_eur'][1] / 2) < 2,
  f"{meta['valore_rtb_eur']} vs {base['valore_rtb_eur']}", grave=True)

c3 = O.tetto_progetto(mwp=10.0, p_auth=1.0, criticita=3)
c4 = O.tetto_progetto(mwp=10.0, p_auth=1.0, criticita=4)
cab = O.tetto_progetto(mwp=10.0, p_auth=1.0, criticita=3, cabina_satura=True)
t('criticita 3 sconta il tetto', c3['monte_suolo_eur'][1] < base['monte_suolo_eur'][1],
  grave=True)
t('criticita 4 sconta piu di 3', c4['monte_suolo_eur'][1] < c3['monte_suolo_eur'][1],
  grave=True)
t('la cabina satura sconta oltre la provincia',
  cab['monte_suolo_eur'][1] < c3['monte_suolo_eur'][1], grave=True)
t('senza dati di rete nessuno sconto (controprova)',
  base['sconto_rete'] == 1.0 and not base['motivi_sconto'], grave=True)
t('il tetto dichiara che vale per TUTTI insieme', 'TUTTI' in base['nota'])

# ------------------------------------------------------------------ 2. soglie
print('\n[2] tre soglie, non un prezzo')
C = cp(('GRANDE', 6.0, 60.0, False), ('MEDIO', 3.0, 30.0, False), ('PICCOLO', 1.0, 10.0, False))
o = O.per_proprietario(C, ha_installabili=10.0, tetto=base)
g = o['offerte'][0]
t('apertura < obiettivo < massimo',
  g['apertura_eur'] < g['obiettivo_eur'] < g['massimo_eur'],
  f"{g['apertura_eur']}/{g['obiettivo_eur']}/{g['massimo_eur']}", grave=True)
t('chi ha piu ettari riceve di piu',
  o['offerte'][0]['obiettivo_eur'] > o['offerte'][-1]['obiettivo_eur'], grave=True)
t('il monte in apertura non supera il monte suolo',
  o['monte_distribuito_eur'][0] <= base['monte_suolo_eur'][1] * 1.01,
  f"{o['monte_distribuito_eur']} vs {base['monte_suolo_eur']}", grave=True)

# ------------------------------------------------------------------ 3. veto
print('\n[3] premio da veto e ordine di contatto')
t('quota 60% prende il premio massimo', g['premio_veto'] == max(O.PREMIO_VETO.values()),
  f"{g['premio_veto']}", grave=True)
t('quota 10% non prende premio', o['offerte'][-1]['premio_veto'] == 1.0, grave=True)
t('si contatta per primo chi puo bloccare',
  o['offerte'][0]['nome'] == 'GRANDE' and o['offerte'][0]['ordine_contatto'] == 1,
  grave=True)
t('l ordine e progressivo e completo',
  [x['ordine_contatto'] for x in o['offerte']] == [1, 2, 3])
t('il veto viene segnalato fra le avvertenze',
  any('veto' in a for a in o['avvertenze']), grave=True)
piatto = O.per_proprietario(cp(('A', 1.0, 10.0, False), ('B', 1.0, 10.0, False)),
                            10.0, base)
t('senza nessuno sopra soglia, nessun avviso di veto (controprova)',
  not any('veto' in a for a in piatto['avvertenze']), grave=True)

# ------------------------------------------------------------------ 4. godimento
print('\n[4] chi ha solo usufrutto: consenso, non ettari')
Cg = cp(('PROPRIETARIO', 9.0, 90.0, False), ('USUFRUTTUARIO', 0.0, 0.0, True))
og = O.per_proprietario(Cg, 10.0, base)
u = [x for x in og['offerte'] if x['nome'] == 'USUFRUTTUARIO'][0]
t('chi ha 0 ha riceve comunque un importo (serve il consenso)',
  u['obiettivo_eur'] > 0, f"{u['obiettivo_eur']}", grave=True)
t('ma molto meno del proprietario',
  u['obiettivo_eur'] < og['offerte'][0]['obiettivo_eur'] / 3, grave=True)
t('e viene etichettato come consenso', 'consenso' in u['tipo'], grave=True)

# ------------------------------------------------------------------ 5. floor
print('\n[5] il pavimento agricolo (VAM)')
# VAM alto: l'obiettivo ci finisce sotto, ma il massimo lo supera
of = O.per_proprietario(cp(('TIZIO', 5.0, 50.0, False)), 10.0, base, vam_eur_ha=8000)
x = of['offerte'][0]
t('confronta col valore agricolo del fondo', x['valore_agricolo_eur'] == 40000,
  f"{x['valore_agricolo_eur']}")
t('segnala se l OBIETTIVO sta sotto il pavimento',
  x['sotto_valore_agricolo'] == (x['obiettivo_eur'] < 40000), grave=True)

# VAM assurdo: nessun prezzo possibile
oi = O.per_proprietario(cp(('CARO', 5.0, 50.0, False)), 10.0, base, vam_eur_ha=10_000_000)
t('se nemmeno il massimo arriva al pavimento, lo dice',
  oi['offerte'][0]['nessun_prezzo_possibile'] and
  any('NESSUN prezzo' in a for a in oi['avvertenze']), grave=True)
t('con VAM basso nessun allarme (controprova)',
  not O.per_proprietario(cp(('TIZIO', 5.0, 50.0, False)), 10.0, base,
                         vam_eur_ha=1)['offerte'][0]['sotto_valore_agricolo'], grave=True)
t('accetta il VAM come dict di vam.vam()',
  O.per_proprietario(cp(('T', 5.0, 50.0, False)), 10.0, base,
                     vam_eur_ha={'eur_ha': [8000, 12000]})['offerte'][0][
                         'valore_agricolo_eur'] == 40000,
  grave=True)
t('senza VAM non inventa un pavimento',
  O.per_proprietario(cp(('T', 5.0, 50.0, False)), 10.0, base
                     )['offerte'][0]['valore_agricolo_eur'] is None, grave=True)

# ------------------------------------------------------------------ 6. senza visure
print('\n[6] senza visure non si puo fare')
vuoto = O.per_proprietario({'controparti': []}, 10.0, base)
t('senza controparti restituisce un errore esplicito',
  'errore' in vuoto and 'visure' in vuoto['errore'], grave=True)
t('e non inventa offerte', vuoto['offerte'] == [], grave=True)

# ------------------------------------------------------------------ 7. csv
print('\n[7] foglio da trattativa')
p = os.path.join(tempfile.mkdtemp(), 'off.csv')
O.esporta_csv(o, p)
righe = open(p, encoding='utf-8-sig').read().strip().splitlines()
t('una riga per proprietario', len(righe) - 1 == len(o['offerte']))
t('ordinato per contatto', righe[1].split(';')[0] == '1')
t('ha colonne per annotare esito in trattativa',
  'esito' in righe[0] and 'note' in righe[0])
t('senza offerte non scrive nulla', O.esporta_csv(vuoto, p) is None, grave=True)

print('\n' + '=' * 76)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 76)
sys.exit(1 if GRAVI else 0)
