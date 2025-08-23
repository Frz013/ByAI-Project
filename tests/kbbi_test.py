import json
import urllib.request
import urllib.parse
import urllib.error
import os
import time

# Allow override via environment; default to Flask default port 5000
API = os.environ.get("API_BASE", "http://127.0.0.1:5000")

def http_get_json(url, timeout=60):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            code = resp.getcode()
            data = resp.read()
            return code, json.loads(data.decode("utf-8")), dict(resp.getheaders())
    except urllib.error.HTTPError as e:
        # Return the actual HTTP status code (e.g., 404, 429) and parse body if possible
        try:
            body = e.read()
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = {"error": str(e)}
        return e.code, data, dict(e.headers or {})
    except Exception as e:
        return None, {"error": str(e)}, {}

def test_valid_word():
    kata = "pijar"
    url = f"{API}/api/kbbi/cek?kata={urllib.parse.quote(kata)}"
    code, data, _ = http_get_json(url)
    print("valid_word status:", code)
    print("payload keys:", list(data.keys()) if isinstance(data, dict) else type(data))
    assert code == 200, f"Expected 200 for valid word, got {code}, data={data}"
    assert isinstance(data, dict)
    assert data.get("valid") is True
    assert data.get("kata")
    # entri (online) opsional; minimal pastikan ada definisi/lema
    assert isinstance(data.get("lema"), list)
    assert isinstance(data.get("definisi"), list)

def test_invalid_word_with_suggestions():
    kata = "xqzptlkxyz"  # mestinya tidak ada
    url = f"{API}/api/kbbi/cek?kata={urllib.parse.quote(kata)}"
    code, data, _ = http_get_json(url)
    print("invalid_word status:", code)
    print("invalid_word data:", data)
    # Bisa 404 (online/offline) -> saran mungkin ada atau kosong
    assert code == 404, f"Expected 404 for invalid word, got {code}, data={data}"
    assert isinstance(data, dict)
    assert data.get("valid") is False
    # saran boleh kosong, tapi per kontrak ada field-nya
    assert "saran" in data

def test_rate_limit_basic():
    # Kirim >60 permintaan dalam 60 detik untuk memicu 429 (rate limit per-IP)
    kata = "pijar"
    url = f"{API}/api/kbbi/cek?kata={urllib.parse.quote(kata)}"
    got_429 = False
    for i in range(0, 65):
        code, data, _ = http_get_json(url)
        if code == 429:
            got_429 = True
            print(f"rate limit hit at request {i+1}")
            break
        # jeda kecil agar tidak terlalu agresif; tetap bisa kena bucket 60/dtk
        time.sleep(0.01)
    assert got_429, "Expected to hit rate limit (429) but did not."

if __name__ == "__main__":
    # Manual run
    print("== HEALTH CHECK ==")
    hc = f"{API}/api/health"
    code, data, _ = http_get_json(hc)
    print("health:", code, data)

    print("\n== VALID WORD TEST ==")
    try:
        test_valid_word()
        print("valid test: OK")
    except AssertionError as e:
        print("valid test: FAIL:", e)

    print("\n== INVALID WORD TEST ==")
    try:
        test_invalid_word_with_suggestions()
        print("invalid test: OK")
    except AssertionError as e:
        print("invalid test: FAIL:", e)

    print("\n== RATE LIMIT TEST ==")
    try:
        test_rate_limit_basic()
        print("rate-limit test: OK")
    except AssertionError as e:
        print("rate-limit test: FAIL:", e)
