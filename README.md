
## Daftar Isi
- Ringkasan
- Fitur
- Struktur proyek (singkat)
- Cara menjalankan secara lokal
- API yang tersedia (ringkasan)
- Cara menggunakan fitur-fitur di halaman
- Troubleshooting singkat
- Kontribusi & Lisensi

## Ringkasan
Proyek ini adalah kumpulan demo dan utilitas web sederhana yang terdiri dari bagian frontend (HTML/JS/CSS) dan backend kecil berbasis Flask. Beberapa fitur yang tersedia: pemeriksa kata KBBI, downloader YouTube sederhana, demo enkripsi AES-GCM, transformasi/konversi koordinat, dan aplikasi perpustakaan (CRUD sederhana).

README ini menjelaskan apa saja fitur yang tersedia, file penting, dan cara menjalankan proyek di komputer Anda.

## Fitur
- KBBI Checker: mencari arti/keterangan kata (lokal) dari data yang ada di `backend/data/`.
- YouTube downloader (demo): antarmuka untuk mengunduh video/audio dengan backend `ytdl`.
- AES-GCM demo: contoh enkripsi dan dekripsi AES-GCM di halaman `features/aes-gcm.html`.
- Geo transform: alat transformasi koordinat / perhitungan geometri di `features/geo-transform.html`.
- Perpustakaan: demo aplikasi perpustakaan sederhana untuk manajemen buku (frontend + backend helper) di `features/perpustakaan.html`.

Catatan: semua fitur bersifat demonstrasi/pendukung. Beberapa fungsi (mis. downloader) menggunakan utilitas backend dan file data lokal.

## Struktur proyek (ringkas)
- `index.html` - Halaman utama
- `script.js`, `styles.css`, `components.js` - Berisi logika dan styling frontend umum
- `features/` - Halaman demo untuk fitur-fitur spesifik (`kbbi-checker.html`, `ytdl.js`, dll.)
- `js/` - Skrip JavaScript terpisah sesuai fitur
- `backend/flask-app/` - Aplikasi Flask dan API
  - `app.py` - titik masuk server Flask
  - `requirements.txt` - daftar dependensi Python
  - `api/` - modul API (mis. `kbbi.py`, `ytdl.py`, `library.py`, `health.py`)
- `backend/data/` - sample data dan berkas pendukung

## Cara menjalankan (lokal)
Petunjuk singkat untuk menjalankan backend Flask dan membuka frontend di browser (Windows PowerShell):

1) Siapkan Python environment (disarankan Python 3.8+)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2) Instal dependensi backend

```powershell
pip install -r backend/flask-app/requirements.txt
```

3) Jalankan server Flask

```powershell
python backend/flask-app/app.py
# atau jika app.py menggunakan flask CLI: set FLASK_APP=backend/flask-app/app.py; flask run
```

4) Buka frontend

- Buka `index.html` langsung di browser (file://) untuk demo statis.
- Untuk fitur yang butuh backend (mis. KBBI Checker atau YTDL), buka `index.html` atau halaman spesifik di folder `features/` setelah server backend berjalan. Pastikan URL API di file JS menunjuk ke alamat server (default: http://127.0.0.1:5000).

Contoh: buka `features/kbbi-checker.html` di browser, masukkan kata, lalu klik cari — frontend akan memanggil API backend.

## API (ringkasan)
Backend menyediakan beberapa endpoint helper di `backend/flask-app/api/`.

- `/api/health` — Cek status server.
- `/api/kbbi` — Pencarian kata KBBI (parameter query seperti `?word=...`).
- `/api/ytdl` — Endpoint untuk mengunduh video/audio dari URL (gunakan dengan bijak dan sesuai ketentuan layanan).
- `/api/library` — Endpoint terkait fungsi perpustakaan (baca/ubah daftar buku, tergantung implementasi).

Contoh panggilan menggunakan PowerShell:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/health"
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/kbbi?word=rumah"
```

Atau dengan curl:

```powershell
curl "http://127.0.0.1:5000/api/kbbi?word=rumah"
```

## Cara menggunakan fitur penting
- KBBI Checker: buka `features/kbbi-checker.html`. Masukkan kata yang ingin dicari. Hasil akan diambil dari data lokal melalui API.
- YouTube Downloader: buka `features/youtube-downloader.html` atau `features/ytdl.html` (jika ada). Tempel URL video, pilih format (jika tersedia), lalu klik unduh. File hasil disimpan di folder `backend/flask-app/downloads` atau sesuai konfigurasi backend.
- AES-GCM demo: buka `features/aes-gcm.html` untuk mencoba enkripsi/dekripsi singkat.
- Perpustakaan: buka `features/perpustakaan.html` untuk melihat antarmuka CRUD buku; beberapa operasi mungkin memerlukan backend.

## Troubleshooting singkat
- Server tidak jalan: pastikan virtual environment aktif dan semua dependensi terinstal.
- Endpoint tidak merespon: periksa URL di file JS, dan lihat log terminal tempat Flask berjalan.
- Masalah CORS: jika frontend dijalankan via file:// dan backend via http://, periksa konfigurasi CORS di backend (module `flask_cors` mungkin perlu diaktifkan).

## Note
- project ini saya buat dengan bantuan AI
