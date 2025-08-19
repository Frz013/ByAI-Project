/*
  crypto-aesgcm.js
  Pure cryptographic logic for AES-GCM with PBKDF2 (SHA-256).
  Exposes window.AESGCM with:
    - bufToBase64(buf)
    - base64ToBuf(b64)
    - getKeyFromPassword(password, saltBytes, iterations = 100000)
    - encryptString(plainText, password, iterations = 100000)
    - decryptString(ciphertextB64, password, ivB64, saltB64, iterations = 100000)
*/

(() => {
  const enc = new TextEncoder();
  const dec = new TextDecoder();

  // ArrayBuffer/TypedArray -> Base64
  function bufToBase64(buf) {
    const bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : buf;
    let binary = "";
    const chunkSize = 0x8000; // avoid call stack limit issues
    for (let i = 0; i < bytes.length; i += chunkSize) {
      const chunk = bytes.subarray(i, i + chunkSize);
      binary += String.fromCharCode.apply(null, chunk);
    }
    return btoa(binary);
  }

  // Base64 -> ArrayBuffer
  function base64ToBuf(b64) {
    const binary = atob((b64 || "").trim());
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
  }

  // PBKDF2 key derivation for AES-GCM 256
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

  // Encrypt string -> base64 fields
  async function encryptString(plainText, password, iterations = 100000) {
    const iv = crypto.getRandomValues(new Uint8Array(12));   // 96-bit IV
    const salt = crypto.getRandomValues(new Uint8Array(16)); // 128-bit salt
    const key = await getKeyFromPassword(password, salt, iterations);

    const cipherBuf = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      key,
      enc.encode(plainText)
    );

    return {
      ciphertextB64: bufToBase64(cipherBuf),
      ivB64: bufToBase64(iv),
      saltB64: bufToBase64(salt),
      iterations,
    };
  }

  // Decrypt using base64 inputs
  async function decryptString(ciphertextB64, password, ivB64, saltB64, iterations = 100000) {
    const iv = new Uint8Array(base64ToBuf(ivB64));
    const salt = new Uint8Array(base64ToBuf(saltB64));
    const ciphertext = base64ToBuf(ciphertextB64);

    const key = await getKeyFromPassword(password, salt, iterations);
    const plainBuf = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      key,
      ciphertext
    );
    return dec.decode(plainBuf);
  }

  window.AESGCM = {
    bufToBase64,
    base64ToBuf,
    getKeyFromPassword,
    encryptString,
    decryptString,
  };
})();
