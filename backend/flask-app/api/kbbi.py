import os
import re
import glob
import json
import time
from flask import Blueprint, request, jsonify, current_app

# Prefer ujson if available
try:
    import ujson as _ujson
except Exception:
    _ujson = None

kbbi_bp = Blueprint("kbbi", __name__)

# Paths
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DATA_DIR = os.path.join(APP_DIR, "data")
KBBI_FILE_GLOB = os.path.join(LIB_DATA_DIR, "kbbi_v_part*.json")
# Support multiple word DB shards: kbbi_word_data.json, kbbi_word_data1.json, ...
KBBI_WORD_DB_GLOB = os.path.join(LIB_DATA_DIR, "kbbi_word_data*.json")
# Backward-compatible default constant name
WORD_DB_JSON = os.path.join(LIB_DATA_DIR, "kbbi_word_data.json")

os.makedirs(LIB_DATA_DIR, exist_ok=True)

# KBBI simple (offline-ish) fallback
try:
    from kbbi_simple import cari_kata, get_saran
    KBBI_SIMPLE_AVAILABLE = True
except Exception as _kbbi_imp_err:
    KBBI_SIMPLE_AVAILABLE = False
    try:
        current_app.logger.warning("kbbi_simple import failed: %r", _kbbi_imp_err)  # may not exist yet
    except Exception:
        pass

    def cari_kata(kata):
        return None

    def get_saran(kata):
        return []

# KBBI online (primary)
try:
    from kbbi import KBBI as KBBIOnline, TidakDitemukan as KBBI_TidakDitemukan
    KBBI_ONLINE_AVAILABLE = True
except Exception as _kbbi_online_err:
    KBBI_ONLINE_AVAILABLE = False
    try:
        # current_app may not be available yet
        pass
    except Exception:
        pass

# Online cache and rate limiting
_KBBI_CACHE = {}  # key_norm -> {ts: epoch, payload: dict}
_KBBI_CACHE_TTL = 6 * 3600  # 6 jam
_RATE_BUCKET = {}  # ip -> [timestamps]
_RATE_LIMIT_MAX = 60
_RATE_LIMIT_WINDOW = 60  # 60 dtk

# Offline indices
_kbbi_index = None
_KBBI_WORD_INDEX = None  # {"by_key":{}, "by_lema":{}, "orig_key":{}, "raw":{}}


def _kbbi_normalize(s: str) -> str:
    """
    Normalize input/lemma for lookup:
      - lowercase
      - remove punctuation (keep letters/digits/spaces)
      - collapse spaces
      - example: 'pi.jar' -> 'pijar'
    """
    s = (s or "").strip().lower()
    # remove all punctuation (keep word chars and spaces), then drop underscores
    s = re.sub(r"[^\w\s]+", "", s, flags=re.UNICODE)
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _kbbi_load_all_parts():
    """
    Load and concatenate all KBBI part files.
    Prefer ujson for speed if available, fallback to stdlib json.
    Supports file shapes:
      - [ { group_with_entri: [...] } , ... ]
      - [ {entry}, ... ]
      - { "entri": [ {entry}, ... ], ... }
      - { "data": [ {entry}, ... ], ... }
      - { "daftar": [ { entri: [...] } , ... ] }
      - { single_entry_fields... }
    Also supports "concatenated JSON" (multiple JSON objects back-to-back).
    """

    def _multi_json_objects(text: str):
        objs = []
        dec = json.JSONDecoder()
        idx = 0
        n = len(text)
        while idx < n:
            # skip whitespace
            while idx < n and text[idx].isspace():
                idx += 1
            if idx >= n:
                break
            try:
                obj, end = dec.raw_decode(text, idx)
                objs.append(obj)
                idx = end
            except Exception:
                # advance one char to avoid infinite loop on malformed spots
                idx += 1
        return objs

    appended_ids = set()

    def _is_entry(obj) -> bool:
        if not isinstance(obj, dict):
            return False
        if "makna" in obj and any(k in obj for k in ("nama", "lema", "kata")):
            return True
        return False

    def _extract_entries(obj, out_list):
        if isinstance(obj, dict):
            # Direct known container keys
            for key in ("entri", "entries"):
                v = obj.get(key)
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, dict):
                            if id(it) not in appended_ids:
                                out_list.append(it)
                                appended_ids.add(id(it))
            # Other container keys that may contain nested objects with "entri"
            for key in ("data", "daftar", "list", "result", "results"):
                v = obj.get(key)
                if isinstance(v, list):
                    for it in v:
                        _extract_entries(it, out_list)
            # Recurse remaining dict values
            for k, v in obj.items():
                if k not in ("entri", "entries", "data", "daftar", "list", "result", "results"):
                    _extract_entries(v, out_list)
            # As a last resort, treat this dict as an entry if it looks like one
            if _is_entry(obj) and id(obj) not in appended_ids:
                out_list.append(obj)
                appended_ids.add(id(obj))
        elif isinstance(obj, list):
            for it in obj:
                _extract_entries(it, out_list)

    entries = []
    paths = sorted(glob.glob(KBBI_FILE_GLOB))
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = f.read()

            objs = _multi_json_objects(raw)
            if not objs:
                try:
                    objs = [(_ujson.loads(raw) if _ujson else json.loads(raw))]
                except Exception:
                    objs = []

            for data in objs:
                _extract_entries(data, entries)
        except Exception as e:
            try:
                current_app.logger.warning("KBBI load failed for %s: %s", p, e)
            except Exception:
                pass
    return entries


