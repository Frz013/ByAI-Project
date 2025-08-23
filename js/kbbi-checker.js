(function () {
  function $(sel) {
    return document.querySelector(sel);
  }
  function onReady(cb) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", cb);
    } else {
      cb();
    }
  }
  function htmlEscape(s) {
    return (s == null ? "" : String(s))
      .replace(/&/g, "&amp;")
      .replace(/</g, "<")
      .replace(/>/g, ">");
  }

  const API_BASE = "http://127.0.0.1:5000";

  async function cekKata(kata) {
    const url = `${API_BASE}/api/kbbi/cek?kata=${encodeURIComponent(kata)}`;
    const resp = await fetch(url, { method: "GET" });
    let data = null;
    let text = await resp.text();
    try {
      data = JSON.parse(text);
    } catch (_) {
      // backend error page or non-JSON
      throw new Error("Gagal memproses respons server.");
    }
    if (!resp.ok) {
      // 4xx/5xx
      if (data && data.error) {
        const errLower = String(data.error || "").toLowerCase();
        if (errLower.includes("tidak ditemukan")) {
          const e = new Error("kata tidak ditemukan");
          e.code = 404;
          // sertakan saran dari backend bila ada
          if (Array.isArray(data.saran)) e.saran = data.saran;
          throw e;
        }
        const e = new Error(String(data.error));
        throw e;
      }
      throw new Error("Terjadi kesalahan pada server.");
    }
    return data;
  }

  function renderHasil(container, payload) {
    container.innerHTML = "";
    if (!payload || !payload.valid) {
      container.innerHTML = `<p class="kbbi-error">kata tidak ditemukan</p>`;
      return;
    }
    // Jika backend menyediakan entri terstruktur, render sebagai kartu per entri
    const entri = Array.isArray(payload.entri) ? payload.entri : [];
    if (entri.length) {
      const cards = entri.map((e) => {
        const makna = Array.isArray(e.makna) ? e.makna : [];
        const maknaList = makna.map((m) => {
          const parts = [];
          if (m.kelas) {
            parts.push(`<div><strong>Kelas:</strong> <span class="tag">${htmlEscape(m.kelas)}</span></div>`);
          }
          if (m.deskripsi) {
            parts.push(`<div class="desc">${htmlEscape(m.deskripsi)}</div>`);
          }
          if (Array.isArray(m.contoh) && m.contoh.length) {
            parts.push(`<div class="contoh"><em>Contoh:</em><ul>${m.contoh.map((c)=>`<li>${htmlEscape(c)}</li>`).join("")}</ul></div>`);
          }
          if (Array.isArray(m.sinonim) && m.sinonim.length) {
            parts.push(`<div class="sinonim"><em>Sinonim:</em> ${m.sinonim.map((s)=>`<code>${htmlEscape(s)}</code>`).join(", ")}</div>`);
          }
          if (Array.isArray(m.antonim) && m.antonim.length) {
            parts.push(`<div class="antonim"><em>Antonim:</em> ${m.antonim.map((a)=>`<code>${htmlEscape(a)}</code>`).join(", ")}</div>`);
          }
          return `<li>${parts.join("")}</li>`;
        }).join("");
        return `<div class="kbbi-card">
          <div><strong>Lema:</strong> <code>${htmlEscape(e.lema || "")}</code></div>
          ${makna.length ? `<h3>Makna</h3><ul>${maknaList}</ul>` : ""}
        </div>`;
      }).join("");
      container.innerHTML = cards;
      return;
    }

    // Fallback ke skema lama (lema + definisi)
    const lemma = Array.isArray(payload.lema) ? payload.lema : [];
    const defs = Array.isArray(payload.definisi) ? payload.definisi : [];

    const lemmaHtml = lemma.length
      ? `<div><strong>Lema:</strong> ${lemma.map((x) => `<code>${htmlEscape(x)}</code>`).join(", ")}</div>`
      : "";

    const defsHtml = defs.length
      ? `<h3>Definisi</h3><ul>${defs.map((d) => `<li>${htmlEscape(d)}</li>`).join("")}</ul>`
      : `<p class="kbbi-error">Definisi tidak tersedia.</p>`;

    container.innerHTML = `${lemmaHtml}${defsHtml}`;
  }

  onReady(function () {
    const form = $("#kbbiForm");
    const input = $("#kataInput");
    const status = $("#status");
    const hasil = $("#hasil");
    const errBox = $("#err");

    if (!form || !input) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      errBox.textContent = "";
      hasil.innerHTML = "";
      const kata = (input.value || "").trim();
      if (!kata) {
        errBox.textContent = "Kata wajib diisi.";
        return;
      }
      status.textContent = "Memeriksa kata di KBBI...";
      try {
        const data = await cekKata(kata);
        status.innerHTML = `<span class="kbbi-ok">Kata valid di KBBI.</span>`;
        renderHasil(hasil, data);
      } catch (ex) {
        const msg = (ex && ex.message) || "Terjadi kesalahan.";
        if (ex && ex.code === 404) {
          const saran = Array.isArray(ex.saran) ? ex.saran : [];
          status.innerHTML = `<span class="kbbi-error">Kata tidak baku menurut KBBI.</span>`;
          const saranHtml = saran.length
            ? `<div><strong>Saran ejaan:</strong> ${saran.map((s)=>`<code>${htmlEscape(s)}</code>`).join(", ")}</div>`
            : `<div class="kbbi-status">Tidak ada saran ejaan.</div>`;
          hasil.innerHTML = `<div class="kbbi-card"><p class="kbbi-error">kata tidak ditemukan</p>${saranHtml}</div>`;
        } else {
          status.textContent = "";
          errBox.textContent = msg;
        }
      }
    });

    // Enter to submit UX
    input.addEventListener("keypress", (ev) => {
      if (ev.key === "Enter") {
        form.dispatchEvent(new Event("submit"));
      }
    });
  });
})();
