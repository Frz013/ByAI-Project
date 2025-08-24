import re
from urllib.parse import unquote


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
