# TODO — Kalkulator Transformasi Geometri (Desmos)

Rencana kerja terurut untuk menambahkan fitur kalkulator transformasi geometri sesuai spesifikasi yang disetujui.

## Spesifikasi Ringkas
- Halaman baru: features/geo-transform.html, ditautkan dari index.html dan dropdown di navbar.
- Objek: Titik (banyak), Garis (y=mx+b dan Ax+By+C=0), Fungsi (eksplisit y=f(x), domain default [-10,10]).
- Transformasi (tanpa chain):
  - Translasi: (dx, dy)
  - Rotasi: sudut derajat, pusat (cx, cy) (default 0,0)
  - Refleksi: sumbu-X, sumbu-Y, y=x, y=-x, umum y=mx+b
  - Dilatasi: faktor k (real, bisa negatif), pusat (cx, cy) (default 0,0)
- Desmos: tema light, grid on, pan/zoom on, bounds x,y in [-10, 10].
- Kontrol: input angka + slider (live update), toggle tampilkan asal/bayangan, legenda warna (asal biru #3b82f6, bayangan merah #ef4444), Reset dan Undo (1 langkah).
- Hasil simbolik: tampilkan persamaan hasil (fungsi: translasi eksplisit, transformasi lain parametrik/implisit).
- Batas: Titik maks 200; fungsi sampling adaptif maks 1000–1500 titik; pembulatan tampilan 2 desimal.
- Library/CDN:
  - Desmos API: https://www.desmos.com/api/v1.8/calculator.js?apiKey=dcb31709b452b1cf9dc26972add0fda6
  - math.js: https://cdn.jsdelivr.net/npm/mathjs@11/dist/math.min.js

## Task List

1) Struktur Halaman
- [ ] Buat features/geo-transform.html
  - [ ] Panel kiri: input objek (Titik/Garis/Fungsi) dan parameter transformasi
  - [ ] Panel kanan: kanvas Desmos (#calc), legenda, hasil simbolik, petunjuk
  - [ ] Muat styles.css, components.js, math.js, Desmos API, js/geo-math.js, js/geo-transform.js
  - [ ] Layout responsif 2 kolom (desktop), stack (mobile)

2) Util & Matematika (js/geo-math.js)
- [ ] Parser:
  - [ ] Titik: parse dari textarea ke array [x,y], validasi, batasi 200
  - [ ] Garis: normalisasi dari y=mx+b atau Ax+By+C=0 ke koef (A,B,C)
  - [ ] Fungsi: sanitasi string f(x), gunakan math.js untuk evaluasi aman
- [ ] Transform:
  - [ ] translatePoint(p, dx, dy)
  - [ ] rotatePoint(p, deg, cx, cy)
  - [ ] reflectPointAcrossLine(p, A, B, C)
  - [ ] dilatePoint(p, k, cx, cy)
  - [ ] lineTransform(A,B,C, op): translasi tertutup (C' = C - A*dx - B*dy), lainnya via 2 titik -> (A',B',C')
  - [ ] functionSample(f, [minX,maxX], step adaptif) + map transform
- [ ] Formatter:
  - [ ] prettyLine(A,B,C) ke "Ax + By + C = 0" dan "y = mx + b" (jika B ≠ 0)
  - [ ] prettyFunctionTranslation(f(x), dx, dy)
  - [ ] Parametrik/implisit untuk transformasi non-translasi

3) Glue UI + Desmos (js/geo-transform.js)
- [ ] Inisialisasi Desmos.Calculator (tema light, grid on, bounds default)
- [ ] Binding kontrol UI (input/slider/toggle) dengan live update
- [ ] Rendering:
  - [ ] Titik: asal & bayangan sebagai table/list (warna berbeda)
  - [ ] Garis: latex "y = m x + b" atau "x = c"; hasil transform reproduksi koefisien lalu latex
  - [ ] Fungsi: 
    - [ ] Asal: latex "y = f(x)" (math.js -> latex sederhana)
    - [ ] Translasi: latex "y = f(x - dx) + dy"
    - [ ] Lainnya: sampling -> table (x[], y[]) untuk bayangan
- [ ] Toggle tampilkan asal/bayangan dengan show/hide expression
- [ ] Hasil simbolik: update panel teks; pembulatan 2 desimal
- [ ] Undo (1 langkah) dan Reset state default
- [ ] Validasi input & pesan error (helper)

4) Integrasi Navigasi
- [ ] index.html: tambah kartu fitur "Kalkulator Transformasi Geometri" -> features/geo-transform.html
- [ ] components.js:
  - [ ] Tambahkan option pada dropdown fitur
  - [ ] Preselect ketika di /features/geo-transform.html

5) QA & Penyesuaian
- [ ] Uji setiap jenis objek + masing-masing transformasi
- [ ] Performa: sampling adaptif dan batas maksimal
- [ ] Responsif UI (mobile/desktop)
- [ ] Konsistensi tema (light default, dark tetap berfungsi di seluruh situs)

## Catatan Implementasi
- Koef garis (A,B,C) dinormalisasi untuk stabilitas (opsional: skala sehingga sqrt(A^2+B^2)=1).
- Refleksi umum y=mx+b -> koef (m, -1, b) -> normalisasi ke Ax+By+C=0 (A=m, B=-1, C=b).
- Parametrik fungsi (rotasi/dilatasi/refleksi): gunakan parameter t pada domain; tampilkan teks:
  - x'(t) = cx + k( cosθ (t - cx) - sinθ (f(t) - cy) ) (contoh kombinasi rotasi+dilatasi)
  - y'(t) = cy + k( sinθ (t - cx) + cosθ (f(t) - cy) )
- Slider default:
  - dx, dy ∈ [-10, 10]
  - θ ∈ [-180°, 180°]
  - k ∈ [-5, 5], step 0.1
  - cx, cy ∈ [-10, 10]
  - m ∈ [-10, 10], b ∈ [-20, 20]

## Cara Uji Lokal
- Buka index.html, navigasi ke Kalkulator Transformasi Geometri.
- Coba:
  - Titik: masukkan beberapa titik; ubah dx,dy; coba rotasi/refleksi/dilatasi.
  - Garis: uji format slope dan umum; cek hasil simbolik setelah translasi/rotasi/dilatasi/refleksi.
  - Fungsi: masukkan f(x)=x^2, sin(x), dsb; translasi (simbolik) dan rotasi/dilatasi (sampling).
- Perhatikan performa pada domain lebar; sesuaikan langkah sampling bila perlu.
