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

    #
