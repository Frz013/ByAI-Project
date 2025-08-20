// js/perpustakaan.js
// Frontend logic for "Book List Generator" feature.

(() => {
  // Allow overriding API endpoint via query param ?api=http://localhost:5001
  try {
    const usp = new URLSearchParams(window.location.search);
    const apiOverride = usp.get("api");
    if (apiOverride) {
      localStorage.setItem("LIB_API_BASE", apiOverride);
    }
  } catch (e) {}
  const API_BASE = localStorage.getItem("LIB_API_BASE") || "http://localhost:5000";

  // Elements
  const els = {
    judul: document.getElementById("judul"),
    penulis: document.getElementById("penulis"),
    tahun: document.getElementById("tahun"),
    tambahBtn: document.getElementById("tambahBtn"),
    resetBtn: document.getElementById("resetBtn"),
    status: document.getElementById("statusMsg"),
    tbody: document.getElementById("bookTbody"),
    exportFmt: document.getElementById("exportFormat"),
    exportBtn: document.getElementById("exportBtn"),
    // Edit modal elements
    editModal: document.getElementById("editModal"),
    editForm: document.getElementById("editForm"),
    editPk: document.getElementById("editPk"),
    editTanggal: document.getElementById("editTanggal"),
    editPenulis: document.getElementById("editPenulis"),
    editJudul: document.getElementById("editJudul"),
    editTahun: document.getElementById("editTahun"),
    editSaveBtn: document.getElementById("editSaveBtn"),
    editCancelBtn: document.getElementById("editCancelBtn"),
  };

  function setStatus(text, type = "info") {
    if (!els.status) return;
    els.status.textContent = text || "";
    els.status.style.color = type === "error" ? "#ef4444" : "var(--muted)";
  }

  function clearForm() {
    if (els.judul) els.judul.value = "";
    if (els.penulis) els.penulis.value = "";
    if (els.tahun) els.tahun.value = "";
  }

  function createActionButton(label, className = "", onClick = null, ariaLabel = "") {
    const btn = document.createElement("button");
    btn.textContent = label;
    if (className) btn.className = className;
    if (ariaLabel) btn.setAttribute("aria-label", ariaLabel);
    if (onClick) btn.addEventListener("click", onClick);
    return btn;
  }

  // ===== Modal Edit Helpers =====
  let currentEdit = null;

  function openEditModal(item) {
    currentEdit = item;
    if (!els.editModal) return;
    if (els.editPk) els.editPk.value = item.pk || "";
    if (els.editTanggal) els.editTanggal.value = item.date_add || "";
    if (els.editPenulis) els.editPenulis.value = item.penulis || "";
    if (els.editJudul) els.editJudul.value = item.judul || "";
    if (els.editTahun) els.editTahun.value = item.tahun || "";
    els.editModal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeEditModal() {
    if (!els.editModal) return;
    els.editModal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    currentEdit = null;
  }

  function onModalInit() {
    if (!els.editModal) return;
    const overlay = els.editModal.querySelector(".modal-overlay");
    if (overlay) {
      overlay.addEventListener("click", (e) => {
        if (e.target && e.target.getAttribute && e.target.getAttribute("data-close") === "true") {
          closeEditModal();
        }
      });
    }
    if (els.editCancelBtn) els.editCancelBtn.addEventListener("click", closeEditModal);
    if (els.editSaveBtn) els.editSaveBtn.addEventListener("click", handleEditSave);
  }

  async function handleEditSave() {
    if (!currentEdit) { closeEditModal(); return; }

    const payload = {};
    let any = false;

    const pen = (els.editPenulis && els.editPenulis.value || "").trim();
    const jud = (els.editJudul && els.editJudul.value || "").trim();
    const thn = (els.editTahun && String(els.editTahun.value) || "").trim();

    if (pen !== "" && pen !== (currentEdit.penulis || "")) {
      payload.penulis = pen; any = true;
    }
    if (jud !== "" && jud !== (currentEdit.judul || "")) {
      payload.judul = jud; any = true;
    }
    if (thn !== "" && thn !== (currentEdit.tahun || "")) {
      if (!validateYear(thn)) {
        setStatus("Tahun harus 4 digit (YYYY). Perubahan tahun dibatalkan.", "error");
        return;
      }
      payload.tahun = thn; any = true;
    }

    if (!any) {
      setStatus("Tidak ada perubahan untuk disimpan.");
      closeEditModal();
      return;
    }

    try {
      setStatus(`Menyimpan perubahan untuk ${currentEdit.pk}…`);
      const res = await fetch(`${API_BASE}/api/library/books/${encodeURIComponent(currentEdit.pk)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let err = `Gagal menyimpan perubahan (HTTP ${res.status}).`;
        try {
          const j = await res.json();
          if (j && j.error) err = j.error;
        } catch (_) {}
        setStatus(err, "error");
        return;
      }
      await loadBooks();
      setStatus("Perubahan berhasil disimpan.");
      closeEditModal();
    } catch (e) {
      console.error(e);
      setStatus("Terjadi kesalahan saat menyimpan perubahan.", "error");
    }
  }

  // Initialize modal listeners after DOM is ready (script is defer-ed)
  onModalInit();

  function renderRows(data) {
    if (!els.tbody) return;
    els.tbody.innerHTML = "";
    (data || []).forEach((item, idx) => {
      const tr = document.createElement("tr");

      // Nomor urut
      const tdNo = document.createElement("td");
      tdNo.textContent = String(idx + 1);
      tdNo.className = "col-no";
      tr.appendChild(tdNo);

      const tdPk = document.createElement("td");
      tdPk.textContent = item.pk || "";
      tr.appendChild(tdPk);

      const tdDate = document.createElement("td");
      tdDate.textContent = item.date_add || "";
      tr.appendChild(tdDate);

      const tdPenulis = document.createElement("td");
      tdPenulis.textContent = item.penulis || "";
      tr.appendChild(tdPenulis);

      const tdJudul = document.createElement("td");
      tdJudul.textContent = item.judul || "";
      tr.appendChild(tdJudul);

      const tdTahun = document.createElement("td");
      tdTahun.textContent = item.tahun || "";
      tr.appendChild(tdTahun);

      const tdAksi = document.createElement("td");
      tdAksi.className = "actions";

      const editBtn = createActionButton("Edit", "secondary", async () => {
        await onEdit(item);
      }, `Edit ${item.pk}`);
      const delBtn = createActionButton("Hapus", "danger", async () => {
        await onDelete(item);
      }, `Hapus ${item.pk}`);

      tdAksi.appendChild(editBtn);
      tdAksi.appendChild(document.createTextNode(" "));
      tdAksi.appendChild(delBtn);

      tr.appendChild(tdAksi);

      els.tbody.appendChild(tr);
    });
  }

  async function loadBooks() {
    setStatus("Memuat data…");
    try {
      const res = await fetch(`${API_BASE}/api/library/books`);
      if (!res.ok) {
        setStatus(`Gagal memuat data (HTTP ${res.status}).`, "error");
        return;
      }
      const data = await res.json();
      renderRows(data);
      setStatus("Data dimuat.");
    } catch (e) {
      console.error(e);
      setStatus("Terjadi kesalahan saat memuat data.", "error");
    }
  }

  function validateYear(y) {
    if (!y) return false;
    const s = String(y).trim();
    return s.length === 4 && /^\d{4}$/.test(s);
  }

  async function addBook() {
    const judul = (els.judul.value || "").trim();
    const penulis = (els.penulis.value || "").trim();
    const tahun = (els.tahun.value || "").trim();

    if (!judul || !penulis || !tahun) {
      setStatus("Semua field (Judul, Penulis, Tahun) wajib diisi.", "error");
      return;
    }
    if (!validateYear(tahun)) {
      setStatus("Tahun harus 4 digit (YYYY).", "error");
      return;
    }

    setStatus("Menambahkan buku…");
    try {
      const res = await fetch(`${API_BASE}/api/library/books`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ judul, penulis, tahun }),
      });
      if (!res.ok) {
        let err = `Gagal menambahkan buku (HTTP ${res.status}).`;
        try {
          const j = await res.json();
          if (j && j.error) err = j.error;
        } catch (_) {}
        setStatus(err, "error");
        return;
      }
      clearForm();
      await loadBooks();
      setStatus("Buku berhasil ditambahkan.");
    } catch (e) {
      console.error(e);
      setStatus("Terjadi kesalahan saat menambahkan buku.", "error");
    }
  }

  async function onEdit(item) {
    // Buka modal edit dengan field terisi nilai saat ini
    openEditModal(item);
  }

  async function onDelete(item) {
    const ok = confirm(`Yakin ingin menghapus data dengan PK: ${item.pk}?`);
    if (!ok) return;

    setStatus(`Menghapus ${item.pk}…`);
    try {
      const res = await fetch(`${API_BASE}/api/library/books/${encodeURIComponent(item.pk)}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        let err = `Gagal menghapus (HTTP ${res.status}).`;
        try {
          const j = await res.json();
          if (j && j.error) err = j.error;
        } catch (_) {}
        setStatus(err, "error");
        return;
      }
      await loadBooks();
      setStatus("Data berhasil dihapus.");
    } catch (e) {
      console.error(e);
      setStatus("Terjadi kesalahan saat menghapus.", "error");
    }
  }

  async function exportData() {
    const fmt = (els.exportFmt.value || "json").toLowerCase();
    if (!["json", "txt"].includes(fmt)) {
      setStatus("Format export tidak valid.", "error");
      return;
    }
    setStatus("Menyiapkan unduhan…");
    try {
      // Use anchor download to preserve filename set by server
      const url = `${API_BASE}/api/library/export?format=${encodeURIComponent(fmt)}`;
      const a = document.createElement("a");
      a.href = url;
      a.target = "_blank";
      // download attribute will be ignored if cross-origin without CORS headers for navigation,
      // but backend sets Content-Disposition, so browser should honor filename.
      document.body.appendChild(a);
      a.click();
      a.remove();
      setStatus("Unduhan dimulai.");
    } catch (e) {
      console.error(e);
      setStatus("Gagal menyiapkan unduhan.", "error");
    }
  }

  // Bind events
  if (els.tambahBtn) els.tambahBtn.addEventListener("click", addBook);
  if (els.resetBtn) els.resetBtn.addEventListener("click", clearForm);
  if (els.exportBtn) els.exportBtn.addEventListener("click", exportData);

  // Initial load
  loadBooks();
  setStatus("");
})();
