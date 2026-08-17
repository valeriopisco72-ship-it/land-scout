# -*- coding: utf-8 -*-
"""QA caccia — l'ordine delle aree da esaminare.

Qui il pericolo e' la promessa: far sembrare che il tool trovi TERRENI, mentre
ordina aree. E il secondo e' l'ordinamento che finge — se la criticita di rete
non e' stata letta, l'ordine non puo' pretendere di tenerne conto.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import caccia as K

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


SS = [
    {'nome': 'SE Morcone', 'lat': 42.3500, 'lon': 13.7600, 'kv': 150000,
     'operatore': 'Terna', 'tensione_nota': True},
    {'nome': 'SE Pontelandolfo', 'lat': 42.3000, 'lon': 13.7000, 'kv': 150000,
     'operatore': 'Terna', 'tensione_nota': True},
    {'nome': 'CP senza tensione', 'lat': 42.2000, 'lon': 13.6000, 'kv': None,
     'operatore': None, 'tensione_nota': False},
]

print('\n[1] una zona per sottostazione, con il bbox pronto')

Z = K.zone('BN', _sottostazioni=SS)
t('tre sottostazioni, tre zone', len(Z['zone']) == 3, str(len(Z['zone'])))
b = Z['zone'][0]['bbox']
t('il bbox e (latmin, lonmin, latmax, lonmax)', b[0] < b[2] and b[1] < b[3], str(b))
t('il raggio e ~3 km in latitudine', abs((b[2] - b[0]) * 111.132 / 2 - 3.0) < 0.1,
  str((b[2] - b[0]) * 111.132 / 2))
t('la provincia viene risolta al nome esteso', Z['nome'] == 'Benevento', Z['nome'])

print('\n[2] chi non sa, lo dice')

t('senza criticita di rete lo dichiara',
  any('criticita' in x for x in Z['non_verificato']), str(Z['non_verificato']), grave=True)
t('senza censimento VIA lo dichiara',
  any('VIA' in x for x in Z['non_verificato']), str(Z['non_verificato']), grave=True)
Z2 = K.zone('BN', criticita={'verificato': True, 'livello': 1},
            progetti=[], _sottostazioni=SS)
t('controprova: con la criticita letta la riga sparisce',
  not any('criticita' in x for x in Z2['non_verificato']), str(Z2['non_verificato']),
  grave=True)

print('\n[3] la rete pesa: una provincia libera vale piu di una satura')

libera = K.zone('BN', criticita={'verificato': True, 'livello': 1}, _sottostazioni=SS[:1])
satura = K.zone('BN', criticita={'verificato': True, 'livello': 4}, _sottostazioni=SS[:1])
t('provincia poco critica -> punteggio piu alto',
  libera['zone'][0]['punteggio'] > satura['zone'][0]['punteggio'],
  f"{libera['zone'][0]['punteggio']} vs {satura['zone'][0]['punteggio']}", grave=True)
t('e il motivo e scritto', any('criticita' in m for m in libera['zone'][0]['motivi']))

print('\n[4] la tensione ignota NON esclude la stazione')

nomi = [z['se'] for z in Z['zone']]
t('la CP senza tensione resta in elenco (OSM la omette spesso)',
  'CP senza tensione' in nomi, str(nomi), grave=True)
z_nt = [z for z in Z['zone'] if z['se'] == 'CP senza tensione'][0]
t('...ma il fatto e dichiarato nei motivi',
  any('non nota' in m for m in z_nt['motivi']), str(z_nt['motivi']), grave=True)
t('e vale meno di una 150 kV',
  z_nt['punteggio'] < [z for z in Z['zone'] if z['se'] == 'SE Morcone'][0]['punteggio'])

print('\n[5] i progetti VIA vicini: segnale doppio, dichiarato')

P = [{'proponente': 'ALFA', 'mw': 30, 'lat': 42.351, 'lon': 13.761},
     {'proponente': 'BETA', 'mw': 20, 'lat': 42.352, 'lon': 13.762}]
Z3 = K.zone('BN', progetti=P, criticita={'verificato': True, 'livello': 3},
            _sottostazioni=SS[:1])
z = Z3['zone'][0]
t('i progetti vicini vengono contati', len(z['progetti_vicini']) == 2,
  str(z['progetti_vicini']))
t('il motivo dice ENTRAMBE le letture (posto buono / fila piu lunga)',
  any('fila' in m and 'buono' in m for m in z['motivi']), str(z['motivi']), grave=True)
senza_p = K.zone('BN', progetti=[], criticita={'verificato': True, 'livello': 3},
                 _sottostazioni=SS[:1])
t('controprova: senza progetti il punteggio e piu alto',
  senza_p['zone'][0]['punteggio'] > z['punteggio'], grave=True)

print('\n[6] il ponte verso scan.py')

cmd = K.comandi(Z)
t('un comando per zona', len(cmd) == 3, str(len(cmd)))
t('il comando contiene il bbox della zona',
  ','.join(str(x) for x in Z['zone'][0]['bbox']) in cmd[0], cmd[0], grave=True)
t('e passa --vincoli (altrimenti lo scan e cieco)', '--vincoli' in cmd[0], cmd[0])

print('\n[6-bis] memoria fra i run: una zona gia guardata non si riguarda per caso')

import tempfile
arch = K.segna({}, 'SE Morcone', 'scartata', nota='tutto bosco', data='2026-03-01')
Z4 = K.zone('BN', _sottostazioni=SS, archivio=arch)
t('la zona gia scartata esce dall elenco', 'SE Morcone' not in [z['se'] for z in Z4['zone']],
  str([z['se'] for z in Z4['zone']]), grave=True)
t('...ma viene DICHIARATA, non fatta sparire',
  any(g['se'] == 'SE Morcone' for g in Z4['gia_viste']), str(Z4['gia_viste']), grave=True)
t('e il motivo di allora e conservato',
  Z4['gia_viste'][0]['nota'] == 'tutto bosco', str(Z4['gia_viste']))
Z5 = K.zone('BN', _sottostazioni=SS, archivio=arch, includi_viste=True)
t('controprova: --includi-viste la rimette dentro',
  'SE Morcone' in [z['se'] for z in Z5['zone']], grave=True)
t('e la marca come gia vista',
  any('gia\' vista' in m for z in Z5['zone'] if z['se'] == 'SE Morcone'
      for m in z['motivi']),
  str([z['motivi'] for z in Z5['zone'] if z['se'] == 'SE Morcone']))
try:
    K.segna({}, 'X', 'boh')
    alzato_e = False
except ValueError:
    alzato_e = True
t('un esito inventato alza invece di essere scritto', alzato_e, grave=True)
dd = tempfile.mkdtemp()
p = K.salva_archivio(arch, os.path.join(dd, 'sub', 'archivio.json'))
t('archivio salvato e riletto identico', K.carica_archivio(p) == arch)
t('archivio inesistente -> dizionario vuoto, non errore',
  K.carica_archivio(os.path.join(dd, 'mai.json')) == {})

print('\n[7] cio che il modulo NON promette')

t('la nota dice che non sono terreni in vendita',
  'non elenco di terreni' in Z['nota'], Z['nota'], grave=True)
try:
    K.zone('ZZ', _sottostazioni=SS)
    alzato = False
except ValueError:
    alzato = True
t('una provincia inesistente alza invece di cercare a caso', alzato, grave=True)
t('il riepilogo si stampa', 'CACCIA' in K.print_zone(Z))

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
