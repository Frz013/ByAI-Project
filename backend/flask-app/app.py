import os
import re
import shutil
import subprocess
import sys
import json
try:
    import ujson as _ujson
except Exception:
    _ujson = None
import glob
from datetime import datetime
from flask import Flask, request, jsonify, send_file, after_this_request
try:
    from flask_cors import CORS
except Exception:
    def CORS(app, *args, **kwargs):
        try:
            app.logger.warning("flask_cors not installed; proceeding without CORS")
        except Exception:
            pass
        return app
from pytube import YouTube
from urllib.parse import unquote, parse_qs

# Ensure the app directory is on sys.path so sibling modules (kbbi_simple.py) can be imported reliably
try:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
    if _APP_DIR not in sys.path:
        sys.path.insert(0, _APP_DIR)
except Exception:
    pass

# KBBI online library (optional) - disabled due to parsing issues
# Use simple fallback implementation instead
try:
    from kbbi_simple import cari_kata, get_saran
    KBBI_SIMPLE_AVAILABLE = True
except Exception as _kbbi_imp_err:
    KBBI_SIMPLE_AVAILABLE = False
    try:
        # app may not be initialized yet; best-effort stderr logging
        sys.stderr.write(f"kbbi_simple import failed: {_kbbi_imp_err}\n")
    except Exception:
        pass
    def cari_kata(kata):
        return None
    def get_saran(kata):
        return []

# KBBI online library (enabled with robust fallback)
try:
    from kbbi import KBBI as KBBIOnline, TidakDitemukan as KBBI_TidakDitemukan
    KBBI_ONLINE_AVAILABLE = True
except Exception as _kbbi_online_err:
    KBBI_ONLINE_AVAILABLE = False
    try:
        sys.stderr.write(f"kbbi online not available: {_kbbi_online_err}\n")
    except Exception:
        pass

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Library (Book List Generator) data path
LIB_DATA_DIR = os.path.join(BASE_DIR, "data")
LIB_DB_JSON = os.path.join(LIB_DATA_DIR, "data.json")
LIB_DB_TXT = os.path.join(LIB_DATA_DIR, "data.txt")
# Support multiple word DB shards: kbbi_word_data.json, kbbi_word_data1.json, ...
KBBI_WORD_DB_GLOB = os.path.join(LIB_DATA_DIR, "kbbi_word_data*.json")
# Backward-compatible default constant name
WORD_DB_JSON = os.path.join(LIB_DATA_DIR, "kbbi_word_data.json")
os.makedirs(LIB_DATA_DIR, exist_ok=True)


def sanitize_filename(name: str) -> str:
    """
    Remove characters not allowed in filenames on Windows/macOS/Linux.
    """
    name = re.sub(r'[\\/*?:"<>|]+', "_", name)
    # Collapse whitespace and strip
    return re.sub(r"\s+", " ", name).strip()[:180]  # keep it reasonably short


def human_size(num: int) -> str:
    try:
        num = int(num)
    except Exception:
        return ""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.0f} {unit}"
        num /= 1024.0
    return f"{num:.0f} PB"


def normalize_yt_url(url: str, raw_qs: str) -> str:
    """
    Return a canonical YouTube watch URL given possibly encoded/partial url + raw query string.
    """
    url = (url or "").strip()
    raw_qs = raw_qs or ""
    # Prefer candidate from raw_qs when present
    m = re.search(r"url=([^&]+)", raw_qs)
    if m:
        cand = unquote(m.group(1))
        cand = cand.replace("v%3D", "v=")
        if ("youtube.com" in cand or "youtu.be" in cand) and len(cand) >= len(url):
            url = cand

    # Extract video id
    vid = None
    m = re.search(r"(?:\?|&)v=([^&]+)", url)
    if m:
        vid = unquote(m.group(1))
    else:
        m = re.search(r"youtu\.be/([^?&/]+)", url)
        if m:
            vid = unquote(m.group(1))

    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    return url


