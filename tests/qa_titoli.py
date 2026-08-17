# -*- coding: utf-8 -*-
"""QA titoli — i prerequisiti alla firma.

L'errore da evitare qui e' l'ottimismo di calendario: dire "16 controparti" e
sottintendere che siano 16 telefonate. Un'enfiteusi non affrancata, una
successione non aperta o sette comproprietari cambiano i mesi, non i giorni.
L'errore opposto — trattare ogni usufrutto come un muro — e' altrettanto falso:
l'usufruttuario firma, semplicemente deve esserci.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import titoli as T

OK = FAIL = 0
GRAVI = []


def t(nome, cond, dettaglio='', grave=False):
    global OK, FAIL
    if cond:
        OK += 1
        print(f'  ok   {nome}')
    else:
        FAIL += 1
        print(f'  FAIL {nome} {dettaglio}')
        if grave:
            GRAVI.append(nome)


PULITO = {'controparti': [
    {'nome': 'ROSSI MARIO', 'ha_controllati': 6.0, 'persona_giuridica': False,
     'solo_diritti_deboli': False,
     'dettaglio': [{'fg': '70', 'pla': '136', 'ha_quota': 6.0}]}],
    'titoli_da_sanare': [], 'senza_intestatari': [], 'particelle_mancanti': []}

print('\n[1] un quadro pulito non deve produrre allarmi')
R = T.analizza(PULITO)
t('nessuna voce su un blocco pulito', R['n'] == 0, str(R), grave=True)
t('nessuna strada critica inventata', R['mesi_strada_critica'] is None, str(R))
t('nessun rischio passato alla bancabilita', T.rischi(R) == [])

print('\n[2] enfiteusi: il caso di casa (Convitto / Fg82-78)')
ENF = dict(PULITO, titoli_da_sanare=[{
    'fg': '82', 'pla': '78', 'tipo': 'enfiteusi/livello',
    'soggetti': [{'nome': 'CONVITTO NAZIONALE', 'diritto': 'CONCEDENTE'},
                 {'nome': 'BETA', 'diritto': 'ENFITEUSI'}]}])
R = T.analizza(ENF)
v = R['voci'][0]
t("l'enfiteusi e BLOCCANTE", v['gravita'] == T.BLOCCA, str(v), grave=True)
t("l'azione dice affrancare, non 'verificare'", 'affranc' in v['azione'].lower(), v['azione'])
t('cita il concedente per nome', 'CONVITTO' in v['cosa'], v['cosa'])
t('i mesi sono dichiarati come stima', v['mesi_stimati'][1] and 'STIMAT' in v['nota'].upper(),
  str(v))
t('finisce nei rischi del blocco', any('TITOLO' in x for x in T.rischi(R)), str(T.rischi(R)),
  grave=True)

print('\n[3] usufrutto e persona giuridica: non bloccano, ma qualcuno deve esserci')
DEB = dict(PULITO, controparti=PULITO['controparti'] + [
    {'nome': 'ZIA', 'ha_controllati': 0.0, 'solo_diritti_deboli': True,
     'persona_giuridica': False, 'dettaglio': []},
    {'nome': 'AGRICOLA SRL', 'ha_controllati': 2.0, 'solo_diritti_deboli': False,
     'persona_giuridica': True, 'dettaglio': [{'fg': '70', 'pla': '999', 'ha_quota': 2.0}]}])
R = T.analizza(DEB)
tipi = {v['tipo']: v for v in R['voci']}
t("l'usufrutto e ATTENZIONE, non BLOCCA",
  tipi['usufrutto']['gravita'] == T.ATTENZIONE, str(tipi.get('usufrutto')), grave=True)
t('la societa chiede i poteri di firma',
  'poteri' in tipi['persona_giuridica']['azione'], str(tipi.get('persona_giuridica')))
t('nessuno dei due entra fra i bloccanti', R['n_bloccanti'] == 0, str(R['n_bloccanti']),
  grave=True)

print('\n[4] comproprieta ampia: serve l unanimita')
COMP = {'controparti': [
    {'nome': f'EREDE {i}', 'ha_controllati': 1.0, 'persona_giuridica': False,
     'solo_diritti_deboli': False,
     'dettaglio': [{'fg': '70', 'pla': '500', 'ha_quota': 1.0}]} for i in range(5)],
    'titoli_da_sanare': [], 'senza_intestatari': [], 'particelle_mancanti': []}
R = T.analizza(COMP)
t('5 comproprietari sulla stessa particella: segnalati',
  any(v['tipo'] == 'comproprieta_ampia' for v in R['voci']), str(R['voci']), grave=True)
t('e detto che basta un irreperibile a fermarla',
  any('irreperibile' in v['azione'] for v in R['voci']))
R3 = T.analizza(dict(COMP, controparti=COMP['controparti'][:3]))
t('controprova: 3 comproprietari NON fanno scattare la voce',
  not any(v['tipo'] == 'comproprieta_ampia' for v in R3['voci']), str(R3['voci']), grave=True)

print('\n[5] cio che manca dalle visure non e un quadro pulito')
MANC = dict(PULITO, senza_intestatari=[('70', '777')], particelle_mancanti=[('70', '888')])
R = T.analizza(MANC)
t('particella senza intestatario -> BLOCCA (successione tipica)',
  any(v['tipo'] == 'senza_intestatario' and v['gravita'] == T.BLOCCA for v in R['voci']),
  str(R['voci']), grave=True)
t('visura mancante -> RALLENTA, e la fa scaricare a te',
  any(v['tipo'] == 'visura_mancante' and v['verifica'] == 'tu' for v in R['voci']),
  str(R['voci']))

print('\n[6] ordine: prima cio che blocca')
MIX = dict(ENF, controparti=DEB['controparti'], senza_intestatari=[('70', '777')])
R = T.analizza(MIX)
grav = [v['gravita'] for v in R['voci']]
t('i BLOCCA stanno tutti prima dei RALLENTA/ATTENZIONE',
  grav == sorted(grav, key=lambda g: {T.BLOCCA: 0, T.RALLENTA: 1, T.ATTENZIONE: 2}[g]),
  str(grav), grave=True)
t('la strada critica e il massimo dei tempi, non la somma',
  R['mesi_strada_critica'] == 12, str(R['mesi_strada_critica']))
t('il riepilogo si stampa', 'PREREQUISITI' in T.print_prerequisiti(R))

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
