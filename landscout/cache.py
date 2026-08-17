"""land-scout — CACHE (v0.1, 15/07/2026): cache unica con TTL per fonti lente/intermittenti.

Perche': le fonti pubbliche sono lente (Nominatim 1 req/s), intermittenti (SITAP cade),
o pesanti (shapefile habitat 17 MB). Prima ogni modulo si faceva la sua cache a mano,
senza scadenza e senza sapere quando il dato era stato preso.

Due primitive:
  JsonCache(nome)          -> dizionario persistente con TTL per chiave
  cached_file(url, nome)   -> scarica una volta e riusa il file (TTL lungo)

Nota progettuale: la cache NON deve mai trasformare un errore in un dato.
Se il fetch fallisce, si ritorna None e il chiamante dichiara "non verificato"
(vedi il pattern sitap_ok in vincoli.py) — mai spacciare "non controllato" per "pulito".
"""
import json, os, threading, time, urllib.request
from pathlib import Path
from landscout.config import CACHE_DIR, UA, TIMEOUT, TTL_GIORNI

_DAY = 86400.0

# Un lock PER FILE, condiviso da tutte le istanze: due JsonCache diverse sullo stesso path
# devono escludersi a vicenda (un lock per istanza non servirebbe a niente).
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _lock_per(path):
    k = str(Path(path).resolve())
    with _LOCKS_GUARD:
        if k not in _LOCKS:
            _LOCKS[k] = threading.RLock()
        return _LOCKS[k]


class JsonCache:
    """Dizionario persistente su file, con TTL per chiave. Uso:
        c = JsonCache('geocode', ttl_giorni=365)
        v = c.get(key)
        if v is None: v = fetch(); c.set(key, v)
    """
    def __init__(self, nome, ttl_giorni=None):
        self.path = Path(CACHE_DIR) / f'{nome}_cache.json'
        # ⚠ QA 16/07: `if self.ttl` trattava ttl=0 come falsy -> "TTL 0 giorni" significava
        # **mai scadere** invece di **sempre scaduto**, l'opposto esatto dell'intenzione.
        # Trappola latente classica dello zero-falsy: qui si distingue None (usa il default)
        # da 0 (scade sempre) in modo esplicito.
        self.ttl = (TTL_GIORNI.get(nome, 365) if ttl_giorni is None else ttl_giorni) * _DAY
        self._d = {}
        if self.path.exists():
            try:
                self._d = json.loads(self.path.read_text(encoding='utf-8'))
            except Exception:
                self._d = {}

    def get(self, key, default=None):
        e = self._d.get(key)
        if not isinstance(e, dict) or '_v' not in e:
            return default                      # formato vecchio/assente
        # ttl<=0 -> sempre scaduto, senza guardare l'orologio.
        # ⚠ QA 16/07, secondo strato dello stesso bug: con `eta > self.ttl` e ttl=0, una voce
        # scritta e riletta nello stesso tick di clock dava eta ESATTAMENTE 0.0 -> 0.0 > 0.0
        # e' False -> il dato "sempre scaduto" veniva servito. Su Windows time.time() ha
        # risoluzione ~15,6 ms, quindi il baco compariva o spariva a seconda di quanto era
        # veloce la macchina: un intermittente, il tipo peggiore da inseguire.
        if self.ttl <= 0:
            return default
        if (time.time() - e.get('_t', 0)) >= self.ttl:
            return default                      # scaduto
        return e['_v']

    def set(self, key, value):
        self._d[key] = {'_v': value, '_t': time.time()}
        self.flush()

    def flush(self):
        """Scrive su disco fondendo con quello che c'e' gia'.

        ⚠ QA 16/07 — la versione precedente riscriveva tutto il file dalla propria copia in
        memoria (`tmp.write_text(json.dumps(self._d))`). Con 8 thread che scrivevano 12 chiavi
        ciascuno, nel file ne restavano **12 su 96**: ogni thread cancellava le chiavi degli
        altri, perche' non le aveva mai lette (lost update). E l'API i dossier li esegue
        proprio a thread, quindi non e' un caso di scuola. In piu' su Windows `tmp.replace()`
        falliva con PermissionError [WinError 32] quando due thread rinominavano insieme.

        Fix in tre pezzi: (1) un lock **per file** (non per istanza: due JsonCache diverse
        sullo stesso path devono escludersi a vicenda); (2) **rilettura e merge** prima di
        scrivere, cosi' non si cancella il lavoro altrui; (3) tmp con nome **univoco per
        thread** + retry sul rename, che su Windows puo' fallire per una manciata di ms.
        """
        with _lock_per(self.path):
            disco = {}
            if self.path.exists():
                try:
                    disco = json.loads(self.path.read_text(encoding='utf-8'))
                except Exception:
                    disco = {}                     # file illeggibile: si riparte da capo
            if not isinstance(disco, dict):
                disco = {}
            # vince la voce piu' RECENTE, chiave per chiave: cosi' due processi che scrivono
            # cose diverse convergono invece di sovrascriversi.
            for k, v in self._d.items():
                vecchia = disco.get(k)
                if (not isinstance(vecchia, dict) or '_t' not in vecchia
                        or v.get('_t', 0) >= vecchia.get('_t', 0)):
                    disco[k] = v
            self._d = disco
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
            tmp.write_text(json.dumps(disco, ensure_ascii=False), encoding='utf-8')
            for tentativo in range(5):             # Windows: il rename puo' collidere
                try:
                    tmp.replace(self.path)
                    return
                except PermissionError:
                    time.sleep(0.02 * (tentativo + 1))
            try:
                tmp.unlink(missing_ok=True)        # non lasciare rifiuti in giro
            except Exception:
                pass
            raise OSError(f'cache: impossibile aggiornare {self.path} (file occupato)')

    def migra_da(self, vecchio_path, wrap=True):
        """Importa una vecchia cache "piatta" ({k: v}) senza perderla."""
        p = Path(vecchio_path)
        if not p.exists():
            return 0
        try:
            old = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            return 0
        n = 0
        for k, v in old.items():
            if k not in self._d:
                self._d[k] = {'_v': v, '_t': time.time()} if wrap else v
                n += 1
        if n:
            self.flush()
        return n

    def __len__(self):
        return len(self._d)


def cached_file(url, nome, ttl_giorni=None, forza=False):
    """Scarica una volta e riusa. Ritorna Path o None se il download fallisce.
    Non solleva: il chiamante decide come degradare."""
    dest = Path(CACHE_DIR) / nome
    ttl = (ttl_giorni if ttl_giorni is not None else 180) * _DAY
    if dest.exists() and not forza:
        if not ttl or (time.time() - dest.stat().st_mtime) < ttl:
            return dest
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=max(TIMEOUT, 300)) as r:
            data = r.read()
        tmp = dest.with_suffix(dest.suffix + '.part')
        tmp.write_bytes(data)
        tmp.replace(dest)
        return dest
    except Exception:
        return dest if dest.exists() else None      # se ho una copia vecchia, meglio quella che niente


def get_json(url, timeout=None):
    """GET JSON senza cache (per chiamate gia' filtrate per bbox). Ritorna None su errore."""
    try:
        req = urllib.request.Request(url, headers=UA)
        return json.loads(urllib.request.urlopen(req, timeout=timeout or TIMEOUT).read().decode('utf-8', 'replace'))
    except Exception:
        return None