# ---------- yt-dlp Fallback Helpers ----------
def _ytdlp_json(url: str) -> dict:
    """
    Run yt-dlp in JSON mode and return parsed metadata.
    Uses the current Python interpreter to avoid PATH issues on Windows.
    """
    cmd = [sys.executable, "-m", "yt_dlp", "-J", url]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as cpe:
        err_out = ((cpe.stderr or "") + "\n" + (cpe.stdout or "")).strip()
        err_out = err_out[:800]
        raise RuntimeError(f"yt-dlp failed to extract info: {err_out}")
    except Exception as ex:
        raise RuntimeError(f"yt-dlp invocation error: {ex}")
    try:
        return json.loads(proc.stdout or "{}")
    except Exception:
        raise RuntimeError("yt-dlp returned invalid JSON")


def _pick_best_thumbnail(info: dict) -> str:
    thumbs = info.get("thumbnails") or []
    if isinstance(thumbs, list) and thumbs:
        try:
            best = max(thumbs, key=lambda t: (t.get("height") or 0, t.get("width") or 0))
            return best.get("url") or ""
        except Exception:
            pass
    return info.get("thumbnail") or ""


def ytdlp_info(url: str) -> dict:
    """
    Build the same payload schema as pytube branch using yt-dlp metadata.
    Returns: {title, author, length, thumbnail_url, video: [...], audio: [...]}
    """
    info = _ytdlp_json(url)
    title = info.get("title") or ""
    author = info.get("channel") or info.get("uploader") or ""
    length = int(info.get("duration") or 0)
    thumbnail_url = _pick_best_thumbnail(info)
    fmts = info.get("formats") or []

    video = []
    audio = []

    for f in fmts:
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        ext = (f.get("ext") or "").lower()
        fid = str(f.get("format_id"))
        fs = f.get("filesize") or f.get("filesize_approx") or 0

        # Progressive MP4 (video+audio in one file)
        if vcodec and vcodec != "none" and acodec and acodec != "none" and ext == "mp4":
            height = f.get("height")
            res_text = f"{int(height)}p" if height else None
            fps = f.get("fps")
            video.append({
                "itag": int(fid) if fid.isdigit() else fid,
                "type": "video",
                "resolution": res_text,
                "fps": fps,
                "mime_type": "video/mp4",
                "filesize_approx": fs,
                "filesize_text": human_size(fs),
                "ext": "mp4",
            })

        # Video-only (no audio) — e.g., 1080p+; accept any container, will merge with bestaudio and output MP4
        if vcodec and vcodec != "none" and (not acodec or acodec == "none"):
            height = f.get("height")
            res_text = f"{int(height)}p" if height else None
            fps = f.get("fps")
            video.append({
                "itag": int(fid) if fid.isdigit() else fid,
                "type": "video",
                "resolution": res_text,
                "fps": fps,
                "mime_type": f"video/{ext}" if ext else "video",
                "filesize_approx": fs,
                "filesize_text": human_size(fs),
                "ext": ext,
                "video_only": True,
            })

        # Audio-only (prefer m4a)
        if (not vcodec or vcodec == "none") and acodec and acodec != "none" and ext == "m4a":
            abr = f.get("abr") or f.get("tbr")
            abr_text = None
            if isinstance(abr, (int, float)):
                abr_text = f"{int(abr)}k"
            elif abr:
                abr_text = str(abr)
            audio.append({
                "itag": int(fid) if fid.isdigit() else fid,
                "type": "audio",
                "abr": abr_text,
                "mime_type": "audio/mp4",
                "filesize_approx": fs,
                "filesize_text": human_size(fs),
                "ext": "m4a",
            })

    # Sort video by resolution (desc), fps (desc)
    def _res_num(v):
        r = v.get("resolution")
        try:
            return int(str(r).rstrip("p")) if r else 0
        except Exception:
            return 0
    video.sort(key=lambda s: (_res_num(s), s.get("fps") or 0), reverse=True)

    # Sort audio by abr (desc)
    def _abr_num(a):
        try:
            m = re.match(r"(\d+)", str(a.get("abr") or ""))
            return int(m.group(1)) if m else 0
        except Exception:
            return 0
    audio.sort(key=_abr_num, reverse=True)

    return {
        "title": title,
        "author": author,
        "length": length,
        "thumbnail_url": thumbnail_url,
        "video": video,
        "audio": audio,
    }