def _kbbi_build_index():
    """
    Build an index: normalized_lemma -> { lema: [original lemma variants], definisi: [strings] }
    """
    global _kbbi_index
    if _kbbi_index is not None:
        return _kbbi_index

    idx = {}
    for entry in _kbbi_load_all_parts():
        # Robustly extract lemma/name; some entries may have non-string "nama"
        raw_nama = entry.get("nama")
        nama = None
        if isinstance(raw_nama, str):
            nama = raw_nama.strip()
        else:
            for k in ("lema", "kata"):
                v = entry.get(k)
                if isinstance(v, str):
                    nama = v.strip()
                    break
        if not nama and isinstance(raw_nama, dict):
            # Last resort: try nested fields inside "nama" object if present
            for kk in ("text", "value", "nama"):
                vv = raw_nama.get(kk) if hasattr(raw_nama, "get") else None
                if isinstance(vv, str) and vv.strip():
                    nama = vv.strip()
                    break
        if not nama:
            continue
        key = _kbbi_normalize(nama)
        if not key:
            continue

        # Collect definitions
        defs = []
        makna = entry.get("makna") or []
        if isinstance(makna, list):
            for m in makna:
                if not isinstance(m, dict):
                    # Sometimes it might be plain string
                    txt = str(m).strip()
                    if txt:
                        defs.append(txt)
                    continue
                # kelas: list of dicts with kode/nama
                label = ""
                klist = m.get("kelas") or []
                if isinstance(klist, list) and klist:
                    k0 = klist[0]
                    if isinstance(k0, dict):
                        label = (k0.get("kode") or k0.get("nama") or "").strip()
                # submakna could be list of strings
                sub = m.get("submakna") or m.get("arti") or m.get("definisi") or []
                if isinstance(sub, list):
                    for s in sub:
                        st = str(s).strip()
                        if not st:
                            continue
                        defs.append(f"[{label}] {st}" if label else st)
                elif isinstance(sub, str):
                    st = sub.strip()
                    if st:
                        defs.append(f"[{label}] {st}" if label else st)

        bucket = idx.get(key)
        if not bucket:
            bucket = {"lema": set(), "definisi": []}
            idx[key] = bucket
        bucket["lema"].add(nama)
        # Deduplicate while preserving order
        for d in defs:
            if d and d not in bucket["definisi"]:
                bucket["definisi"].append(d)

    # finalize sets to lists
    for k, v in idx.items():
        v["lema"] = sorted(v["lema"])

    _kbbi_index = idx
    return _kbbi_index


