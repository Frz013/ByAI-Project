import os
import re
import shutil
import subprocess
import sys
import json
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

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Library (Book List Generator) data path
LIB_DATA_DIR = os.path.join(BASE_DIR, "data")
LIB_DB_JSON = os.path.join(LIB_DATA_DIR, "data.json")
LIB_DB_TXT = os.path.join(LIB_DATA_DIR, "data.txt")
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
