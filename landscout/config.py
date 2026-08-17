"""land-scout — CONFIG (v0.1, 15/07/2026): unica fonte di verita' per path, endpoint, parametri.

Prima di questo modulo ogni file aveva `BASE = r'C:\\Users\\Valerio\\dev\\land-scout'` hardcoded
(e match.py leggeva il censimento da un percorso locale fuori dal repo): il motore non girava
su nessuna macchina che non fosse quella di Valerio. Qui la radice si AUTO-RILEVA dalla
posizione del package ed e' sovrascrivibile via variabile d'ambiente.

Override via env:
  LANDSCOUT_HOME    -> radice del progetto        (default: cartella che contiene questo package)
  LANDSCOUT_DATA    -> cartella dati              (default: <HOME>/data)
  LANDSCOUT_CACHE   -> cartella cache             (default: <DATA>/cache)
  LANDSCOUT_CENSUS  -> csv censimento VIA         (default: <DATA>/raw/via/proponenti_VIA.csv)
"""
import os
from pathlib import Path

# ---------- radice: auto-rilevata, niente path assoluti nel codice ----------
HOME = Path(os.environ.get('LANDSCOUT_HOME') or Path(__file__).resolve().parent.parent)
DATA = Path(os.environ.get('LANDSCOUT_DATA') or HOME / 'data')
RAW = DATA / 'raw'
CACHE_DIR = Path(os.environ.get('LANDSCOUT_CACHE') or DATA / 'cache')
DEMO = HOME / 'demo'
for _d in (DATA, RAW, CACHE_DIR, DEMO):
    _d.mkdir(parents=True, exist_ok=True)

# ---------- dataset ----------
CENSUS = Path(os.environ.get('LANDSCOUT_CENSUS') or RAW / 'via' / 'proponenti_VIA.csv')
HABITAT_ZIP = CACHE_DIR / 'rn2000_campania.zip'
HABITAT_PREFIX = 'RN2000 - Regione Campania - 14.11.2024/'
GEOCODE_CACHE = CACHE_DIR / 'geocode_cache.json'
PVGIS_CACHE = CACHE_DIR / 'pvgis_cache.json'

# ---------- endpoint (centralizzati: si cambiano/mockano da qui) ----------
EP = {
    'sitap':    'https://sitap.cultura.gov.it/geoserver/wfs',          # NB: la porta :8080 e' morta, usare https
    'eea_n2k':  'https://bio.discomap.eea.europa.eu/arcgis/rest/services/ProtectedSites/Natura2000Sites/MapServer',
    'ispra_habitat_wfs': 'https://sdi.isprambiente.it/geoserver/hb1/habitat/wfs',
    'habitat_campania_zip': 'https://www.regione.campania.it/assets/documents/rn2000-regione-campania-14-11-2024.zip',
    'pvgis':    'https://re.jrc.ec.europa.eu/api/v5_2/PVcalc',
    # portale VIA nazionale: la ricerca e' GET e supporta l'export XLSX con &t=o&mode=export
    'via_export': 'https://va.mite.gov.it/it-IT/Ricerca/ViaLibera',
    'nominatim':'https://nominatim.openstreetmap.org/search',
    'nominatim_reverse':'https://nominatim.openstreetmap.org/reverse',
    'catasto':  'https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php',
    'idrogeo':  'https://idrogeo.isprambiente.it/geoserver/idrogeo/ows',
    'opentopo': 'https://api.opentopodata.org/v1',
}
UA = {'User-Agent': 'land-scout/0.1 (screening terreni rinnovabili)'}
TIMEOUT = int(os.environ.get('LANDSCOUT_TIMEOUT', '90'))

