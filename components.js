// components.js
// Injects a reusable Navbar and Footer + handles theme toggle and feature selection

(function () {
  function onReady(cb) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", cb);
    } else {
      cb();
    }
  }

  function detectBase() {
    const path = location.pathname.replace(/\\/g, "/");
    const inFeatures = /\/features(\/|$)/.test(path);
    return {
      base: inFeatures ? ".." : ".",
      inFeatures,
    };
  }

  function applyTheme(theme) {
    const t = theme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem("theme", t);
    const btn = document.getElementById("themeToggle");
    if (btn) {
      const isDark = t === "dark";
      btn.textContent = isDark ? "🌞" : "🌙";
      btn.setAttribute("aria-label", isDark ? "Switch to light theme" : "Switch to dark theme");
      btn.title = isDark ? "Light mode" : "Dark mode";
    }
  }

  function initTheme() {
    const stored = localStorage.getItem("theme");
    if (stored) {
      applyTheme(stored);
      return;
    }
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(prefersDark ? "dark" : "light");
  }

  function buildHeader(base) {
    return `
      <nav class="navbar">
        <div class="nav-left">
          <a class="brand" href="${base}/index.html" aria-label="Beranda">Crypto Tools</a>
          <button class="nav-toggle" aria-label="Buka menu">☰</button>
        </div>
        <ul class="nav-links">
          <li><a href="${base}/index.html">Home</a></li>
          <li><a href="${base}/index.html#about">About</a></li>
          <li><a href="${base}/index.html#contact">Contact</a></li>
          <li><a href="${base}/index.html#projects">Project</a></li>
        </ul>
        <div class="nav-actions">
          <label class="feature-select-label" for="featureSelect">Fitur:</label>
          <select id="featureSelect" class="feature-select" aria-label="Pilih fitur">
            <option value="">Pilih fitur...</option>
            <option value="${base}/features/aes-gcm.html">AES-GCM Encrypt/Decrypt</option>
            <option value="${base}/features/youtube-downloader.html">YouTube Downloader</option>
            <option value="" disabled>Hash/Checksum (Coming Soon)</option>
            <option value="" disabled>JWT Tools (Coming Soon)</option>
            <option value="" disabled>RSA/EC Keys (Coming Soon)</option>
            <option value="" disabled>Base64 Tools (Coming Soon)</option>
            <option value="" disabled>UUID (Coming Soon)</option>
          </select>
          <button id="themeToggle" class="theme-toggle" aria-label="Toggle theme">🌙</button>
        </div>
      </nav>
    `;
  }

  function buildFooter() {
    const year = new Date().getFullYear();
    return `
      <div class="footer-inner">
        <div class="footer-left">
          <strong>Crypto Tools</strong> — Memudahkan proses kriptografi sehari-hari.
        </div>
        <div class="footer-right">
          <a href="#" aria-label="GitHub">GitHub</a>
          <span class="dot">•</span>
          <a href="#" aria-label="LinkedIn">LinkedIn</a>
        </div>
      </div>
      <div class="footer-copy">© ${year} Crypto Tools. Dibuat dengan ❤️.</div>
    `;
  }

  onReady(function () {
    const { base, inFeatures } = detectBase();

    // Inject Header
    const header = document.getElementById("site-header");
    if (header) {
      header.innerHTML = buildHeader(base);
    }

    // Inject Footer
    const footer = document.getElementById("site-footer");
    if (footer) {
      footer.innerHTML = buildFooter();
    }

    // Initialize Theme
    initTheme();

    // Theme toggle handler
    const themeBtn = document.getElementById("themeToggle");
    if (themeBtn) {
      themeBtn.addEventListener("click", () => {
        const current = document.documentElement.getAttribute("data-theme");
        applyTheme(current === "dark" ? "light" : "dark");
      });
    }

    // Feature select handler
    const featureSelect = document.getElementById("featureSelect");
    if (featureSelect) {
      featureSelect.addEventListener("change", (e) => {
        const val = e.target.value;
        if (val) window.location.href = val;
      });

      // Preselect when on a feature page
      const path = location.pathname.replace(/\\/g, "/");
      if (/\/features\/aes-gcm\.html$/.test(path)) {
        featureSelect.value = `${base}/features/aes-gcm.html`;
      } else if (/\/features\/youtube-downloader\.html$/.test(path)) {
        featureSelect.value = `${base}/features/youtube-downloader.html`;
      }
    }

    // Mobile nav toggle
    const navToggle = document.querySelector(".nav-toggle");
    const navLinks = document.querySelector(".nav-links");
    if (navToggle && navLinks) {
      navToggle.addEventListener("click", () => {
        navLinks.classList.toggle("open");
      });
    }
  });
})();
