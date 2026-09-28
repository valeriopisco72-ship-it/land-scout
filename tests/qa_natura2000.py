# -*- coding: utf-8 -*-
"""QA natura2000 — la ZPS e l'habitat NON verificati lungo tutta la catena.

Il 16/07 `vincoli.natura2000` ha imparato a dire "non lo so" (`n2k_ok=False`,
`zps=None`). Ma il "non lo so" si fermava li': ogni modulo a valle, per
tradurlo nel proprio formato, lo riscriveva come *zero*.

  - `to_score_fields` non passava `zps_pct` e `score_with_vincoli` metteva il
    default `0.0` = "verificato fuori ZPS";
  - `recommend._normalizza` convertiva `None` in `0.0` e l'eolico usciva
    "fuori ZPS: possibile";
  - `dossier` scriveva `zpct = 0.0` e, con la Carta Habitat giu', stampava
    "Habitat divieto FV: ✅ non rilevato";
  - `blocco.ammissibilita` dichiarava PAI e SITAP non verificati, ma taceva su
    Natura 2000 e habitat — cioe' sui due controlli che decidono il divieto;
  - `engine.score_parcel`, ricevuto il `None`, alzava TypeError; e con la ZPS
    trovata ma l'habitat `None` scriveva "DENTRO ZPS ma NON su habitat vietato"
    e spegneva il blocker (classe B invece di D);
  - `valore.p_auth` dava 0,75 "fuori Natura 2000: iter ordinario senza VINCA";
  - `zps.studio` concludeva "nessun divieto trovato" senza aver guardato;
  - `feasibility` scriveva 'VINCA' (= "nessuna preclusione" sulla pagina web)
    anche con la Carta Habitat giu'.

Audit del 28/09/2026. Ogni verifica ha la sua controprova: con la fonte che
risponde, nessun avviso inventato.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shapely.geometry import GeometryCollection, Polygon

from landscout import blocco as B
from landscout import dossier as D
from landscout import engine as E
from landscout import recommend as R
from landscout import vincoli as V
from landscout.config import CHIAVI_SITAP

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


def prova(fn, *a, **k):
    """(risultato, eccezione): nella fase rossa il codice puo' esplodere, e un
    file di test che muore al primo errore non dice quanti altri ce ne sono."""
    try:
        return fn(*a, **k), None
    except Exception as e:           # noqa: BLE001 — qui si vuole proprio tutto
        return None, e


def ha_avviso_n2k(flags):
    return any('Natura 2000' in f and 'NON verificat' in f for f in (flags or []))


BASE = {'ha': 5.0, 'slope': 4.0, 'd_se_m': 800, 'd_150kv_m': 400,
        'pai_fr': -1, 'pai_idr': 0}

# ------------------------------------------------------------------ 1. motore
print('\n[1] engine: la ZPS non verificata e un dubbio dichiarato, non un crash')

r, e = prova(E.score_parcel, dict(BASE, zps_pct=None, zps_border_m=None), 'agriPV')
t('zps_pct=None non fa esplodere score_parcel', e is None, repr(e), grave=True)
t('e lo scrive nei flag', r is not None and ha_avviso_n2k(r[2]),
  str(r and r[2]), grave=True)

r, e = prova(E.score_parcel, dict(BASE), 'BESS')
t('neanche la chiave assente (dict costruito a mano)', e is None, repr(e), grave=True)
t('...che vale "non controllato", non "fuori ZPS"', r is not None and ha_avviso_n2k(r[2]),
  str(r and r[2]), grave=True)

r, e = prova(E.score_parcel, dict(BASE, zps_pct=0.0, zps_border_m=9e9), 'agriPV')
t('controprova: ZPS verificata assente -> nessun avviso inventato',
  e is None and not ha_avviso_n2k(r[2]), str(e or r[2]), grave=True)

r, e = prova(E.score_parcel, dict(BASE, zps_pct=100.0, zps_border_m=-1), 'agriPV')
t('controprova: ZPS verificata presente -> resta un blocker per agriPV',
  e is None and r[1] == 'D', str(e or r), grave=True)

print('\n[1b] engine: in ZPS, habitat NON verificato non e "habitat sgombro"')

# Il ramo "DENTRO ZPS ma NON su habitat vietato" (-28, non preclusivo) esiste perche'
# a Morcone l'habitat era stato VERIFICATO sgombro. Con `habitat_ban=None` (Carta
# Habitat giu') la condizione `not p['habitat_ban']` era vera lo stesso: il motore
# scriveva "NON su habitat vietato" su un controllo mai eseguito, e toglieva il blocker.
r, e = prova(E.score_parcel, dict(BASE, zps_pct=100.0, zps_border_m=-1, habitat_ban=None),
             'agriPV')
t('ZPS + habitat None: resta il blocker agriPV', e is None and r[1] == 'D', str(e or r),
  grave=True)
t('e non dice "NON su habitat vietato"',
  e is None and not any('NON su habitat vietato' in f for f in r[2]), str(r and r[2]),
  grave=True)
t('ma dichiara l habitat non verificato',
  e is None and any('habitat' in f.lower() and 'NON verificat' in f for f in r[2]),
  str(r and r[2]), grave=True)
r, e = prova(E.score_parcel, dict(BASE, zps_pct=100.0, zps_border_m=-1, habitat_ban=False),
             'agriPV')
t('controprova: habitat verificato sgombro -> iter VINCA, non blocker',
  e is None and r[1] != 'D' and any('NON su habitat vietato' in f for f in r[2]),
  str(e or r), grave=True)

from landscout import bess as BS
r, e = prova(BS.vincoli_bess, dict(BASE, zps_pct=None))
t('bess.vincoli_bess accetta zps_pct=None', e is None, repr(e), grave=True)
t('e lo dichiara fra le criticita', e is None and any('Natura 2000' in f for f in r['criticita']),
  str(r and r['criticita']))
r, e = prova(BS.vincoli_bess, dict(BASE, zps_pct=100.0))
t('controprova: ZPS verificata -> resta fra i "favorevoli" del BESS',
  e is None and any('ZPS' in f for f in r['favorevoli']), str(e or r))

print('\n[2] engine: la distanza dalla rete ignota non e "9.000.000 km"')

r, e = prova(E.score_parcel, dict(BASE, zps_pct=0.0, zps_border_m=9e9, d_se_m=None), 'BESS')
t('d_se_m=None non fa esplodere score_parcel', e is None, repr(e), grave=True)
r2, _ = prova(E.score_parcel, {k: v for k, v in dict(BASE, zps_pct=0.0,
                                                    zps_border_m=9e9).items()
                               if k != 'd_se_m'}, 'BESS')
testo = ' | '.join((r and r[2] or []) + (r2 and r2[2] or []))
t('il flag non promette una stazione a migliaia di km', '9000000' not in testo, testo)
t('e dice che la distanza non e stata verificata',
  r is not None and any('SE' in f and 'NON verificat' in f for f in r[2]), testo)
lontana, _ = prova(E.score_parcel, dict(BASE, zps_pct=0.0, zps_border_m=9e9,
                                        d_se_m=12000), 'BESS')
t('controprova: una SE lontana ma misurata resta "SE a 12.0 km"',
  lontana is not None and any('12.0 km' in f for f in lontana[2]), str(lontana))

p = {'ha': 2.0}
r, e = prova(E.price_parcel, p, 70.0, 'B', 'BESS')
t('price_parcel senza d_se_m non alza KeyError', e is None, repr(e), grave=True)

# --------------------------------------------------------- 2. vincoli -> motore
print('\n[3] to_score_fields: il "non lo so" di natura2000 arriva al motore')

ignoto = {'zps': None, 'sic': None, 'zps_pct': None, 'n2k_ok': False,
          'habitat_ban': False, 'pai_fr': -1, 'pai_idr': 0, 'pai_ok': True}
f = V.to_score_fields(ignoto)
t('to_score_fields passa zps_pct=None', 'zps_pct' in f and f['zps_pct'] is None, str(f),
  grave=True)

vero_feas = V.feasibility
try:
    V.feasibility = lambda parcels, prov=None: {'p1': dict(ignoto)}
    out, e = prova(V.score_with_vincoli, {'p1': {'lat': 41.3, 'lon': 14.6, 'ha': 5.0,
                                                  'slope': 4.0, 'd_se_m': 800}})
finally:
    V.feasibility = vero_feas
t('score_with_vincoli non riempie il buco con "fuori ZPS"',
  e is None and ha_avviso_n2k(out['p1']['flags']), str(e or out['p1']['flags']),
  grave=True)

noto = dict(ignoto, zps=False, sic=False, zps_pct=0.0, n2k_ok=True)
f = V.to_score_fields(noto)
t('controprova: ZPS verificata assente -> niente zps_pct=None',
  f.get('zps_pct', 0.0) is not None, str(f), grave=True)

# ------------------------------------------------------------- 3. recommend
print('\n[4] recommend: senza ZPS verificata l eolico non e "fuori ZPS"')

reco, e = prova(R.recommend, {'ha': 3.0, 'slope': 4.0, 'zps_pct': None,
                              'habitat_ban': False, 'd_se_m': 500, 'd_150kv_m': 300})
t('recommend accetta zps_pct=None', e is None, repr(e), grave=True)
eol = next((x for x in (reco or {}).get('ranking', []) if x['tech'] == 'eolico'), {})
motivi = ' | '.join(eol.get('reasons', []))
t('l eolico non dice "fuori ZPS"', 'fuori ZPS' not in motivi, motivi, grave=True)
t('e dichiara la ZPS non verificata', 'NON verificat' in motivi, motivi, grave=True)
agri = next((x for x in (reco or {}).get('ranking', []) if x['tech'] == 'agriPV'), {})
t('l avviso arriva anche fra i motivi dell agriPV',
  any('Natura 2000' in m for m in agri.get('reasons', [])), str(agri.get('reasons')))

reco2, _ = prova(R.recommend, {'ha': 3.0, 'slope': 4.0, 'zps_pct': 0.0,
                               'zps_border_m': 9e9, 'habitat_ban': False, 'd_se_m': 500})
eol2 = next((x for x in (reco2 or {}).get('ranking', []) if x['tech'] == 'eolico'), {})
t('controprova: ZPS verificata assente -> "fuori ZPS" resta',
  any('fuori ZPS' in m for m in eol2.get('reasons', [])), str(eol2))

q = R._normalizza({'ha': 1.0, 'zps_pct': None})
t('_normalizza lascia None la ZPS (e un vincolo, non una distanza)',
  q['zps_pct'] is None, str(q), grave=True)
q = R._normalizza({'ha': 1.0, 'zps_pct': ''})
t('...anche quando arriva vuota da un form', q['zps_pct'] is None, str(q))

# --------------------------------------------------------------- 4. dossier
print('\n[5] dossier: dal risultato vincoli ai campi del motore')

pm = getattr(D, 'parcella_motore', None)
t('dossier espone parcella_motore (testabile senza rete)', callable(pm), grave=True)
if callable(pm):
    ep = pm({'ha': 2.0, 'slope': 3.0}, {'zps': None, 'zps_pct': None,
                                        'habitat_ban': None, 'sic': None})
    t('zps None -> zps_pct None (non 0.0)', ep['zps_pct'] is None, str(ep), grave=True)
    t('e habitat_ban resta None', ep['habitat_ban'] is None, str(ep), grave=True)
    ep = pm({'ha': 2.0}, {'zps': True, 'zps_pct': None})
    t('col solo centroide zps True -> 100%', ep['zps_pct'] == 100.0, str(ep))
    ep = pm({'ha': 2.0}, {'zps': False, 'zps_pct': 0.0})
    t('controprova: fuori ZPS verificato -> 0%', ep['zps_pct'] == 0.0, str(ep))

print('\n[6] dossier: la stampa non promette un habitat che non ha guardato')


def dossier_finto(habitat_ok=True, n2k_ok=True, verdetti=None):
    return {'comune': 'Esempio', 'prov': 'BN', 'n': 1, 'tot_ha': 2.0,
            'avvisi_luogo': [],
            'fattibilita': {'verdetti': verdetti or {'CLEAN': 1}, 'ha_habitat_vietato': 0.0,
                            'usi_civici_n': 0, 'sitap_ok': True,
                            'habitat_ok': habitat_ok, 'n2k_ok': n2k_ok,
                            'copertura': {'regione': 'CAMPANIA', 'habitat_regionale': True,
                                          'habitat_fonte': 'carta regionale', 'sitap': True,
                                          'sitap_mancanti': []}},
            'tecnologia': {'consigliata': 'agriPV', 'distribuzione': {'agriPV': 1}},
            'rete': {'verificato': False, 'comune': 'Esempio', 'prov': 'BN', 'nota': '-'},
            'rete_distanza': {'verificato': False},
            'resa': {'error': 'offline'}, 'valore_eur': {}, 'aziende': []}


def stampa(d):
    buf, vero = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        D.print_dossier(d)
    except Exception as e:           # noqa: BLE001
        buf.write(f'\n<<ECCEZIONE {type(e).__name__}: {e}>>')
    finally:
        sys.stdout = vero
    return buf.getvalue()


vero_descr = D.descrivi_valore
D.descrivi_valore = lambda v: '   (valore: n.d. nel test)'
try:
    out_nv = stampa(dossier_finto(habitat_ok=False, n2k_ok=False,
                                  verdetti={'NON VERIFICATO: habitat (fonte non raggiunta)': 1}))
    out_ok = stampa(dossier_finto())
finally:
    D.descrivi_valore = vero_descr
riga_hab = next((x for x in out_nv.splitlines() if 'Habitat divieto' in x), '')
t('habitat non raggiunto: niente "✅ non rilevato"', 'non rilevato' not in riga_hab,
  riga_hab, grave=True)
t('ma "NON VERIFICATO"', 'NON VERIFICAT' in riga_hab, riga_hab, grave=True)
t('e il motivo della tecnologia non dice "fuori Natura 2000"',
  'fuori Natura 2000' not in out_nv, out_nv[-600:], grave=True)
t('controprova: habitat verificato e assente -> "non rilevato"',
  'non rilevato' in out_ok, out_ok[-400:])
t('nessuna eccezione in stampa', '<<ECCEZIONE' not in out_nv + out_ok,
  (out_nv + out_ok)[-300:], grave=True)

print('\n[6b] valore: la probabilita autorizzativa non e "fuori Natura 2000" per default')

from landscout import valore as VL

p_nv, perche_nv = VL.p_auth({'zps': None, 'sic': None, 'habitat_ban': None})
t('EEA e habitat giu: il perche non dice "fuori Natura 2000: iter ordinario"',
  'fuori Natura 2000: iter ordinario' not in perche_nv, perche_nv, grave=True)
t('e dichiara che manca la verifica', 'NON verificat' in perche_nv, perche_nv, grave=True)
p_z, perche_z = VL.p_auth({'zps': True, 'sic': False, 'habitat_ban': None})
t('dentro ZPS con habitat ignoto: "nessuna preclusione" va condizionato',
  'habitat NON verificat' in perche_z, perche_z, grave=True)
p_ok, perche_ok = VL.p_auth({'zps': False, 'sic': False, 'habitat_ban': False})
t('controprova: tutto verificato e pulito -> "fuori Natura 2000"',
  'fuori Natura 2000' in perche_ok and 'NON verificat' not in perche_ok, perche_ok)
t('controprova: dict vuoto (API storica) -> invariato', VL.p_auth({})[0] == p_ok)
v_nv = VL.valore(5.0, {'zps': None, 'sic': None, 'habitat_ban': None}, tech='agriPV')
t('valore() lo porta anche fra gli avvisi',
  any('NON verificat' in a for a in v_nv['avvisi']), str(v_nv['avvisi']), grave=True)
t('e la confidenza resta bassa', v_nv['confidenza'] == 'bassa', v_nv['confidenza'])

vb = getattr(D, 'vincoli_blocco', None)
t('dossier espone vincoli_blocco', callable(vb), grave=True)
if callable(vb):
    b = vb({'a': {'zps': None, 'sic': None, 'habitat_ban': None, 'usi_civici': None},
            'b': {'zps': False, 'sic': False, 'habitat_ban': False, 'usi_civici': False}})
    t('una particella non verificata rende il blocco non verificato (None, non False)',
      b['zps'] is None and b['habitat_ban'] is None, str(b), grave=True)
    b = vb({'a': {'zps': None, 'habitat_ban': None}, 'b': {'zps': True, 'habitat_ban': True}})
    t('un vincolo TROVATO vince sul dubbio', b['zps'] is True and b['habitat_ban'] is True,
      str(b), grave=True)
    b = vb({'a': {'zps': False, 'habitat_ban': False}})
    t('controprova: tutto verificato -> False', b['zps'] is False and b['habitat_ban'] is False,
      str(b))

# ---------------------------------------------------------------- 5. blocco
print('\n[7] blocco: Natura 2000 e habitat non verificati finiscono nel riepilogo')

LA, LO = 41.30, 14.60
quad = [(LA, LO), (LA + 0.003, LO), (LA + 0.003, LO + 0.003), (LA, LO + 0.003)]
p = [{'fg': 7, 'pla': 100, 'ha': 3.0, 'poly': quad}]
occ = {'7_100': {'verdetto': 'LIBERA', 'pct': 0.0}}
A_nv = B.ammissibilita(p, {'7_100': {'habitat_ban': None, 'habitat_ok': False,
                                     'zps': None, 'n2k_ok': False,
                                     'pai_ok': True, 'sitap_ok': True}}, occ)
t('non verificato non e bocciato: la particella entra', len(A_nv['ammesse']) == 1,
  str(A_nv['scarti']))
nv = ' | '.join(A_nv['non_verificati'])
t('il riepilogo dichiara l habitat non verificato', 'habitat' in nv.lower(), nv, grave=True)
t('e Natura 2000 non verificata', 'Natura 2000' in nv, nv, grave=True)
A_ok = B.ammissibilita(p, {'7_100': {'habitat_ban': False, 'habitat_ok': True,
                                     'zps': False, 'n2k_ok': True,
                                     'pai_ok': True, 'sitap_ok': True}}, occ)
t('controprova: fonti raggiunte -> nessuna lacuna inventata',
  A_ok['non_verificati'] == [], str(A_ok['non_verificati']), grave=True)

# --------------------------------------------------- 6. verdetto di feasibility
print('\n[8] feasibility: "VINCA" non si scrive se l habitat non e stato guardato')

# Dentro la ZPS il divieto habitat e' L'UNICA cosa che separa "iter VINCA,
# impegnativo ma non preclusivo" da "progetto vietato". Se la Carta Habitat non
# risponde il verdetto non puo' essere il semplice 'VINCA' (la pagina web lo
# traduce in "nessuna preclusione").


def feas(hab_risposta, n2k=True):
    finti = {}

    def natura(plist, to_xy):
        g = Polygon([to_xy(LA - 0.01, LO - 0.01), to_xy(LA - 0.01, LO + 0.01),
                     to_xy(LA + 0.01, LO + 0.01), to_xy(LA + 0.01, LO - 0.01)])
        return (g, None, True) if n2k else (None, None, False)

    finti['natura2000'] = natura
    finti['pai'] = lambda plist, to_xy: ({}, {}, True)
    finti['sitap_paesaggio'] = lambda plist, to_xy, regione=None: (
        {k: GeometryCollection() for k in CHIAVI_SITAP}, True)
    finti['habitat_ban'] = lambda parcels: hab_risposta
    veri = {k: getattr(V, k) for k in finti}
    buf, vero_out = io.StringIO(), sys.stdout
    try:
        for k, fn in finti.items():
            setattr(V, k, fn)
        sys.stdout = buf
        return V.feasibility({'p1': {'lat': LA, 'lon': LO, 'ha': 2.0}}, prov='BN')['p1']
    finally:
        sys.stdout = vero_out
        for k, fn in veri.items():
            setattr(V, k, fn)


r_nv, e = prova(feas, None)
t('feasibility gira con i servizi finti', e is None, repr(e), grave=True)
v = (r_nv or {}).get('verdetto', '')
t('habitat non raggiunto in ZPS: il verdetto resta VINCA...', v.startswith('VINCA'), v)
t('...ma dichiara l habitat NON verificato', 'NON VERIFICAT' in v and 'habitat' in v, v,
  grave=True)
r_ok, _ = prova(feas, {'p1': {'codici': {}, 'geometria': 'centroide'}})
t('controprova: habitat verificato e sgombro -> "VINCA" pulito',
  (r_ok or {}).get('verdetto') == 'VINCA', str((r_ok or {}).get('verdetto')), grave=True)
r_ban, _ = prova(feas, {'p1': {'codici': {'6220*': 100.0}, 'geometria': 'centroide'}})
t('controprova: habitat vietato -> BLOCK_HABITAT, come prima',
  (r_ban or {}).get('verdetto') == 'BLOCK_HABITAT', str((r_ban or {}).get('verdetto')),
  grave=True)
r_n2k, _ = prova(feas, {'p1': {'codici': {}, 'geometria': 'centroide'}}, n2k=False)
t('EEA giu e nient altro trovato -> NON VERIFICATO (regola gia esistente)',
  str((r_n2k or {}).get('verdetto', '')).startswith('NON VERIFICATO'),
  str((r_n2k or {}).get('verdetto')), grave=True)

print('\n[8b] zps.studio: "nessun divieto trovato" solo se il divieto e stato cercato')

from landscout import zps as ZS
vz = {'p1': {'ha': 2.0, 'geometria': 'poligono', 'n2k_ok': True, 'zps_pct': 100.0,
             'habitat_ok': False, 'habitat_ban_pct': None, 'habitat': None}}
st, e = prova(ZS.studio, {'p1': {'lat': LA, 'lon': LO, 'ha': 2.0}}, prov='BN', vinc=vz)
t('zps.studio gira offline con vinc gia calcolato', e is None, repr(e), grave=True)
if st:
    t('ZPS + habitat non raggiunto: il verdetto non dice "nessun divieto trovato"',
      'nessun divieto' not in st['verdetto'], st['verdetto'], grave=True)
    t('e la sintesi non dice "non il divieto"', 'non il divieto' not in st['sintesi'],
      st['sintesi'], grave=True)
    t('ma dichiara l habitat non verificato', 'NON verificat' in st['verdetto'] + st['sintesi'],
      st['verdetto'] + ' | ' + st['sintesi'], grave=True)
vz_ok = {'p1': dict(vz['p1'], habitat_ok=True, habitat_ban_pct=0.0)}
st_ok, _ = prova(ZS.studio, {'p1': {'lat': LA, 'lon': LO, 'ha': 2.0}}, prov='BN', vinc=vz_ok)
t('controprova: habitat verificato sgombro -> "VInCA NECESSARIA (nessun divieto trovato)"',
  bool(st_ok) and st_ok['verdetto'] == 'VInCA NECESSARIA (nessun divieto trovato)',
  str(st_ok and st_ok['verdetto']), grave=True)

print('\n[9] print_report ordina per gravita anche i verdetti con riserva')

res = {'pulita': {'ha': 1.0, 'verdetto': 'CLEAN', 'habitat': None},
       'vinca': {'ha': 1.0, 'verdetto': 'VINCA — NON VERIFICATO: habitat (fonte non raggiunta)',
                 'habitat': None, 'zps': True},
       'frana': {'ha': 1.0, 'verdetto': 'BLOCK_PAI(frana P4 100%)', 'habitat': None}}
buf, vero_out = io.StringIO(), sys.stdout
sys.stdout = buf
try:
    V.print_report(res)
finally:
    sys.stdout = vero_out
righe = [x.split()[0] for x in buf.getvalue().splitlines() if x.split()
         and x.split()[0] in res]
t('BLOCK_PAI prima di VINCA, VINCA prima di CLEAN', righe == ['frana', 'vinca', 'pulita'],
  str(righe))

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