def ytdlp_download(url: str, format_id: str, dl_type: str):
    """
    Download using yt-dlp. For audio with ffmpeg present, convert to MP3.
    Returns a Flask Response with after_this_request cleanup.
    """
    info = _ytdlp_json(url)
    selected = None
    for f in info.get("formats") or []:
        if str(f.get("format_id")) == str(format_id):
            selected = f
            break

    title = sanitize_filename(info.get("title") or "youtube")
    suffix = ""
    if dl_type == "video":
        height = selected.get("height") if selected else None
        suffix = f" - {int(height)}p" if height else ""
        output_name = f"{title}{suffix}.mp4"
        out_path = os.path.join(DOWNLOADS_DIR, output_name)

        vcodec = selected.get("vcodec") if selected else None
        acodec = selected.get("acodec") if selected else None
        is_video_only = bool(vcodec and vcodec != "none" and (not acodec or acodec == "none"))

        if is_video_only:
            # Merge selected video-only with best audio; ffmpeg assumed installed
            cmd = [
                sys.executable, "-m", "yt_dlp",
                "-f", f"{format_id}+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
                "--merge-output-format", "mp4",
                "-o", out_path, url
            ]
        else:
            cmd = [sys.executable, "-m", "yt_dlp", "-f", str(format_id), "-o", out_path, url]

        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        @after_this_request
        def _cleanup_v(response):
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass
            return response

        resp = send_file(
            out_path,
            as_attachment=True,
            download_name=os.path.basename(out_path),
            mimetype="video/mp4",
            etag=True,
            conditional=True,
        )
        if is_video_only:
            resp.headers["X-Video-Merged"] = "true"
        return resp

    # Audio path
    abr = (selected.get("abr") or selected.get("tbr")) if selected else None
    if isinstance(abr, (int, float)):
        suffix = f" - {int(abr)}k"
    elif abr:
        suffix = f" - {abr}"

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        output_name = f"{title}{suffix}.mp3"
        out_path = os.path.join(DOWNLOADS_DIR, output_name)
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "-f", str(format_id),
            "-x", "--audio-format", "mp3", "--audio-quality", "192K",
            "-o", out_path, url
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        @after_this_request
        def _cleanup_mp3(response):
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass
            return response

        resp = send_file(
            out_path,
            as_attachment=True,
            download_name=os.path.basename(out_path),
            mimetype="audio/mpeg",
            etag=True,
            conditional=True,
        )
        resp.headers["X-Conversion"] = "mp3"
        return resp

    # Fallback to m4a if ffmpeg not available
    output_name = f"{title}{suffix}.m4a"
    out_path = os.path.join(DOWNLOADS_DIR, output_name)
    cmd = [sys.executable, "-m", "yt_dlp", "-f", str(format_id), "-o", out_path, url]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @after_this_request
    def _cleanup_m4a(response):
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        return response

    resp = send_file(
        out_path,
        as_attachment=True,
        download_name=os.path.basename(out_path),
        mimetype="audio/mp4",
        etag=True,
        conditional=True,
    )
    resp.headers["X-Conversion"] = "m4a-fallback"
    return resp


# ---------------- Library (Book List Generator) ----------------
# Persistent data is now stored as JSON (array of {pk, date_add, penulis, judul, tahun})
# Legacy fixed-width TXT format is still supported for import/migration and TXT export:
#  " {pk}, {date_add}, {penulis_fixed90}, {judul_fixed90}, {tahun}\n"
# Where:
#  - pk: 6 random ascii letters (A-Z, a-z)
#  - date_add: "%Y-%m-%d-%H:%M:%S%z" in UTC (gmtime)
#  - penulis/judul: right-padded to 90 chars (spaces)
#  - tahun: "YYYY"
import time, random, string