# ---------- layer SITAP per REGIONE ----------
# SITAP copre 9 regioni su 20 e OGNUNA ha un sottoinsieme diverso con naming incoerente
# (CAMPANIA_art_142_b_laghi vs BASILICATA_art142_b_laghi_buffer vs 'VENETO_art.142_lett b_BUFFER 300m_LAGHI').
# Gli USI CIVICI esistono solo per Campania, Lazio, Umbria, FVG. Nomi verificati live 15/07/2026.
# Chiave assente per una regione = quel controllo NON e' possibile li' -> si dichiara "non verificato".
SITAP_REGION_LAYERS = {
    'CAMPANIA': {
        'usi_civici':  'CAMPANIA_art_142_h_usi_civici',
        'bosco_142g':  'CAMPANIA_art_142_g_boschi',
        'fiume_150m':  'CAMPANIA_art_142_c_fiumi',
        'lago_300m':   'CAMPANIA_art_142_b_laghi',
        'tratturo':    'CAMPANIA_art_142_m_componenti_lineari_archeo',
        'archeo_area': 'CAMPANIA_art_142_m_componenti_areali_archeo',
        'art136':      'CAMPANIA_art_136_vigenti_per_amb_terr_cat_estensione',
    },
    'PUGLIA': {
        'fiume_150m':  'PUGLIA_fiumi-torrenti-acque_pubbliche_150m',
        'archeo_area': 'PUGLIA_142_c1_lett_m_zone_interesse_archeologico',
        'art136':      'PUGLIA_art_136',
    },
    'BASILICATA': {
        'lago_300m':   'BASILICATA_art142_b_laghi_buffer',
        'fiume_150m':  'BASILICATA_art142_c_fiumi',
        'bosco_142g':  'BASILICATA_art142_g_boschi',
        'archeo_area': 'BASILICATA_art142_m_interesse_archeo',
        'art136':      'Basilicata_Art136',          # NB: maiuscola anomala, verificato
    },
    'LAZIO': {
        'usi_civici':  'LAZIO_142_usi_civici',
        'bosco_142g':  'LAZIO_art142_g_boschi',
        'lago_300m':   'LAZIO_art_142_c_1_b_aree_rispetto_laghi',
        'fiume_150m':  'LAZIO_art_142_fascia_150m_fiumi',
        'art136':      'LAZIO_art_136_c_d',
    },
    'PIEMONTE': {
        'fiume_150m':  'PIEMONTE_art_142_fascia_150m_fiumi',
        'lago_300m':   'PIEMONTE_art_142_territori_contermini_laghi',
    },
    'SARDEGNA': {
        'bosco_142g':  'SARDEGNA_art_142_Boschi_D_Lgs_386_2003',
        'fiume_150m':  'SARDEGNA_art_142_fascia_150m_fiumi',
        'lago_300m':   'SARDEGNA_art_142_territori_contermini_laghi',
        'archeo_area': 'SARDEGNA_art_142_zone_interesse_archeo',
        'art136':      'SARDEGNA_art_136',
    },
    'UMBRIA': {
        'usi_civici':  'UMBRIA_Zone_interessate_da_usi_civici',
        'art136':      'UMBRIA_Beni_Paesaggistici_art136',
    },
    'VENETO': {
        'lago_300m':   'VENETO_art.142_lett b_BUFFER 300m_LAGHI',   # NB: spazi e punto nel nome
        'bosco_142g':  'VENETO_c1102071_vincoloforestale',
        'archeo_area': 'VENETO_art_142_c1_lett_m_zone_int_archeo',
    },
    'FVG': {
        'usi_civici':  'FVG_art_142_c_1_h_usi_civici',
        'bosco_142g':  'FVG_art_142_c_1_g_boschi',
        'fiume_150m':  'FVG_art_142_c_1_c_aree_rispetto_fiumi',
        'lago_300m':   'FVG_art_142_c_1_b_aree_rispetto_laghi',
        'art136':      'FVG_Perimetri_Beni_tutelati_art_136_Dlgs_42_2004',
    },
}
CHIAVI_SITAP = ('usi_civici', 'bosco_142g', 'fiume_150m', 'lago_300m', 'tratturo', 'archeo_area', 'art136')
SITAP_LAYERS = SITAP_REGION_LAYERS['CAMPANIA']      # retrocompatibilita'

def sitap_layers(regione):
    return SITAP_REGION_LAYERS.get((regione or '').upper(), {})

