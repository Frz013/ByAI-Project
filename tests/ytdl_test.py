import json
import urllib.request
import urllib.parse
import sys
import time

API = "http://127.0.0.1:5001"

def http_get_json(url, timeout=120):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            code = resp.getcode()
            data = resp.read()
            return code, json.loads(data.decode("utf-8")), dict(resp.getheaders())
    except Exception as e:
        return None, {"error": str(e)}, {}

def http_post_json_headers(url, payload, timeout=600):
    """
    Perform a POST but only request 1 byte using Range to avoid downloading the full media.
    Returns (status_code, headers_dict) or (None, {"error": ...}).
    """
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Range": "bytes=0-0",  # fetch minimal content to only get headers
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            headers = dict(resp.getheaders())
            return code, headers
    except Exception as e:
        return None, {"error": str(e)}

def pick_by_res(info, wanted=("1080p","720p","360p")):
    out = {}
    for res in wanted:
        cand = None
        for v in info.get("video", []) or []:
            if str(v.get("resolution") or "") == res:
                # prefer progressive (no video_only flag) over video_only
                if cand is None:
                    cand = v
                else:
                    cur_vo = bool(cand.get("video_only"))
                    v_vo = bool(v.get("video_only"))
                    if cur_vo and not v_vo:
                        cand = v
        if cand:
            out[res] = cand
    return out

def run():
    print("== HEALTH CHECK ==")
    code, data, _ = http_get_json(f"{API}/api/health")
    print("health:", code, data)

    print("\n== INFO URL FORMS ==")
    vid = "j9Kg_rQ2rYA"
    url_watch = f"https://www.youtube.com/watch?v={vid}"
    url_short = f"https://youtu.be/{vid}"
    url_encoded = urllib.parse.quote(url_watch, safe="")

    forms = [
        ("watch?v=", url_watch),
        ("youtu.be", url_short),
        ("encoded v%3D", url_encoded),
    ]
    info_any = None
    for label, u in forms:
        info_url = f"{API}/api/ytdl/info?url={u}"
        code, info, _ = http_get_json(info_url)
        have = []
        if code == 200 and isinstance(info, dict):
            selected = pick_by_res(info)
            for r in ("1080p","720p","360p"):
                if r in selected:
                    itag = selected[r].get("itag")
                    vo = bool(selected[r].get("video_only"))
                    have.append(f"{r}(itag={itag},video_only={vo})")
            if not info_any:
                info_any = info
        print(f"[{label}] code={code} found={', '.join(have) if have else 'none'}")

    if not info_any:
        print("No info available; aborting download tests.")
        return

    # Try video download: prefer 1080p, then 720p, then 360p
    want_order = ["1080p","720p","360p"]
    selected_map = pick_by_res(info_any)
    chosen = None
    for r in want_order:
        if r in selected_map:
            chosen = (r, selected_map[r])
            break

    print("\n== DOWNLOAD TESTS ==")
    if chosen:
        res, stream = chosen
        itag = stream.get("itag")
        print(f"Video: requesting {res} itag={itag}")
        vcode, vheaders = http_post_json_headers(f"{API}/api/ytdl/download", {
            "url": url_watch,
            "itag": itag,
            "type": "video"
        })
        print("video status:", vcode)
        if isinstance(vheaders, dict):
            for k in ("Content-Type","Content-Disposition","X-Video-Merged","Content-Length"):
                if k in vheaders:
                    print(f"  {k}: {vheaders[k]}")
    else:
        print("No desired video resolution available to test.")

    # Audio download (prefer first audio entry)
    aud = None
    if isinstance(info_any.get("audio"), list) and info_any["audio"]:
        aud = info_any["audio"][0]
    if aud:
        itag_a = aud.get("itag")
        abr = aud.get("abr")
        print(f"Audio: requesting itag={itag_a} abr={abr}")
        acode, aheaders = http_post_json_headers(f"{API}/api/ytdl/download", {
            "url": url_watch,
            "itag": itag_a,
            "type": "audio"
        })
        print("audio status:", acode)
        if isinstance(aheaders, dict):
            for k in ("Content-Type","Content-Disposition","X-Conversion","Content-Length"):
                if k in aheaders:
                    print(f"  {k}: {aheaders[k]}")
    else:
        print("No audio stream found to test.")

if __name__ == "__main__":
    run()