def _first_kelas(m):
    """
    Extract first class code/name from a makna item.
    """
    klist = m.get("kelas") or []
    cls = ""
    if isinstance(klist, list) and klist:
        k0 = klist[0]
        if isinstance(k0, dict):
            cls = (k0.get("kode") or k0.get("nama") or "").strip()
        elif isinstance(k0, str):
            cls = k0.strip()
    elif isinstance(klist, str):
        cls = klist.strip()
    return cls


def _kbbi_transform_word_record(rec):
    """
    Transform one record (with .data.entri[]) into API segments:
      - entri: [{lema, makna:[{kelas, deskripsi, contoh:[], sinonim:[], antonim:[]}]}]
      - lema: [str]
      - definisi: ["[kelas] deskripsi", ...]
    """
    data = (rec or {}).get("data") or {}
    ent = data.get("entri") or []
    entri_payload = []
    lemma = []
    definisi = []
    if isinstance(ent, list):
        for e in ent:
            if not isinstance(e, dict):
                continue
            nama = e.get("nama") or e.get("lema") or ""
            if isinstance(nama, str) and nama.strip():
                lemma.append(nama.strip())
            makna_src = e.get("makna") or []
            makna_list = []
            if isinstance(makna_src, list):
                for m in makna_src:
                    if not isinstance(m, dict):
                        continue
                    cls = _first_kelas(m)
                    subs = m.get("submakna") or m.get("arti") or m.get("definisi") or []
                    contoh = m.get("contoh") if isinstance(m.get("contoh"), list) else []
                    sinonim = m.get("sinonim") if isinstance(m.get("sinonim"), list) else []
                    antonim = m.get("antonim") if isinstance(m.get("antonim"), list) else []
                    if isinstance(subs, list):
                        for s in subs:
                            st = str(s).strip()
                            if not st:
                                continue
                            mk = {
                                "kelas": cls,
                                "deskripsi": st,
                                "contoh": contoh,
                                "sinonim": sinonim,
                                "antonim": antonim,
                            }
                            makna_list.append(mk)
                            definisi.append(f"[{cls}] {st}" if cls else st)
                    elif isinstance(subs, str) and subs.strip():
                        st = subs.strip()
                        mk = {
                            "kelas": cls,
                            "deskripsi": st,
                            "contoh": contoh,
                            "sinonim": sinonim,
                            "antonim": antonim,
                        }
                        makna_list.append(mk)
                        definisi.append(f"[{cls}] {st}" if cls else st)
            entri_payload.append({"lema": nama, "makna": makna_list})

    # Deduplicate lemma while preserving order
    seen = set()
    lemma_unique = []
    for l in lemma:
        if l not in seen:
            lemma_unique.append(l)
            seen.add(l)

    return {
        "lema": lemma_unique,
        "definisi": definisi,
        "entri": entri_payload,
    }


def _kbbi_load_word_db_raw():
    """
    Load raw word database JSON shards as a combined dict.
    Supports multiple files matching KBBI_WORD_DB_GLOB.
    Returns empty dict on error.
    """
    combined = {}
    try:
        paths = sorted(glob.glob(KBBI_WORD_DB_GLOB))
        for p in paths:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    obj = json.load(f)
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        # keep first occurrence to avoid accidental overwrite
                        if k not in combined:
                            combined[k] = v
            except Exception as e:
                try:
                    current_app.logger.warning("Failed loading word DB shard %s: %s", p, e)
                except Exception:
                    pass
    except Exception:
        pass
    return combined