# ---------- COPERTURA GEOGRAFICA (fondamentale: mai spacciare "non controllato" per "pulito") ----------
# La Carta Habitat caricata e' REGIONALE (Campania). I layer SITAP esistono solo per alcune regioni
# e con set diversi (es. gli "usi civici" art.142-h esistono SOLO per la Campania).
# Fuori copertura il check NON si fa e va dichiarato non verificato.
HABITAT_REGIONI = {'CAMPANIA'}     # regioni con Carta Habitat REGIONALE (max precisione, codici Natura2000)
# Fuori: fallback NAZIONALE ISPRA "Carta della Natura" (codici CORINE Biotopes) + corrispondenza UFFICIALE
# CORINE -> Direttiva Habitat, estratta dal catalogo ISPRA (Manuali e Linee Guida 49/2009, 229 schede,
# campo "DH" di ogni scheda habitat). Tabella completa: data/raw/habitat_corine_dh.json
# ⚠ Una prima versione di questa lista era EURISTICA e SBAGLIATA (includeva 34.7/34.8 a tappeto e
#   ometteva 35.3): questi sono i codici che ISPRA fa davvero corrispondere a 6210/6220.
CORINE_BAN = (
    '34.313', '34.314', '34.323', '34.326', '34.332', '34.74',   # -> 6210
    '34.5', '34.6', '35.3',                                      # -> 6220
)
CORINE_DH_MAP = RAW / 'habitat_corine_dh.json'    # CORINE -> {nome, dh:[codici Natura2000]}
PROV_REGIONE = {
    'AV': 'CAMPANIA', 'BN': 'CAMPANIA', 'CE': 'CAMPANIA', 'NA': 'CAMPANIA', 'SA': 'CAMPANIA',
    'BA': 'PUGLIA', 'BT': 'PUGLIA', 'BR': 'PUGLIA', 'FG': 'PUGLIA', 'LE': 'PUGLIA', 'TA': 'PUGLIA',
    'MT': 'BASILICATA', 'PZ': 'BASILICATA',
    'CB': 'MOLISE', 'IS': 'MOLISE',
    'CZ': 'CALABRIA', 'CS': 'CALABRIA', 'KR': 'CALABRIA', 'RC': 'CALABRIA', 'VV': 'CALABRIA',
    'FR': 'LAZIO', 'LT': 'LAZIO', 'RI': 'LAZIO', 'RM': 'LAZIO', 'VT': 'LAZIO',
    'AQ': 'ABRUZZO', 'CH': 'ABRUZZO', 'PE': 'ABRUZZO', 'TE': 'ABRUZZO',
    'AG': 'SICILIA', 'CL': 'SICILIA', 'CT': 'SICILIA', 'EN': 'SICILIA', 'ME': 'SICILIA',
    'PA': 'SICILIA', 'RG': 'SICILIA', 'SR': 'SICILIA', 'TP': 'SICILIA',
    'CA': 'SARDEGNA', 'NU': 'SARDEGNA', 'OR': 'SARDEGNA', 'SS': 'SARDEGNA', 'SU': 'SARDEGNA', 'VS': 'SARDEGNA',
    'PG': 'UMBRIA', 'TR': 'UMBRIA',
    # regioni con SITAP che mancavano (Piemonte/Veneto/FVG): senza queste la copertura non si attivava
    'AL': 'PIEMONTE', 'AT': 'PIEMONTE', 'BI': 'PIEMONTE', 'CN': 'PIEMONTE', 'NO': 'PIEMONTE',
    'TO': 'PIEMONTE', 'VB': 'PIEMONTE', 'VC': 'PIEMONTE',
    'BL': 'VENETO', 'PD': 'VENETO', 'RO': 'VENETO', 'TV': 'VENETO', 'VE': 'VENETO', 'VI': 'VENETO', 'VR': 'VENETO',
    'GO': 'FVG', 'PN': 'FVG', 'TS': 'FVG', 'UD': 'FVG',
    # resto d'Italia: nessun layer SITAP mappato, ma almeno la regione viene riconosciuta e dichiarata
    'BG': 'LOMBARDIA', 'BS': 'LOMBARDIA', 'CO': 'LOMBARDIA', 'CR': 'LOMBARDIA', 'LC': 'LOMBARDIA',
    'LO': 'LOMBARDIA', 'MB': 'LOMBARDIA', 'MI': 'LOMBARDIA', 'MN': 'LOMBARDIA', 'PV': 'LOMBARDIA',
    'SO': 'LOMBARDIA', 'VA': 'LOMBARDIA',
    'BO': 'EMILIA-ROMAGNA', 'FC': 'EMILIA-ROMAGNA', 'FE': 'EMILIA-ROMAGNA', 'MO': 'EMILIA-ROMAGNA',
    'PC': 'EMILIA-ROMAGNA', 'PR': 'EMILIA-ROMAGNA', 'RA': 'EMILIA-ROMAGNA', 'RE': 'EMILIA-ROMAGNA',
    'RN': 'EMILIA-ROMAGNA',
    'AR': 'TOSCANA', 'FI': 'TOSCANA', 'GR': 'TOSCANA', 'LI': 'TOSCANA', 'LU': 'TOSCANA',
    'MS': 'TOSCANA', 'PI': 'TOSCANA', 'PO': 'TOSCANA', 'PT': 'TOSCANA', 'SI': 'TOSCANA',
    'AN': 'MARCHE', 'AP': 'MARCHE', 'FM': 'MARCHE', 'MC': 'MARCHE', 'PU': 'MARCHE',
    'GE': 'LIGURIA', 'IM': 'LIGURIA', 'SP': 'LIGURIA', 'SV': 'LIGURIA',
    'TN': 'TRENTINO-ALTO ADIGE', 'BZ': 'TRENTINO-ALTO ADIGE',
    'AO': "VALLE D'AOSTA",
}

