/*
  Browser-based AES-GCM encryption/decryption using Web Crypto API.
  - Key derivation: PBKDF2 (SHA-256, 100000 iterations)
  - IV: 12 bytes (recommended for AES-GCM)
  - Salt: 16 bytes
  Data exchanged/shown as Base64 for easy copy/paste.
*/

(() => {
  const enc = new TextEncoder();
  const dec = new TextDecoder();

  // --- Utils: ArrayBuffer <-> Base64 ---
  function bufToBase64(buf) {
    const bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : buf;
    let binary = "";
    const chunkSize = 0x8000; // avoid call stack limit
    for (let i = 0; i < bytes.length; i += chunkSize) {
      const chunk = bytes.subarray(i, i + chunkSize);
      binary += String.fromCharCode.apply(null, chunk);
    }
    return btoa(binary);
  }

  function base64ToBuf(b64) {
    const binary = atob((b64 || "").trim());
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
  }

  // --- PBKDF2 key derivation (AES-GCM 256) ---
  async function getKeyFromPassword(password, saltBytes, iterations = 100000) {
    const keyMaterial = await crypto.subtle.importKey(
      "raw",
      enc.encode(password),
      { name: "PBKDF2" },
      false,
      ["deriveKey"]
    );
    return crypto.subtle.deriveKey(
      {
        name: "PBKDF2",
        salt: saltBytes,
        iterations,
        hash: "SHA-256",
      },
      keyMaterial,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"]
    );
  }

  // --- Encryption/Decryption helpers ---
  async function encryptString(plainText, password) {
    console.log("Encrypting:", { plainText, password }); // Added log
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const key = await getKeyFromPassword(password, salt);

    const cipherBuf = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      key,
      enc.encode(plainText)
    );

    console.log("Encryption successful:", {
      ciphertextB64: bufToBase64(cipherBuf),
      ivB64: bufToBase64(iv),
      saltB64: bufToBase64(salt),
    });

    return {
      ciphertextB64: bufToBase64(cipherBuf),
      ivB64: bufToBase64(iv),
      saltB64: bufToBase64(salt),
    };
  }

  async function decryptString(ciphertextB64, password, ivB64, saltB64) {
    const iv = new Uint8Array(base64ToBuf(ivB64));
    const salt = new Uint8Array(base64ToBuf(saltB64));
    const ciphertext = base64ToBuf(ciphertextB64);

    const key = await getKeyFromPassword(password, salt);
    const plainBuf = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      key,
      ciphertext
    );
    return dec.decode(plainBuf);
  }

  // --- DOM elements ---
  const passwordEl = document.getElementById("password");
  const inputStringEl = document.getElementById("inputString");

  const ciphertextEl = document.getElementById("ciphertext");
  const ivEl = document.getElementById("iv");
  const saltEl = document.getElementById("salt");
  const decryptedOutputEl = document.getElementById("decryptedOutput");

  const encryptBtn = document.getElementById("encryptButton");
  const decryptBtn = document.getElementById("decryptButton");
  const copyBtn = document.getElementById("copyButton");
  const downloadBtn = document.getElementById("downloadButton");

  // --- Button handlers ---
  if (encryptBtn) {
    encryptBtn.addEventListener("click", async () => {
      const pwd = passwordEl.value; // Get password from input
      console.log("Button clicked"); // Added log
      console.log("Password:", pwd); // Log password
      console.log("Plaintext:", inputStringEl.value); // Log plaintext
      if (!pwd) return;

      try {
        const plain = inputStringEl?.value ?? "";
        const { ciphertextB64, ivB64, saltB64 } = await encryptString(
          plain,
          pwd
        );
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

  // ... (rest of the code remains unchanged)
})();