def _kbbi_build_word_index():
    """
    Build indices for fast lookup:
      - by_key: normalized top-level key -> record
      - by_lema: normalized entri.nama/lema -> record
      - orig_key: normalized top-level key -> original key string
      - raw: the raw dict
    """
    global _KBBI_WORD_INDEX
    if _KBBI_WORD_INDEX is not None:
        return _KBBI_WORD_INDEX

    raw = _kbbi_load_word_db_raw()
    by_key = {}
    by_lema = {}
    orig_key = {}
    for k, rec in (raw.items() if isinstance(raw, dict) else []):
        nk = _kbbi_normalize(k)
        if nk:
            by_key[nk] = rec
            orig_key[nk] = k
        data = (rec or {}).get("data") or {}
        entri = data.get("entri") or []
        if isinstance(entri, list):
            for ent in entri:
                if isinstance(ent, dict):
                    nama = ent.get("nama") or ent.get("lema")
                    if isinstance(nama, str):
                        ln = _kbbi_normalize(nama)
                        if ln and ln not in by_lema:
                            by_lema[ln] = rec
    _KBBI_WORD_INDEX = {"by_key": by_key, "by_lema": by_lema, "orig_key": orig_key, "raw": raw}
    return _KBBI_WORD_INDEX


def _kbbi_lookup_word_db(kata):
    """
    Lookup kata in kbbi_word_data.json (by top-level key or by entri.nama/lema).
    Returns transformed dict or None.
    """
    idx = _kbbi_build_word_index()
    norm = _kbbi_normalize(kata)
    rec = idx["by_key"].get(norm) or idx["by_lema"].get(norm)
    if not rec:
        return None
    return _kbbi_transform_word_record(rec)


def _kbbi_word_suggestions(prefix_norm: str, limit: int = 10):
    """
    Suggest using original keys from word DB matching a normalized prefix.
    """
    idx = _kbbi_build_word_index()
    out = []
    for nkey, orig in idx["orig_key"].items():
        if nkey.startswith(prefix_norm):
            out.append(orig)
            if len(out) >= limit:
                break
    return out