# ---------- sigla -> (codice provincia, nome esteso) ----------
# Serve a far parlare fra loro moduli che identificano la provincia in modo diverso:
# `vincoli`/`copertura` ragionano per SIGLA (i layer sono regionali), `capacita`
# interroga il servizio e-Distribuzione che vuole il NOME o il CODICE. Finche' la
# mappa non c'e', chi entra da `blocco.pipeline()` ha la sigla e non puo' chiamare il
# gate di rete: il controllo salta in silenzio (bug trovato in audit il 08/08/2026).
# ⚠ Codici e nomi sono stati VERIFICATI uno per uno contro il layer ProvinceCritiche
#   il 08/08/2026: 110 su 110 combaciano. Non sono ISTAT puri — la Sardegna nel
#   servizio usa codici propri (SS 312, CA 318, NU 114, OR 115) e conserva le quattro
#   province soppresse nel 2016 (OT, OG, VS, CI), mentre SU non c'e'. Se un giorno il
#   servizio cambia, si rigenera da li': e' l'unica fonte che li dichiara insieme.
PROVINCE = {
    'AG': (84, 'Agrigento'), 'AL': (6, 'Alessandria'), 'AN': (42, 'Ancona'),
    'AO': (7, "Valle d'Aosta"), 'AP': (44, 'Ascoli Piceno'), 'AQ': (66, "L'Aquila"),
    'AR': (51, 'Arezzo'), 'AT': (5, 'Asti'), 'AV': (64, 'Avellino'), 'BA': (72, 'Bari'),
    'BG': (16, 'Bergamo'), 'BI': (96, 'Biella'), 'BL': (25, 'Belluno'), 'BN': (62, 'Benevento'),
    'BO': (37, 'Bologna'), 'BR': (74, 'Brindisi'), 'BS': (17, 'Brescia'),
    'BT': (110, 'Barletta-Andria-Trani'), 'BZ': (21, 'Bolzano'), 'CA': (318, 'Cagliari'),
    'CB': (70, 'Campobasso'), 'CE': (61, 'Caserta'), 'CH': (69, 'Chieti'),
    'CI': (119, 'Sulcis Iglesiente'), 'CL': (85, 'Caltanissetta'), 'CN': (4, 'Cuneo'),
    'CO': (13, 'Como'), 'CR': (19, 'Cremona'), 'CS': (78, 'Cosenza'), 'CT': (87, 'Catania'),
    'CZ': (79, 'Catanzaro'), 'EN': (86, 'Enna'), 'FC': (40, 'Forlì-Cesena'), 'FE': (38, 'Ferrara'),
    'FG': (71, 'Foggia'), 'FI': (48, 'Firenze'), 'FM': (109, 'Fermo'), 'FR': (60, 'Frosinone'),
    'GE': (10, 'Genova'), 'GO': (31, 'Gorizia'), 'GR': (53, 'Grosseto'), 'IM': (8, 'Imperia'),
    'IS': (94, 'Isernia'), 'KR': (101, 'Crotone'), 'LC': (97, 'Lecco'), 'LE': (75, 'Lecce'),
    'LI': (49, 'Livorno'), 'LO': (98, 'Lodi'), 'LT': (59, 'Latina'), 'LU': (46, 'Lucca'),
    'MB': (108, 'Monza e della Brianza'), 'MC': (43, 'Macerata'), 'ME': (83, 'Messina'),
    'MI': (15, 'Milano'), 'MN': (20, 'Mantova'), 'MO': (36, 'Modena'), 'MS': (45, 'Massa-Carrara'),
    'MT': (77, 'Matera'), 'NA': (63, 'Napoli'), 'NO': (3, 'Novara'), 'NU': (114, 'Nuoro'),
    'OG': (116, 'Ogliastra'), 'OR': (115, 'Oristano'), 'OT': (113, 'Gallura Nord-Est Sardegna'),
    'PA': (82, 'Palermo'), 'PC': (33, 'Piacenza'), 'PD': (28, 'Padova'), 'PE': (68, 'Pescara'),
    'PG': (54, 'Perugia'), 'PI': (50, 'Pisa'), 'PN': (93, 'Pordenone'), 'PO': (100, 'Prato'),
    'PR': (34, 'Parma'), 'PT': (47, 'Pistoia'), 'PU': (41, 'Pesaro-Urbino'), 'PV': (18, 'Pavia'),
    'PZ': (76, 'Potenza'), 'RA': (39, 'Ravenna'), 'RC': (80, 'Reggio di Calabria'),
    'RE': (35, 'Reggio Emilia'), 'RG': (88, 'Ragusa'), 'RI': (57, 'Rieti'), 'RM': (58, 'Roma'),
    'RN': (99, 'Rimini'), 'RO': (29, 'Rovigo'), 'SA': (65, 'Salerno'), 'SI': (52, 'Siena'),
    'SO': (14, 'Sondrio'), 'SP': (11, 'La Spezia'), 'SR': (89, 'Siracusa'), 'SS': (312, 'Sassari'),
    'SV': (9, 'Savona'), 'TA': (73, 'Taranto'), 'TE': (67, 'Teramo'), 'TN': (22, 'Trento'),
    'TO': (1, 'Torino'), 'TP': (81, 'Trapani'), 'TR': (55, 'Terni'), 'TS': (32, 'Trieste'),
    'TV': (26, 'Treviso'), 'UD': (30, 'Udine'), 'VA': (12, 'Varese'),
    'VB': (103, 'Verbano-Cusio-Ossola'), 'VC': (2, 'Vercelli'), 'VE': (27, 'Venezia'),
    'VI': (24, 'Vicenza'), 'VR': (23, 'Verona'), 'VS': (117, 'Medio Campidano'),
    'VT': (56, 'Viterbo'), 'VV': (102, 'Vibo Valentia'),
}