def _lib_rand_pk(n: int = 6) -> str:
    return "".join(random.choice(string.ascii_letters) for _ in range(n))

def _lib_now_str() -> str:
    return time.strftime("%Y-%m-%d-%H:%M:%S%z", time.gmtime())

def _lib_pad_fixed(s: str, width: int = 90) -> str:
    s = (s or "")
    if len(s) > width:
        s = s[:width]
    return s + (" " * (width - len(s)))

def _lib_format_line(pk: str, date_add: str, penulis: str, judul: str, tahun: str) -> str:
    return f" {pk}, {date_add}, {_lib_pad_fixed(penulis)}, {_lib_pad_fixed(judul)}, {tahun}\n"

def _lib_parse_line(line: str):
    if not line:
        return None
    raw = line.rstrip("\n")
    if not raw.strip():
        return None
    if raw.startswith(" "):
        raw = raw[1:]
    parts = raw.split(", ")
    if len(parts) != 5:
        return None
    pk, date_add, penulis, judul, tahun = parts
    return {
        "pk": pk.strip(),
        "date_add": date_add.strip(),
        "penulis": (penulis or "").rstrip(),
        "judul": (judul or "").rstrip(),
        "tahun": (tahun or "").strip(),
    }

def _lib_read_all():
    # JSON-first; migrate from legacy TXT if needed
    try:
        if os.path.exists(LIB_DB_JSON):
            with open(LIB_DB_JSON, "r", encoding="utf-8") as f:
                data = json.load(f) or []
            # Ensure list of dicts with expected keys
            out = []
            for r in data if isinstance(data, list) else []:
                if isinstance(r, dict):
                    out.append({
                        "pk": str(r.get("pk", "")).strip(),
                        "date_add": str(r.get("date_add", "")).strip(),
                        "penulis": str(r.get("penulis", "")).rstrip(),
                        "judul": str(r.get("judul", "")).rstrip(),
                        "tahun": str(r.get("tahun", "")).strip(),
                    })
            return out
    except Exception as e:
        app.logger.warning("Failed reading JSON DB: %s", e)

    # Fallback: import from legacy TXT on first run
    if os.path.exists(LIB_DB_TXT):
        recs = []
        try:
            with open(LIB_DB_TXT, "r", encoding="utf-8") as f:
                for ln in f:
                    rec = _lib_parse_line(ln)
                    if rec:
                        recs.append(rec)
        except Exception as e:
            app.logger.warning("Failed reading legacy TXT DB: %s", e)
            return []
        # Migrate to JSON store
        try:
            _lib_write_all(recs)
        except Exception as e:
            app.logger.warning("Failed migrating TXT->JSON: %s", e)
        return recs

    return []

def _lib_write_all(records):
    try:
        os.makedirs(LIB_DATA_DIR, exist_ok=True)
        with open(LIB_DB_JSON, "w", encoding="utf-8") as f:
            json.dump(records or [], f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f"Failed writing library DB: {e}")

@app.get("/api/library/books")
def library_list_books():
    """
    Return all books as JSON array [{pk, date_add, penulis, judul, tahun}]
    """
    try:
        recs = _lib_read_all()
        return jsonify(recs)
    except Exception as e:
        app.logger.exception("library_list_books error: %s", e)
        return jsonify({"error": "Gagal membaca data."}), 500

@app.post("/api/library/books")
def library_add_book():
    """
    Body JSON: { penulis: str, judul: str, tahun: "YYYY" }
    """
    payload = request.get_json(silent=True) or {}
    penulis = (payload.get("penulis") or "").strip()
    judul = (payload.get("judul") or "").strip()
    tahun = (payload.get("tahun") or "").strip()

    if not penulis or not judul or not tahun:
        return jsonify({"error": "Field penulis, judul, tahun wajib diisi."}), 400
    if not (len(tahun) == 4 and tahun.isdigit()):
        return jsonify({"error": "Tahun harus 4 digit (YYYY)."}), 400

    # ensure unique pk
    recs = _lib_read_all()
    existing = {r["pk"] for r in recs}
    pk = _lib_rand_pk(6)
    attempts = 0
    while pk in existing and attempts < 10_000:
        pk = _lib_rand_pk(6)
        attempts += 1
    date_add = _lib_now_str()

    # append to JSON database
    try:
        recs.append({"pk": pk, "date_add": date_add, "penulis": penulis, "judul": judul, "tahun": tahun})
        _lib_write_all(recs)
    except Exception as e:
        app.logger.exception("library_add_book write error: %s", e)
        return jsonify({"error": "Gagal menulis data."}), 500

    return jsonify({"pk": pk, "date_add": date_add, "penulis": penulis, "judul": judul, "tahun": tahun}), 201