@kbbi_bp.get("/api/kbbi/cek")
def kbbi_cek():
    """
    Query: ?kata=...
    Returns (online-first dengan offline fallback dan word-db):
      200: {
        valid: true, kata, lema: ["..."], definisi: ["..."],
        entri: [{lema, makna:[{kelas, deskripsi, contoh:[], sinonim:[], antonim:[]}]}],
        saran: [], sumber: "kbbi-online"|"kbbi-offline"|"kbbi-worddb"|"kbbi-simple", cache_hit: bool
      }
      404: { valid: false, error: "kata tidak ditemukan", saran: [...] }
      400: { error: "parameter 'kata' wajib diisi" }
      429: { error: "Terlalu banyak permintaan, coba lagi nanti." }
    """
    kata = (request.args.get("kata") or "").strip()
    if not kata:
        return jsonify({"error": "parameter 'kata' wajib diisi"}), 400

    # Rate limiting sederhana per-IP
    try:
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    except Exception:
        ip = ""
    now_ts = time.time()
    bucket = _RATE_BUCKET.get(ip, [])
    bucket = [t for t in bucket if now_ts - t < _RATE_LIMIT_WINDOW]
    if len(bucket) >= _RATE_LIMIT_MAX:
        return jsonify({"error": "Terlalu banyak permintaan, coba lagi nanti."}), 429
    bucket.append(now_ts)
    _RATE_BUCKET[ip] = bucket

    key_norm = _kbbi_normalize(kata)
    try:
        current_app.logger.info("kbbi_cek query kata=%r norm=%r simple=%r", kata, key_norm, KBBI_SIMPLE_AVAILABLE)
    except Exception:
        pass

    # Cache hit?
    c = _KBBI_CACHE.get(key_norm)
    if c and (now_ts - (c.get("ts") or 0) < _KBBI_CACHE_TTL):
        payload = dict(c.get("payload") or {})
        if payload:
            payload["cache_hit"] = True
            return jsonify(payload)

    # Try KBBI online first
    if 'KBBI_ONLINE_AVAILABLE' in globals() and KBBI_ONLINE_AVAILABLE:
        try:
            obj = KBBIOnline(kata)
            serial = obj.serialisasi()
            # Map online serialization to expected entri format
            entri_src = serial.get("entri") or []
            entri_payload = []
            if isinstance(entri_src, list):
                for ent in entri_src:
                    if not isinstance(ent, dict):
                        continue
                    nama = ent.get("nama") or ent.get("lema") or None
                    makna_list = []
                    for m in (ent.get("makna") or []):
                        if not isinstance(m, dict):
                            continue
                        cls = ""
                        klist = m.get("kelas") or []
                        if isinstance(klist, list) and klist:
                            k0 = klist[0]
                            if isinstance(k0, dict):
                                cls = (k0.get("kode") or k0.get("nama") or "").strip()
                        sub = m.get("submakna") or m.get("arti") or m.get("definisi") or []
                        deskr = ""
                        if isinstance(sub, list) and sub:
                            deskr = str(sub[0]).strip()
                        elif isinstance(sub, str):
                            deskr = sub.strip()
                        contoh = m.get("contoh") or []
                        sinonim = m.get("sinonim") or []
                        antonim = m.get("antonim") or []
                        makna_list.append({
                            "kelas": cls,
                            "deskripsi": deskr,
                            "contoh": contoh if isinstance(contoh, list) else [],
                            "sinonim": sinonim if isinstance(sinonim, list) else [],
                            "antonim": antonim if isinstance(antonim, list) else [],
                        })
                    entri_payload.append({"lema": nama, "makna": makna_list})
            lemma = []
            for e in entri_payload:
                nm = e.get("lema")
                if nm:
                    lemma.append(nm)
            definisi = []
            for e in entri_payload:
                for m in e.get("makna", []):
                    d = m.get("deskripsi")
                    if d:
                        definisi.append(f"[{m['kelas']}] {d}" if m.get("kelas") else d)
            payload = {
                "valid": True,
                "kata": kata,
                "lema": sorted(list({*lemma})),
                "definisi": definisi,
                "entri": entri_payload,
                "saran": [],
                "sumber": "kbbi-online",
                "cache_hit": False,
            }
            _KBBI_CACHE[key_norm] = {"ts": now_ts, "payload": payload}
            try:
                current_app.logger.info("kbbi_cek online-hit kata=%r", kata)
            except Exception:
                pass
            return jsonify(payload)
        except Exception as ex_online:
            # Jika tidak ditemukan oleh KBBI online, kirim 404 dengan saran dari online jika tersedia
            try:
                if isinstance(ex_online, KBBI_TidakDitemukan):
                    saran = []
                    try:
                        _obj = getattr(ex_online, "objek", None)
                        saran = getattr(_obj, "saran_entri", []) if _obj else []
                    except Exception:
                        saran = []
                    if not saran and KBBI_SIMPLE_AVAILABLE:
                        try:
                            saran = get_saran(kata)
                        except Exception:
                            pass
                    return jsonify({"valid": False, "error": "kata tidak ditemukan", "saran": saran}), 404
            except Exception:
                pass
            try:
                current_app.logger.warning("KBBI online lookup error for %r: %r", kata, ex_online)
            except Exception:
                pass
            # fall through to simple/worddb/offline

    # Try Word DB (kbbi_word_data.json)
    try:
        wd = _kbbi_lookup_word_db(kata)
        if wd:
            payload = {
                "valid": True,
                "kata": kata,
                "lema": wd.get("lema", []),
                "definisi": wd.get("definisi", []),
                "entri": wd.get("entri", []),
                "saran": [],
                "sumber": "kbbi-worddb",
                "cache_hit": False,
            }
            _KBBI_CACHE[key_norm] = {"ts": now_ts, "payload": payload}
            try:
                current_app.logger.info("kbbi_cek worddb-hit kata=%r", kata)
            except Exception:
                pass
            return jsonify(payload)
    except Exception as ex_worddb:
        try:
            current_app.logger.warning("KBBI worddb lookup error for %r: %r", kata, ex_worddb)
        except Exception:
            pass

    # Try simple KBBI implementation
    if KBBI_SIMPLE_AVAILABLE:
        try:
            data = cari_kata(kata)
            if data:
                payload = {
                    "valid": True,
                    "kata": kata,
                    "lema": data.get("lema", []),
                    "definisi": data.get("definisi", []),
                    "entri": data.get("entri", []),
                    "saran": [],
                    "sumber": "kbbi-simple",
                    "cache_hit": False,
                }
                _KBBI_CACHE[key_norm] = {"ts": now_ts, "payload": payload}
                try:
                    current_app.logger.info("kbbi_cek simple-hit kata=%r", kata)
                except Exception:
                    pass
                return jsonify(payload)
        except Exception as ex:
            try:
                current_app.logger.warning("KBBI simple lookup failed for %r: %r", kata, ex)
            except Exception:
                pass

    # Fallback: offline index yang sudah ada
    idx = _kbbi_build_index()
    data = idx.get(key_norm)
    if not data:
        # heuristik saran sederhana: gabungkan saran dari simple, word-db, dan index offline
        try:
            prefix = key_norm[:2]
            combined = []
            if KBBI_SIMPLE_AVAILABLE:
                try:
                    s = get_saran(kata) or []
                    for x in s:
                        if x not in combined:
                            combined.append(x)
                except Exception:
                    pass
            # from word-db (original keys)
            try:
                for x in _kbbi_word_suggestions(prefix, limit=10) or []:
                    if x not in combined:
                        combined.append(x)
            except Exception:
                pass
            # from offline index keys (normalized keys)
            try:
                offline_keys = [k for k in idx.keys() if isinstance(k, str) and k.startswith(prefix)]
                for x in sorted(offline_keys)[:10]:
                    if x not in combined:
                        combined.append(x)
            except Exception:
                pass
            saran = combined[:10]
        except Exception:
            saran = []
        try:
            current_app.logger.info("kbbi_cek offline-miss kata=%r norm=%r; suggestions=%r", kata, key_norm, saran[:5] if isinstance(saran, list) else saran)
        except Exception:
            pass
        return jsonify({"valid": False, "error": "kata tidak ditemukan", "saran": saran}), 404

    payload = {
        "valid": True,
        "kata": kata,
        "lema": data.get("lema", []),
        "definisi": data.get("definisi", []),
        "entri": [],  # offline dataset tidak memiliki struktur makna lengkap
        "saran": [],
        "sumber": "kbbi-offline",
        "cache_hit": False,
    }
    _KBBI_CACHE[key_norm] = {"ts": now_ts, "payload": payload}
    try:
        current_app.logger.info("kbbi_cek offline-hit kata=%r", kata)
    except Exception:
        pass
    return jsonify(payload)