# ---------- validazione input (QA 16/07/2026) ----------
# Prima non esisteva: lat/lon arrivavano CRUDE a PVGIS/Overpass/WFS. Un punto a caso
# sulla mappa (mare, estero, coordinate invertite) produceva o un crash oscuro o —
# peggio — un dossier dall'aria seria su un terreno inesistente.
ITALIA_BBOX = (35.20, 47.30, 6.50, 18.60)      # (lat_min, lat_max, lon_min, lon_max)


def norm_prov(prov):
    """'  bn ' -> 'BN'. Nessuna sorpresa se l'utente incolla con spazi o minuscole."""
    return (prov or '').strip().upper()


def nome_prov(prov):
    """Sigla -> nome esteso ('BN' -> 'Benevento'). None se la sigla non e' mappata.

    Accetta anche un nome gia' esteso e lo restituisce invariato: i chiamanti
    storici (`blocco --prov-nome`) passano il nome, i nuovi passano la sigla, e
    non deve essere il chiamante a doverlo sapere.
    """
    p = norm_prov(prov)
    if p in PROVINCE:
        return PROVINCE[p][1]
    return prov or None


def cod_prov(prov):
    """Sigla o nome -> codice provincia del servizio e-Distribuzione. None se ignota."""
    p = norm_prov(prov)
    if p in PROVINCE:
        return PROVINCE[p][0]
    for cod, nome in PROVINCE.values():
        if nome.upper() == p:
            return cod
    return None