@app.put("/api/library/books/<pk>")
def library_update_book(pk):
    """
    Body JSON: any of { penulis, judul, tahun }
    Keep date_add as-is.
    """
    payload = request.get_json(silent=True) or {}
    penulis = payload.get("penulis", None)
    judul = payload.get("judul", None)
    tahun = payload.get("tahun", None)

    if penulis is None and judul is None and tahun is None:
        return jsonify({"error": "Tidak ada field untuk diupdate."}), 400
    if tahun is not None:
        tahun = str(tahun).strip()
        if not (len(tahun) == 4 and tahun.isdigit()):
            return jsonify({"error": "Tahun harus 4 digit (YYYY)."}), 400

    recs = _lib_read_all()
    found = False
    for r in recs:
        if r["pk"] == pk:
            if penulis is not None:
                r["penulis"] = str(penulis).strip()
            if judul is not None:
                r["judul"] = str(judul).strip()
            if tahun is not None:
                r["tahun"] = tahun
            found = True
            break
    if not found:
        return jsonify({"error": "Data dengan pk tersebut tidak ditemukan."}), 404

    try:
        _lib_write_all(recs)
    except Exception as e:
        app.logger.exception("library_update_book write error: %s", e)
        return jsonify({"error": "Gagal menyimpan perubahan."}), 500

    updated = next(r for r in recs if r["pk"] == pk)
    return jsonify(updated)

@app.delete("/api/library/books/<pk>")
def library_delete_book(pk):
    recs = _lib_read_all()
    new_recs = [r for r in recs if r["pk"] != pk]
    if len(new_recs) == len(recs):
        return jsonify({"error": "Data dengan pk tersebut tidak ditemukan."}), 404
    try:
        _lib_write_all(new_recs)
    except Exception as e:
        app.logger.exception("library_delete_book write error: %s", e)
        return jsonify({"error": "Gagal menghapus data."}), 500
    return jsonify({"status": "deleted", "pk": pk})

