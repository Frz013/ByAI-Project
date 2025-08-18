# TODO — Crypto Tools

This file tracks the implementation steps for the homepage, navbar, footer, feature menu, and related theme work.

## Completed
- [x] Plan approved with preferences:
  - Homepage at `index.html`, AES-GCM moved to `features/aes-gcm.html`
  - Navbar items: Home, About, Contact, Project
  - Dummy brand text (logo to be added later)
  - Keep blue glassmorphism theme
  - Footer with copyright and links
  - Feature menu with AES-GCM and Coming Soon cards
  - Bahasa Indonesia UI
  - Include theme toggle (dark/light)
- [x] Created `components.js`
  - Injects Navbar and Footer on all pages
  - Theme toggle (dark/light) with `localStorage` and system preference default
  - Feature select menu with routing (preselect on AES page)
  - Mobile nav toggle
- [x] Created `features/aes-gcm.html` and migrated existing AES-GCM UI from old `index.html`
- [x] Refactored `index.html` to be the homepage
  - Hero section
  - Features grid (AES-GCM + Coming Soon cards)
  - About and Contact sections
- [x] Updated `styles.css`
  - Added theme variables for dark/light
  - Navbar, Hero, Features grid, Footer styles
  - Kept backward compatible styles to avoid breaking current UI

## Pending / Next Steps
- [ ] CSS cleanup (remove legacy/duplicate rules safely):
  - Legacy `h1` color, older `section` styles, older `button` rules, etc. Only remove after confirming no regressions.
- [ ] Implement remaining AES features in `script.js`:
  - [ ] Decrypt string handler (`#decryptButton`)
  - [ ] Copy result (`#copyButton`)
  - [ ] Download encrypted file (`#downloadButton`)
  - [ ] Upload & Encrypt (`#uploadEncryptButton`)
  - [ ] Upload & Decrypt (`#uploadDecryptButton`)
- [ ] Populate real content for About/Contact sections
- [ ] Footer links: add actual GitHub/LinkedIn URLs
- [ ] Brand: integrate logo asset when provided
- [ ] Accessibility improvements (focus states, skip links)
- [ ] Responsive QA across devices and browsers
- [ ] Optional: 404 page for better UX
- [ ] Deployment (e.g., GitHub Pages/Netlify)

## How to run locally
- Open `index.html` in your browser.
  - From VS Code, right-click `index.html` > Open with Live Server (if extension installed), or open directly in the browser.
- Navigate via Navbar or the feature select dropdown to `features/aes-gcm.html` to use the AES tool.

## Notes
- Theme toggle persists between sessions via `localStorage`.
- The homepage does not load crypto logic; it’s only loaded on the feature page for performance.