def sigla_prov(prov):
    """Nome esteso -> sigla ('Benevento' -> 'BN'). Una sigla resta se stessa.

    Chiude il triangolo sigla/nome/codice: i VAM sono per sigla, e-Distribuzione
    vuole nome o codice, e l'utente scrive quello che gli viene comodo.
    """
    p = norm_prov(prov)
    if p in PROVINCE:
        return p
    for s, (_, nome) in PROVINCE.items():
        if nome.upper() == p:
            return s
    return None


class CoordinataNonValida(ValueError):
    """Coordinata fuori dominio: si alza PRIMA di chiamare qualsiasi servizio esterno."""


def valida_coordinate(lat, lon):
    """Alza CoordinataNonValida con un messaggio leggibile, o ritorna (lat, lon) float.

    Regola: meglio un errore chiaro subito che un dossier plausibile e falso.
    """
    if lat is None or lon is None:
        raise CoordinataNonValida('coordinate mancanti: servono sia latitudine sia longitudine')
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise CoordinataNonValida(f'coordinate non numeriche: lat={lat!r} lon={lon!r}')
    if lat != lat or lon != lon:                       # NaN: ogni confronto e' False -> passerebbe tutto
        raise CoordinataNonValida('coordinate NaN')
    if not (-90 <= lat <= 90):
        raise CoordinataNonValida(f'latitudine {lat} fuori range (-90..90)')
    if not (-180 <= lon <= 180):
        raise CoordinataNonValida(f'longitudine {lon} fuori range (-180..180)')
    la0, la1, lo0, lo1 = ITALIA_BBOX
    if not (la0 <= lat <= la1 and lo0 <= lon <= lo1):
        # caso frequentissimo: lat/lon invertite. Diciamolo invece di far indovinare.
        if la0 <= lon <= la1 and lo0 <= lat <= lo1:
            raise CoordinataNonValida(
                f'punto fuori Italia ({lat}, {lon}) — sembrano invertite: intendevi ({lon}, {lat})?')
        raise CoordinataNonValida(
            f'punto fuori Italia ({lat}, {lon}): land-scout usa cartografia italiana '
            '(catasto, SITAP, Natura 2000 IT, portale VIA) e qui non avrebbe nulla da verificare')
    return lat, lon