@app.get("/api/library/export")
def library_export():
    """
    ?format=json|txt
    Download as attachment:
      - book-list.json (application/json)
      - book-list.txt (text/plain) with original fixed-width format.
    """
    fmt = (request.args.get("format") or "").strip().lower()
    if fmt not in {"json", "txt"}:
        return jsonify({"error": "format harus json atau txt"}), 400

    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        if fmt == "json":
            data = _lib_read_all()
            out_path = os.path.join(DOWNLOADS_DIR, "book-list.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            @after_this_request
            def _cleanup_json(resp):
                try:
                    if os.path.exists(out_path):
                        os.remove(out_path)
                except Exception:
                    pass
                return resp
            return send_file(
                out_path,
                as_attachment=True,
                download_name="book-list.json",
                mimetype="application/json",
                etag=True,
                conditional=True,
            )
        else:
            # txt: generate from current records using legacy fixed-width format
            out_path = os.path.join(DOWNLOADS_DIR, "book-list.txt")
            recs = _lib_read_all()
            with open(out_path, "w", encoding="utf-8") as dst:
                for r in recs:
                    dst.write(_lib_format_line(r["pk"], r["date_add"], r["penulis"], r["judul"], r["tahun"]))
            @after_this_request
            def _cleanup_txt(resp):
                try:
                    if os.path.exists(out_path):
                        os.remove(out_path)
                except Exception:
                    pass
                return resp
            return send_file(
                out_path,
                as_attachment=True,
                download_name="book-list.txt",
                mimetype="text/plain",
                etag=True,
                conditional=True,
            )
    except Exception as e:
        app.logger.exception("library_export error: %s", e)
        return jsonify({"error": "Gagal menyiapkan unduhan."}), 500

# ---------------- KBBI Checker ----------------
# Loads and indexes offline KBBI JSON parts on first use, cached in-memory.
KBBI_FILE_GLOB = os.path.join(LIB_DATA_DIR, "kbbi_v_part*.json")
_kbbi_index = None

# Online cache and rate limiting for KBBI
_KBBI_CACHE = {}  # key_norm -> {ts: epoch, payload: dict}
_KBBI_CACHE_TTL = 6 * 3600  # 6 jam
_RATE_BUCKET = {}  # ip -> [timestamps]
_RATE_LIMIT_MAX = 60
_RATE_LIMIT_WINDOW = 60  # 60 dtk

# ---------- KBBI Word DB (kbbi_word_data.json) ----------
_KBBI_WORD_INDEX = None  # cached indices: {"by_key":{}, "by_lema":{}, "orig_key":{}, "raw":{}}

def _kbbi_load_word_db_raw():
    """
    Load raw word database JSON shards as a combined dict.
    Supports multiple files matching KBBI_WORD_DB_GLOB (e.g., kbbi_word_data.json, kbbi_word_data1.json, ...).
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
                    app.logger.warning("Failed loading word DB shard %s: %s", p, e)
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
                app.logger.warning("KBBI load failed for %s: %s", p, e)
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

@app.get("/api/kbbi/cek")
def kbbi_cek():
    """
    Query: ?kata=...
    Returns (online-first with offline fallback):
      200: {
        valid: true, kata, lema: ["..."], definisi: ["..."],
        entri: [{lema, makna:[{kelas, deskripsi, contoh:[], sinonim:[], antonim:[]}]}],
        saran: [], sumber: "kbbi-online"|"kbbi-offline", cache_hit: bool
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
        app.logger.info("kbbi_cek query kata=%r norm=%r simple=%r", kata, key_norm, KBBI_SIMPLE_AVAILABLE)
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
                app.logger.info("kbbi_cek online-hit kata=%r", kata)
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
                app.logger.warning("KBBI online lookup error for %r: %r", kata, ex_online)
            except Exception:
                pass
            # fall through to simple/offline

    # Try Word DB (kbbi_word_data.json) third
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
                app.logger.info("kbbi_cek worddb-hit kata=%r", kata)
            except Exception:
                pass
            return jsonify(payload)
    except Exception as ex_worddb:
        try:
            app.logger.warning("KBBI worddb lookup error for %r: %r", kata, ex_worddb)
        except Exception:
            pass

    # Try simple KBBI implementation second
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
                    app.logger.info("kbbi_cek simple-hit kata=%r", kata)
                except Exception:
                    pass
                return jsonify(payload)
        except Exception as ex:
            app.logger.warning(f"KBBI simple lookup failed for '{kata}': {ex}")

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
            app.logger.info("kbbi_cek offline-miss kata=%r norm=%r; suggestions=%r", kata, key_norm, saran[:5] if isinstance(saran, list) else saran)
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
        app.logger.info("kbbi_cek offline-hit kata=%r", kata)
    except Exception:
        pass
    return jsonify(payload)

@app.post("/api/kbbi/reload")
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

@app.get("/api/kbbi/stats")
def kbbi_stats():
    """
    Debug stats for KBBI index and files.
    Returns: { files, entries_loaded, index_size, has_pijar, pijar_lema, sample_keys_pi }
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

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


@app.get("/api/ytdl/info")
def ytdl_info():
    """
    Query: ?url=YOUTUBE_URL
    Returns:
      {
        title, author, length, thumbnail_url,
        video: [...progressive mp4...],
        audio: [...audio/mp4...]
      }
    """
    raw_qs = request.query_string.decode("utf-8", "ignore")
    url_in = request.args.get("url", "").strip()
    url = normalize_yt_url(url_in, raw_qs)
    app.logger.info(f"/api/ytdl/info url_in={url_in!r} normalized={url!r}")

    if not url:
        return jsonify({"error": "Missing url"}), 400

    try:
        yt = YouTube(url)
        # Progressive mp4 streams (video+audio)
        video_streams = (
            yt.streams.filter(progressive=True, file_extension="mp4")
            .order_by("resolution")
            .desc()
        )
        # Audio-only (prefer audio/mp4)
        audio_streams = (
            yt.streams.filter(only_audio=True, mime_type="audio/mp4")
            .order_by("abr")
            .desc()
        )

        def video_payload(s):
            return {
                "itag": s.itag,
                "type": "video",
                "resolution": getattr(s, "resolution", None),
                "fps": getattr(s, "fps", None),
                "mime_type": s.mime_type,
                "filesize_approx": getattr(s, "filesize_approx", None),
                "filesize_text": human_size(getattr(s, "filesize_approx", 0)),
                "ext": "mp4",
            }

        def audio_payload(s):
            return {
                "itag": s.itag,
                "type": "audio",
                "abr": getattr(s, "abr", None),
                "mime_type": s.mime_type,
                "filesize_approx": getattr(s, "filesize_approx", None),
                "filesize_text": human_size(getattr(s, "filesize_approx", 0)),
                "ext": "m4a",  # pytube audio/mp4 is typically .m4a
            }

        data = {
            "title": yt.title,
            "author": yt.author,
            "length": yt.length,
            "thumbnail_url": yt.thumbnail_url,
            "video": [video_payload(s) for s in video_streams],
            "audio": [audio_payload(s) for s in audio_streams],
        }
        # Augment with yt-dlp formats to expose higher resolutions (e.g., 1080p video-only) if available
        try:
            ydl = ytdlp_info(url)
            # Merge video (avoid duplicates by itag)
            v_itags = {str(v.get("itag")) for v in data.get("video", [])}
            for v in (ydl.get("video") or []):
                if str(v.get("itag")) not in v_itags:
                    data["video"].append(v)
                    v_itags.add(str(v.get("itag")))
            # Merge audio (avoid duplicates by itag)
            a_itags = {str(a.get("itag")) for a in data.get("audio", [])}
            for a in (ydl.get("audio") or []):
                if str(a.get("itag")) not in a_itags:
                    data["audio"].append(a)
                    a_itags.add(str(a.get("itag")))

            # Re-sort video by resolution desc, fps desc
            def _res_num(v):
                try:
                    r = v.get("resolution")
                    return int(str(r).rstrip("p")) if r else 0
                except Exception:
                    return 0
            data["video"].sort(key=lambda s: (_res_num(s), s.get("fps") or 0), reverse=True)

            # Re-sort audio by abr desc
            def _abr_num(a):
                try:
                    m = re.match(r"(\d+)", str(a.get("abr") or ""))
                    return int(m.group(1)) if m else 0
                except Exception:
                    return 0
            data["audio"].sort(key=_abr_num, reverse=True)
        except Exception:
            pass

        return jsonify(data)
    except Exception as e:
        # Try yt-dlp fallback for robustness
        app.logger.warning("pytube info failed, trying yt-dlp: %s", e)
        try:
            data = ytdlp_info(url)
            return jsonify(data)
        except Exception as e2:
            app.logger.exception("ytdl_info failed for url=%r due to %r", url, e2)
            return jsonify({"error": f"Tidak dapat mengambil info dari URL yang diberikan. Detail: {str(e2)}"}), 400


@app.post("/api/ytdl/download")
def ytdl_download():
    """
    Body (JSON): { "url": "...", "itag": 123, "type": "video" | "audio" }
    Behavior:
      - For "video": download progressive mp4 and send as attachment .mp4
      - For "audio": download audio/mp4 (.m4a), try convert to .mp3 using ffmpeg.
                     If ffmpeg missing, fall back to .m4a with X-Conversion: m4a-fallback
    """
    payload = request.get_json(silent=True) or {}
    app.logger.info("ytdl_download raw_body=%r content_type=%r parsed=%r", request.data[:200], request.content_type, payload)
    url = (payload.get("url") or "").strip()
    itag = payload.get("itag")
    dl_type = (payload.get("type") or "").strip().lower()

    if not url or not itag or dl_type not in {"video", "audio"}:
        return jsonify({"error": "Missing required fields: url, itag, type"}), 400

    try:
        yt = YouTube(url)
        itag_str = str(itag)
        stream = None
        if itag_str.isdigit():
            stream = yt.streams.get_by_itag(int(itag_str))
        else:
            # non-numeric itag -> force yt-dlp fallback path
            raise Exception("non-numeric itag")
        if stream is None:
            app.logger.info("itag %r not found in pytube; falling back to yt-dlp", itag_str)
            return ytdlp_download(url, str(itag), dl_type)

        title = sanitize_filename(yt.title or "youtube")
        # Compose descriptive suffix
        suffix = ""
        if dl_type == "video":
            res = getattr(stream, "resolution", "")
            suffix = f" - {res}".strip() if res else ""
            filename = f"{title}{suffix}.mp4"
            out_path = os.path.join(DOWNLOADS_DIR, filename)
            tmp_path = stream.download(output_path=DOWNLOADS_DIR, filename=filename)

            @after_this_request
            def cleanup_video(response):
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
                return response

            return send_file(
                out_path,
                as_attachment=True,
                download_name=os.path.basename(out_path),
                mimetype="video/mp4",
                etag=True,
                conditional=True,
            )

        # audio flow
        abr = getattr(stream, "abr", "")
        suffix = f" - {abr}".strip() if abr else ""
        # pytube audio/mp4 is .m4a
        input_name = f"{title}{suffix}.m4a"
        input_path = os.path.join(DOWNLOADS_DIR, input_name)
        tmp_path = stream.download(output_path=DOWNLOADS_DIR, filename=input_name)

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            # Convert to MP3 with ffmpeg
            output_name = f"{title}{suffix}.mp3"
            output_path = os.path.join(DOWNLOADS_DIR, output_name)
            cmd = [
                ffmpeg_path,
                "-y",
                "-i",
                input_path,
                "-vn",
                "-acodec",
                "libmp3lame",
                "-b:a",
                "192k",
                output_path,
            ]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                # Remove source .m4a after successful conversion
                try:
                    os.remove(input_path)
                except Exception:
                    pass

                @after_this_request
                def cleanup_mp3(response):
                    try:
                        if os.path.exists(output_path):
                            os.remove(output_path)
                    except Exception:
                        pass
                    return response

                resp = send_file(
                    output_path,
                    as_attachment=True,
                    download_name=os.path.basename(output_path),
                    mimetype="audio/mpeg",
                    etag=True,
                    conditional=True,
                )
                resp.headers["X-Conversion"] = "mp3"
                return resp
            except Exception as conv_err:
                # Fallback to original m4a on conversion error
                pass

        # Fallback: serve .m4a (no ffmpeg or conversion failed)
        @after_this_request
        def cleanup_m4a(response):
            try:
                if os.path.exists(input_path):
                    os.remove(input_path)
            except Exception:
                pass
            return response

        resp = send_file(
            input_path,
            as_attachment=True,
            download_name=os.path.basename(input_path),
            mimetype="audio/mp4",
            etag=True,
            conditional=True,
        )
        resp.headers["X-Conversion"] = "m4a-fallback"
        return resp

    except Exception as e:
        # Fallback to yt-dlp for download
        app.logger.warning("pytube download failed, trying yt-dlp: %s", e)
        try:
            return ytdlp_download(url, str(itag), dl_type)
        except Exception as e2:
            app.logger.exception("ytdl_download failed for url=%r itag=%r type=%r due to %r", url, itag, dl_type, e2)
            return jsonify({"error": f"Gagal mengunduh media. Detail: {str(e2)}"}), 400


if __name__ == "__main__":
    # Default to port 5000 as agreed
    app.run(host="0.0.0.0", port=5000, debug=True)
