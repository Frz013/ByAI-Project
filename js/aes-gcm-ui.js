/*
  aes-gcm-ui.js
  DOM handlers for AES-GCM feature page. Uses window.AESGCM from crypto-aesgcm.js.
  Implements:
    - Encrypt/Decrypt string
    - Copy result
    - Download encrypted (.enc JSON)
    - Upload & Encrypt (text files)
    - Upload & Decrypt (.enc JSON)
*/

(() => {
  const AES = window.AESGCM;
  if (!AES) {
    console.error("AESGCM library not loaded. Ensure crypto-aesgcm.js is included before this file.");
    return;
  }

  // --- Helpers ---
  function $(id) {
    return document.getElementById(id);
  }

  function safeJSONParse(text) {
    try {
      return JSON.parse(text);
    } catch (_) {
      return null;
    }
  }

  function readFileAsText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error || new Error("Gagal membaca file"));
      reader.readAsText(file);
    });
  }

  function downloadBlob(data, filename, mime = "application/json") {
    const blob = new Blob([data], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      a.remove();
    }, 0);
  }

  async function copyToClipboard(text) {
    if (!text) {
      alert("Tidak ada data untuk disalin.");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        alert("Disalin ke clipboard.");
      } catch (e) {
        // fallback
        fallbackCopy(text);
      }
    } else {
      fallbackCopy(text);
    }
  }

  function fallbackCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
      document.execCommand("copy");
      alert("Disalin ke clipboard.");
    } catch (e) {
      alert("Gagal menyalin ke clipboard.");
    } finally {
      ta.remove();
    }
  }

  // --- Elements ---
  const passwordEl = $("password");
  const inputStringEl = $("inputString");

  const ciphertextEl = $("ciphertext");
  const ivEl = $("iv");
  const saltEl = $("salt");
  const decryptedOutputEl = $("decryptedOutput");

  const encryptBtn = $("encryptButton");
  const decryptBtn = $("decryptButton");
  const copyBtn = $("copyButton");
  const downloadBtn = $("downloadButton");

  const fileInput = $("fileInput");
  const encFileInput = $("encFileInput");
  const uploadEncryptBtn = $("uploadEncryptButton");
  const uploadDecryptBtn = $("uploadDecryptButton");

  // --- Button handlers ---

  if (encryptBtn) {
    encryptBtn.addEventListener("click", async () => {
      const pwd = (passwordEl?.value || "").trim();
      const plain = inputStringEl?.value ?? "";
      if (!pwd) {
        alert("Masukkan password terlebih dahulu.");
        return;
      }
      try {
        const { ciphertextB64, ivB64, saltB64 } = await AES.encryptString(plain, pwd);
        if (ciphertextEl) ciphertextEl.value = ciphertextB64;
        if (ivEl) ivEl.value = ivB64;
        if (saltEl) saltEl.value = saltB64;
        if (decryptedOutputEl) decryptedOutputEl.value = "";
      } catch (err) {
        console.error(err);
        alert("Gagal melakukan enkripsi.");
      }
    });
  }

  if (decryptBtn) {
    decryptBtn.addEventListener("click", async () => {
      const pwd = (passwordEl?.value || "").trim();
      const ct = (ciphertextEl?.value || "").trim();
      const iv = (ivEl?.value || "").trim();
      const salt = (saltEl?.value || "").trim();
      if (!pwd) {
        alert("Masukkan password terlebih dahulu.");
        return;
      }
      if (!ct || !iv || !salt) {
        alert("Lengkapi ciphertext, IV, dan Salt (Base64).");
        return;
      }
      try {
        const plain = await AES.decryptString(ct, pwd, iv, salt);
        if (decryptedOutputEl) decryptedOutputEl.value = plain;
      } catch (err) {
        console.error(err);
        if (decryptedOutputEl) decryptedOutputEl.value = "";
        // Typical failure: OperationError / DOMException due to wrong password or corrupted inputs
        alert("Dekripsi gagal. Periksa password, IV, Salt, atau ciphertext Anda.");
      }
    });
  }

  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const src =
        (decryptedOutputEl?.value || "").trim() ||
        (ciphertextEl?.value || "").trim();
      await copyToClipboard(src);
    });
  }

  if (downloadBtn) {
    downloadBtn.addEventListener("click", () => {
      const ct = (ciphertextEl?.value || "").trim();
      const iv = (ivEl?.value || "").trim();
      const salt = (saltEl?.value || "").trim();
      if (!ct || !iv || !salt) {
        alert("Tidak ada data terenkripsi untuk diunduh. Lakukan enkripsi terlebih dahulu.");
        return;
      }
      const payload = {
        version: 1,
        algo: "AES-GCM",
        kdf: "PBKDF2-SHA256",
        iterations: 100000,
        ciphertext: ct,
        iv,
        salt,
      };
      const json = JSON.stringify(payload, null, 2);
      downloadBlob(json, "encrypted.enc", "application/json");
    });
  }

  if (uploadEncryptBtn) {
    uploadEncryptBtn.addEventListener("click", async () => {
      const pwd = (passwordEl?.value || "").trim();
      if (!pwd) {
        alert("Masukkan password terlebih dahulu.");
        return;
      }
      const file = fileInput?.files?.[0];
      if (!file) {
        alert("Pilih file teks terlebih dahulu.");
        return;
      }
      try {
        const content = await readFileAsText(file);
        const { ciphertextB64, ivB64, saltB64 } = await AES.encryptString(content, pwd);
        const payload = {
          version: 1,
          algo: "AES-GCM",
          kdf: "PBKDF2-SHA256",
          iterations: 100000,
          ciphertext: ciphertextB64,
          iv: ivB64,
          salt: saltB64,
        };
        const json = JSON.stringify(payload, null, 2);
        const outName = file.name.endsWith(".enc") ? file.name : `${file.name}.enc`;
        downloadBlob(json, outName, "application/json");

        // Populate fields for reference
        if (ciphertextEl) ciphertextEl.value = ciphertextB64;
        if (ivEl) ivEl.value = ivB64;
        if (saltEl) saltEl.value = saltB64;
        if (decryptedOutputEl) decryptedOutputEl.value = "";
      } catch (err) {
        console.error(err);
        alert("Gagal mengunggah & mengenkripsi file.");
      }
    });
  }

  if (uploadDecryptBtn) {
    uploadDecryptBtn.addEventListener("click", async () => {
      const pwd = (passwordEl?.value || "").trim();
      if (!pwd) {
        alert("Masukkan password terlebih dahulu.");
        return;
      }
      const file = encFileInput?.files?.[0];
      if (!file) {
        alert("Pilih file .enc terlebih dahulu.");
        return;
      }
      try {
        const text = await readFileAsText(file);
        const data = safeJSONParse(text);
        if (
          !data ||
          typeof data.ciphertext !== "string" ||
          typeof data.iv !== "string" ||
          typeof data.salt !== "string"
        ) {
          alert("Format file .enc tidak valid.");
          return;
        }
        const iterations = Number.isInteger(data.iterations) ? data.iterations : 100000;

        // Fill fields for visibility
        if (ciphertextEl) ciphertextEl.value = data.ciphertext;
        if (ivEl) ivEl.value = data.iv;
        if (saltEl) saltEl.value = data.salt;

        const plain = await AES.decryptString(data.ciphertext, pwd, data.iv, data.salt, iterations);
        if (decryptedOutputEl) decryptedOutputEl.value = plain;
      } catch (err) {
        console.error(err);
        if (decryptedOutputEl) decryptedOutputEl.value = "";
        alert("Gagal mengunggah & mendekripsi file. Pastikan password benar dan file tidak korup.");
      }
    });
  }
})();
