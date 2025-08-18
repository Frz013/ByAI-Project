// features/ytdl.js
// Frontend logic for YouTube Downloader page (works with Flask backend at http://localhost:5000)

(() => {
  // Allow overriding API endpoint via query param ?api=http://localhost:5001
  try {
    const usp = new URLSearchParams(window.location.search);
    const apiOverride = usp.get("api");
    if (apiOverride) {
      localStorage.setItem("YTDL_API_BASE", apiOverride);
    }
  } catch (e) {}
  const API_BASE = localStorage.getItem("YTDL_API_BASE") || "http://localhost:5000";

  // State
  let currentInfo = null; // holds last fetched info JSON
  let currentType = "video"; // "video" | "audio"

  // Elements
  const els = {
    url: document.getElementById("ytUrl"),
    fetchInfo: document.getElementById("fetchInfoBtn"),
    download: document.getElementById("downloadBtn"),
    status: document.getElementById("statusMsg"),

    infoGrid: document.getElementById("infoGrid"),
    thumb: document.getElementById("thumb"),
    title: document.getElementById("videoTitle"),
    author: document.getElementById("videoAuthor"),
    length: document.getElementById("videoLength"),

    typeVideoBtn: document.getElementById("typeVideoBtn"),
    typeAudioBtn: document.getElementById("typeAudioBtn"),

    videoQuality: document.getElementById("videoQuality"),
    audioQuality: document.getElementById("audioQuality"),
  };

  function setStatus(text, type = "info") {
    if (!els.status) return;
    els.status.textContent = text || "";
    els.status.style.color = type === "error" ? "#ef4444" : "var(--muted)";
  }

  function secondsToHMS(sec) {
    try {
      let s = Number(sec) || 0;
      const h = Math.floor(s / 3600);
      s %= 3600;
      const m = Math.floor(s / 60);
      s = Math.floor(s % 60);
      return [h, m, s]
        .map((v, i) => (i === 0 ? String(v) : String(v).padStart(2, "0")))
        .filter((v, i) => (i === 0 ? v !== "0" : true))
        .join(":");
    } catch {
      return "";
    }
  }

  function toggleType(type) {
    currentType = type;
    // toggle button styles
    if (type === "video") {
      els.typeVideoBtn.classList.remove("secondary");
      els.typeVideoBtn.setAttribute("aria-pressed", "true");
      els.typeAudioBtn.classList.add("secondary");
      els.typeAudioBtn.setAttribute("aria-pressed", "false");
      // enable/disable selects
      els.videoQuality.disabled = false;
      els.audioQuality.disabled = true;
    } else {
      els.typeAudioBtn.classList.remove("secondary");
      els.typeAudioBtn.setAttribute("aria-pressed", "true");
      els.typeVideoBtn.classList.add("secondary");
      els.typeVideoBtn.setAttribute("aria-pressed", "false");
      els.videoQuality.disabled = true;
      els.audioQuality.disabled = false;
    }
  }

  function clearSelect(sel) {
    if (!sel) return;
    sel.innerHTML = "";
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = sel === els.videoQuality ? "— pilih kualitas video —" : "— pilih kualitas audio —";
    sel.appendChild(opt);
  }

  function fillInfo(data) {
    currentInfo = data;
    // Show basic info
    els.infoGrid.style.display = "grid";
    els.thumb.src = data.thumbnail_url || "";
    els.title.value = data.title || "";
    els.author.value = data.author || "";
    els.length.value = secondsToHMS(data.length);

    // Fill video qualities (limit to 1080p, 720p, 360p; prefer progressive over video-only)
    clearSelect(els.videoQuality);
    const wantedOrder = ["1080p", "720p", "360p"];
    const byRes = {};
    (data.video || []).forEach((s) => {
      const res = s.resolution ? String(s.resolution) : "";
      if (!wantedOrder.includes(res)) return;
      const key = res;
      const cur = byRes[key];
      if (!cur) {
        byRes[key] = s;
      } else {
        const curIsVO = !!cur.video_only;
        const sIsVO = !!s.video_only;
        // Prefer progressive (has audio) over video-only for the same resolution
        if (curIsVO && !sIsVO) byRes[key] = s;
      }
    });
    const picked = wantedOrder.map((r) => byRes[r]).filter(Boolean);
    picked.forEach((s, i) => {
      const opt = document.createElement("option");
      const parts = [];
      if (s.resolution) parts.push(s.resolution);
      if (s.fps) parts.push(`${s.fps}fps`);
      if (s.filesize_text) parts.push(s.filesize_text);
      if (s.video_only) parts.push("merged"); // will be merged with best audio on backend
      opt.textContent = `${parts.join(" • ")} (itag ${s.itag})`;
      opt.value = s.itag;
      if (i === 0) opt.selected = true;
      els.videoQuality.appendChild(opt);
    });

    // Fill audio qualities
    clearSelect(els.audioQuality);
    (data.audio || []).forEach((s, i) => {
      const opt = document.createElement("option");
      const parts = [];
      if (s.abr) parts.push(s.abr);
      if (s.filesize_text) parts.push(s.filesize_text);
      opt.textContent = `${parts.join(" • ")} (itag ${s.itag})`;
      opt.value = s.itag;
      if (i === 0) opt.selected = true;
      els.audioQuality.appendChild(opt);
    });

    // Enable related controls
    els.download.disabled = false;
    // Default type to video if available, else audio
    if ((data.video || []).length > 0) {
      toggleType("video");
    } else {
      toggleType("audio");
    }
  }

  function parseContentDispositionFilename(headerVal) {
    if (!headerVal) return null;
    // Example: attachment; filename="MyVideo - 720p.mp4"
    const m = /filename\*=UTF-8''([^;]+)|filename="?([^\";]+)"?/i.exec(headerVal);
    if (m) {
      const fn = decodeURIComponent(m[1] || m[2] || "");
      return fn || null;
    }
    return null;
  }

  async function fetchInfo() {
    const url = (els.url.value || "").trim();
    if (!url) {
      setStatus("Masukkan URL video YouTube terlebih dahulu.", "error");
      return;
    }
    setStatus("Mengambil info video…");
    els.download.disabled = true;
    try {
      const res = await fetch(`${API_BASE}/api/ytdl/info?url=${encodeURIComponent(url)}`);
      if (!res.ok) {
        let err = "Gagal mengambil info.";
        try {
          const j = await res.json();
          if (j && j.error) err = j.error;
        } catch (_) {}
        setStatus(err, "error");
        return;
      }
      const data = await res.json();
      fillInfo(data);
      setStatus("Info berhasil diambil.");
    } catch (e) {
      console.error(e);
      setStatus("Terjadi kesalahan jaringan saat mengambil info.", "error");
    }
  }

  async function doDownload() {
    if (!currentInfo) {
      setStatus("Ambil info video terlebih dahulu.", "error");
      return;
    }
    const url = (els.url.value || "").trim();
    if (!url) {
      setStatus("URL tidak boleh kosong.", "error");
      return;
    }

    const itag =
      currentType === "video" ? els.videoQuality.value : els.audioQuality.value;
    if (!itag) {
      setStatus("Pilih kualitas sesuai tipe unduhan.", "error");
      return;
    }

    setStatus("Menyiapkan unduhan…");

    try {
      const res = await fetch(`${API_BASE}/api/ytdl/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, itag, type: currentType }),
      });

      if (!res.ok) {
        let err = `Gagal mengunduh (HTTP ${res.status}).`;
        try {
          const j = await res.json();
          if (j && j.error) err = j.error;
        } catch (_) {}
        setStatus(err, "error");
        return;
      }

      // Determine filename
      let filename =
        parseContentDispositionFilename(res.headers.get("Content-Disposition")) ||
        "";

      // Fallback filename construction
      if (!filename) {
        const title = (currentInfo.title || "youtube").replace(/[\\/*?:"<>|]+/g, "_").slice(0, 180);
        if (currentType === "video") {
          const sel = els.videoQuality.options[els.videoQuality.selectedIndex];
          const label = sel ? sel.textContent : "";
          const reso = (label.match(/^\s*([^•]+)\s*•/) || [,""])[1].trim();
          filename = `${title}${reso ? " - " + reso : ""}.mp4`;
        } else {
          const conv = (res.headers.get("X-Conversion") || "").toLowerCase();
          const sel = els.audioQuality.options[els.audioQuality.selectedIndex];
          const label = sel ? sel.textContent : "";
          const abr = (label.match(/^\s*([^•]+)\s*•/) || [,""])[1].trim();
          const ext = conv === "mp3" ? "mp3" : "m4a";
          filename = `${title}${abr ? " - " + abr : ""}.${ext}`;
        }
      }

      const convHeader = (res.headers.get("X-Conversion") || "").toLowerCase();
      const mergedHeader = (res.headers.get("X-Video-Merged") || "").toLowerCase() === "true";
      if (currentType === "audio" && convHeader === "m4a-fallback") {
        setStatus("ffmpeg belum tersedia → mengirim M4A (fallback).", "info");
      } else if (currentType === "video" && mergedHeader) {
        setStatus("Menggabungkan video dan audio (video-only) → MP4.", "info");
      } else {
        setStatus("Mengunduh…");
      }

      const blob = await res.blob();
      const urlBlob = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = urlBlob;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(urlBlob), 1500);

      setStatus("Unduhan dimulai.");
    } catch (e) {
      console.error(e);
      setStatus("Terjadi kesalahan saat mengunduh.", "error");
    }
  }

  // Events
  if (els.fetchInfo) {
    els.fetchInfo.addEventListener("click", fetchInfo);
  }
  if (els.download) {
    els.download.addEventListener("click", doDownload);
  }
  if (els.typeVideoBtn) {
    els.typeVideoBtn.addEventListener("click", () => toggleType("video"));
  }
  if (els.typeAudioBtn) {
    els.typeAudioBtn.addEventListener("click", () => toggleType("audio"));
  }

  // Default UI state
  toggleType("video");
  setStatus("");
})();