@kbbi_bp.post("/api/kbbi/reload")
def kbbi_reload():
    """
    Force reload KBBI offline index and clear online cache.
    """
    try:
        global _kbbi_index
        _kbbi_index = None
        _KBBI_CACHE.clear()
        idx = _kbbi_build_index()
        return jsonify({"reloaded": True, "index_size": len(idx)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kbbi_bp.get("/api/kbbi/stats")
def kbbi_stats():
    """
    Debug stats for KBBI index and files.
    Returns: { files, entries_loaded, index_size, word_db_size, has_pijar, pijar_lema, sample_keys_pi }
    """
    try:
        paths = sorted(glob.glob(KBBI_FILE_GLOB))
        entries = _kbbi_load_all_parts()
        idx = _kbbi_build_index()
        widx = _kbbi_build_word_index()
        key = _kbbi_normalize("pijar")
        sample_keys = [k for k in idx.keys() if isinstance(k, str) and k.startswith("pi")][:10]
        return jsonify({
            "files": len(paths),
            "entries_loaded": len(entries),
            "index_size": len(idx),
            "word_db_size": len(widx.get("raw") or {}),
            "has_pijar": key in idx,
            "pijar_lema": idx.get(key, {}).get("lema") if key in idx else [],
            "sample_keys_pi": sample_keys,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
