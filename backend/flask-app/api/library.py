import os
import json
import time
import random
import string
from flask import Blueprint, request, jsonify, send_file, after_this_request, current_app

library_bp = Blueprint("library", __name__)

# Paths
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DATA_DIR = os.path.join(APP_DIR, "data")
LIB_DB_JSON = os.path.join(LIB_DATA_DIR, "data.json")
LIB_DB_TXT = os.path.join(LIB_DATA_DIR, "data.txt")
DOWNLOADS_DIR = os.path.join(APP_DIR, "downloads")

os.makedirs(LIB_DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


# ---------------- Library (Book List Generator) ----------------
# Persistent data is stored as JSON (array of {pk, date_add, penulis, judul, tahun})
# Legacy fixed-width TXT format is still supported for import/migration and TXT export:
#  " {pk}, {date_add}, {penulis_fixed90}, {judul_fixed90}, {tahun}\n"
# Where:
#  - pk: 6 random ascii letters (A-Z, a-z)
#  - date_add: "%Y-%m-%d-%H:%M:%S%z" in UTC (gmtime)
#  - penulis/judul: right-padded to 90 chars (spaces)
#  - tahun: "YYYY"

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
        try:
            current_app.logger.warning("Failed reading JSON DB: %s", e)
        except Exception:
            pass

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
            try:
                current_app.logger.warning("Failed reading legacy TXT DB: %s", e)
            except Exception:
                pass
            return []
        # Migrate to JSON store
        try:
            _lib_write_all(recs)
        except Exception as e:
            try:
                current_app.logger.warning("Failed migrating TXT->JSON: %s", e)
            except Exception:
                pass
        return recs

    return []


def _lib_write_all(records):
    try:
        os.makedirs(LIB_DATA_DIR, exist_ok=True)
        with open(LIB_DB_JSON, "w", encoding="utf-8") as f:
            json.dump(records or [], f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f"Failed writing library DB: {e}")


@library_bp.get("/api/library/books")
def library_list_books():
    """
    Return all books as JSON array [{pk, date_add, penulis, judul, tahun}]
    """
    try:
        recs = _lib_read_all()
        return jsonify(recs)
    except Exception as e:
        try:
            current_app.logger.exception("library_list_books error: %s", e)
        except Exception:
            pass
        return jsonify({"error": "Gagal membaca data."}), 500


@library_bp.post("/api/library/books")
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
        try:
            current_app.logger.exception("library_add_book write error: %s", e)
        except Exception:
            pass
        return jsonify({"error": "Gagal menulis data."}), 500

    return jsonify({"pk": pk, "date_add": date_add, "penulis": penulis, "judul": judul, "tahun": tahun}), 201


@library_bp.put("/api/library/books/<pk>")
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
        try:
            current_app.logger.exception("library_update_book write error: %s", e)
        except Exception:
            pass
        return jsonify({"error": "Gagal menyimpan perubahan."}), 500

    updated = next(r for r in recs if r["pk"] == pk)
    return jsonify(updated)


@library_bp.delete("/api/library/books/<pk>")
def library_delete_book(pk):
    recs = _lib_read_all()
    new_recs = [r for r in recs if r["pk"] != pk]
    if len(new_recs) == len(recs):
        return jsonify({"error": "Data dengan pk tersebut tidak ditemukan."}), 404
    try:
        _lib_write_all(new_recs)
    except Exception as e:
        try:
            current_app.logger.exception("library_delete_book write error: %s", e)
        except Exception:
            pass
        return jsonify({"error": "Gagal menghapus data."}), 500
    return jsonify({"status": "deleted", "pk": pk})


@library_bp.get("/api/library/export")
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
        try:
            current_app.logger.exception("library_export error: %s", e)
        except Exception:
            pass
        return jsonify({"error": "Gagal menyiapkan unduhan."}), 500