def latlon(x, y):
    """Riconosce l'ordine di una coppia di coordinate, o ALZA.

    Il GeoJSON standard e' (lon, lat), ma diversi GeoServer italiani rispondono
    (lat, lon) e altri — se non si passa `srsName` — in coordinate proiettate.
    La vecchia regola era «se non sembra (lat, lon) allora e' (lon, lat)»: su
    coordinate metriche non sbaglia in modo visibile, proietta e basta, e i
    poligoni finiscono lontanissimo. Nel caso del PAI questo si e' tradotto in
    «nessun vincolo frane» su tutte le particelle (audit 08/08/2026).

    Qui cio' che non e' riconoscibile alza: un errore rumoroso e' sempre meglio
    di un "pulito" silenzioso.
    """
    la0, la1, lo0, lo1 = ITALIA_BBOX
    if la0 <= x <= la1 and lo0 <= y <= lo1:
        return float(x), float(y)
    if la0 <= y <= la1 and lo0 <= x <= lo1:
        return float(y), float(x)
    raise CoordinataNonValida(
        f'coppia ({x}, {y}) non interpretabile come lat/lon in Italia: il servizio '
        'ha probabilmente risposto in un altro CRS (tipico: EPSG:3857 in metri). '
        'Passare srsName=EPSG:4326 nella query.')


def copertura(prov):
    """Cosa possiamo davvero verificare per questa provincia (mai assumere: dichiarare)."""
    reg = PROV_REGIONE.get(norm_prov(prov))
    lay = sitap_layers(reg)
    return {'prov': prov, 'regione': reg,
            'habitat_regionale': reg in HABITAT_REGIONI,   # carta regionale autorevole
            'habitat': True,                               # sempre: regionale o fallback ISPRA nazionale
            'habitat_fonte': ('carta regionale (codici Natura2000)' if reg in HABITAT_REGIONI
                              else 'ISPRA Carta della Natura 1:50.000 + corrispondenza ufficiale CORINE→DH'),
            'sitap': bool(lay),
            'sitap_layer': sorted(lay.keys()),             # cosa e' davvero controllabile qui
            'sitap_mancanti': [k for k in CHIAVI_SITAP if k not in lay],
            'natura2000': True}      # confini ZPS/SIC da EEA: nazionali/europei


# ---------- parametri di dominio ----------
BAN_CODES = ('6210', '6220')          # habitat con divieto FV a terra in ZPS (DGR Campania 617/2024)
MWP_HA = {'agriPV': (0.6, 0.8), 'PV': (0.8, 1.0)}
EUR_MWH = (60, 90)                    # banda prezzo energia indicativa (PPA/mercato IT)
# ancore €/ha terra (progetto Morcone lug-2026: quota EDPR + comparabile RWE-Pontelandolfo)
# ATTENZIONE: valori di ESEMPIO, non raccomandazioni di mercato.
# Vanno sostituiti con i comparabili osservati nella propria zona.
EUR_HA_TERRA = {'secco': 20_000, 'target_postvinca': 50_000, 'apertura': 60_000}
TTL_GIORNI = {'geocode': 365, 'pvgis': 365, 'habitat': 180, 'census': 30}

# ---------- v0.2 (19/07/2026): indicatori aggiunti dopo audit checklist ----------
# Filosofia invariata: un indicatore ASSENTE dal dict parcel non vale "pulito".
# score_parcel lo ignora e engine.vincoli_non_verificati() dichiara cosa non e' stato controllato.

# --- soglie e fasce di rispetto (legge o prassi consolidata) ---
BUFFER_BENI_TUTELATI_M = 500     # DL Semplificazioni: fascia dai beni tutelati per FV (agriPV: deroghe)
BUFFER_BOSCO_M = 100             # distanza dal LIMITE del bosco (diverso dall'essere dentro il bosco)
BUFFER_CIMITERO_M = 200          # R.D. 1265/1934 art.338
FASCIA_FERROVIA_M = 30           # DPR 753/1980
FASCIA_STRADA_M = {'A': 60, 'B': 40, 'C': 30, 'F_extraurbana': 20}   # DPR 495/1992, fuori centro abitato

# --- aree idonee / non idonee (D.Lgs 199/2021 art.20 + DM 21/06/2024 + legge regionale) ---
# Il DM 21/06/2024 impone alle Regioni di individuare le aree entro 180 gg dal 3/07/2024.
# TAR Campania: solo Stato e Regioni possono definirle -> divieti nei PUC comunali illegittimi.
AREE_IDONEE_BONUS = 10           # iter accelerato: vale punti veri
AREE_NON_IDONEE_BLOCKER = True   # area dichiarata NON idonea: iter di fatto precluso

# --- agrivoltaico Campania: Circolare Dir. Politiche Agricole n. 481104/2026 ---
PLV_MIN_RESIDUA = 0.80           # va certificata almeno l'80% della Produzione Lorda Vendibile preesistente
# NON idonei all'agrivoltaico in Campania: vigneti/oliveti iscritti al Registro nazionale dei
# paesaggi rurali storici e vigneti eroici/storici (decreti dedicati).
COLTURE_STORICHE_BLOCKER = True

# --- rete: il "moltiplicatore di valore" tradotto in euro ---
EUR_KM_CAVIDOTTO = (100_000, 150_000)   # scavo + posa cavidotto interrato MT/AT
D_SE_LIMITE_ECONOMICO_M = 5_000         # oltre ~5 km il costo di connessione erode il margine

# --- blocco contiguo bancabile (Fase 32, `blocco.py`) ---
# Un vincolo che copre meta' particella la rende inutile; uno che ne sfiora un bordo si
# risolve arretrando i moduli. Quindi soglie di ESCLUSIONE alte, e sotto soglia si
# SOTTRAGGONO gli ettari invece di buttare via il fondo.
BLOCCO_BOSCO_MAX_PCT = 50.0       # art.142-g: oltre, non e' un campo con alberi
BLOCCO_FASCIA_MAX_PCT = 25.0      # art.142-b/c (lago 300 m, fiume 150 m): oltre, la fascia mangia il lotto
BLOCCO_EDIFICATO_MAX_PCT = 15.0   # coerente con occupazione.py: oltre, e' un lotto edificato
BLOCCO_HA_MIN_NETTI = 0.05        # sotto, e' una controparte senza superficie
BLOCCO_ADIACENZA_M = 15.0         # scavalca stradine interpoderali e fossi fra fondi confinanti
# Le quote vincolate si SOMMANO, non si moltiplicano: non sappiamo se si sovrappongono, e la
# stima prudente e' quella che non promette ettari inesistenti.
BLOCCO_DETRAZIONI_ADDITIVE = True
# Agrivoltaico avanzato: moduli radi e sollevati per far passare le macchine, quindi NON si
# applica il ~0,7 MWp/ha del FV a terra.
MWP_PER_HA_AGRIPV = (0.35, 0.55)
# Soglie di allarme sulla bancabilita'.
BLOCCO_MAX_CONTROPARTI = 30       # oltre, il developer si tira indietro per costo di aggregazione
BLOCCO_QUOTA_OSTAGGIO_PCT = 15.0  # una particella che pesa di piu' da' al proprietario un veto di fatto

# --- endpoint dei nuovi controlli. ⚠ NON VERIFICATI LIVE: i fetcher in vincoli.py sono da
# implementare e ogni URL va confermato prima dell'uso (mai dare per buono un layer non testato).
EP_V2_DA_VERIFICARE = {
    'aree_protette_euap':   'https://sgi.isprambiente.it/geoserver/wfs',       # Parchi/Riserve (EUAP) - da confermare
    'vincolo_idrogeologico':'https://sit2.regione.campania.it/geoserver/wfs',  # R.D. 3267/1923 - da confermare
    'aree_idonee_campania': None,   # layer regionale aree idonee: da individuare
    'dop_igp':              'https://www.qualigeo.eu/',                        # zonazioni DOP/IGP/DOCG
    'catasto_incendi':      None,   # L.353/2000: spesso solo albo comunale (PDF)
    'terna_capacita':       'https://www.terna.it/it/sistema-elettrico/rete/connessioni',
}


def info():
    return {'HOME': str(HOME), 'DATA': str(DATA), 'CACHE': str(CACHE_DIR),
            'CENSUS': str(CENSUS), 'census_esiste': CENSUS.exists(),
            'HABITAT_ZIP': str(HABITAT_ZIP), 'habitat_scaricato': HABITAT_ZIP.exists()}


if __name__ == '__main__':
    import json, sys
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass
    print(json.dumps(info(), indent=1, ensure_ascii=False))
