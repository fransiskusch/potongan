# Auto Clipper Cloud v2 — Colab T4 + Drive + Vercel + Face Tracking Modern

Tanggal: 2025-11-15
Status: Approved (design review bersama user)
Evolusi dari: `docs/cloud-architecture-plan.md` (arsitektur Vercel + Colab versi awal)

## Ringkasan

Dua workstream dalam satu spec (urutan implementasi sesuai prioritas user):

1. **Workstream A — Alur Colab T4 + Drive + UI Hosted (PRIORITAS 1):** Perbaiki alur
   Colab yang sudah ada: kerja di disk lokal Colab (cepat), hasil final + DB di Google
   Drive (persisten), tambah upload chunked di web UI, deploy UI ke Vercel, dan
   ganti domain ke `fransiskus.my.id`.
2. **Workstream B — Face Tracking Modern (PRIORITAS 2):** Ganti Haar Cascade dengan
   MediaPipe Face Detection di Colab + algoritma Dominant Face Lock untuk mengunci
   satu orang dominan, memperbaiki tiga keluhan: crop patah-patah/goyang, salah
   pilih orang (multi-orang), wajah terpotong.

### Keputusan user (dari sesi brainstorming)

| Keputusan | Pilihan |
|---|---|
| Gejala face tracking terburuk | Crop goyang, salah pilih orang, wajah terpotong (ketiganya) |
| Alur yang diinginkan | UI hosted + backend Colab |
| Dukungan desktop | Fokus Colab; desktop tetap jalan dengan Haar (fallback) |
| Multi-orang | Kunci 1 orang dominan (face recognition-lite via tracking) |
| Prioritas | Colab/Drive dulu, face tracking menyusul |
| Tunnel | Tetap Cloudflare (README lama menyebut NGROK — usang, akan dirapikan) |
| Input video lokal | Upload langsung di web UI (chunked) + browser Drive |
| File > 100MB (batas Cloudflare) | Chunked upload (20MB per chunk) |
| Hosting UI | Vercel |
| Domain frontend | `clip.fransiskus.my.id` |
| Domain backend (tunnel) | `be-clipper.fransiskus.my.id` |
| Detektor wajah Colab | MediaPipe Face Detection (BlazeFace), lisensi Apache-2.0 |

---

## Workstream A — Arsitektur & Alur Colab

### Arsitektur target

```
[Browser — di mana saja]
   https://clip.fransiskus.my.id      (UI statis Vercel, gratis)
        │ fetch API + Bearer token
        ▼
[Cloudflare Tunnel] be-clipper.fransiskus.my.id
        ▼
[Google Colab T4 GPU]
   ├─ backend FastAPI (backend/colab_api.py)   ← clone dari GitHub tiap sesi
   ├─ /content/uploads        ← chunked upload dari browser (disk lokal)
   ├─ /content/projects       ← working dir: download YT, render (disk lokal)
   └─ /content/drive/MyDrive/AutoClipperData
        ├─ history.db          ← DB riwayat (persisten)
        └─ projects/<judul>/   ← HANYA hasil final: clips/ + subtitles/
```

### Prinsip utama: disk lokal untuk kerja, Drive untuk hasil

Masalah saat ini: `AUTO_CLIPPER_WORKSPACE` di Colab menunjuk ke mount Drive
(`/content/drive/MyDrive/AutoClipperData`) dan dipakai untuk SEMUA aktivitas —
download YouTube, file sementara, render FFmpeg. I/O Drive via FUSE ~10x lebih
lambat dari disk lokal Colab dan boros kuota Drive.

Perilaku baru:

1. Sesi Colab dimulai → notebook assert GPU T4 → clone repo → install deps →
   mount Drive → cek kesehatan tunnel → jalankan backend.
2. Job masuk (link YT / upload chunked / file Drive) → semua pemrosesan di
   `/content/projects/` (disk lokal).
   - Pengecualian: sumber dari browser Drive (`local:/content/drive/...`) tetap
     dibaca langsung dari Drive (tidak diduplikasi).
3. Job selesai → hanya `clips/` + `subtitles/` + `history.db` yang disalin ke
   Drive (`projects/<judul>/`), file sumber & temp dibersihkan dari disk lokal.
   **Semua path absolut yang tersimpan di DB** (`job["clips"][*]["path"]`,
   `metadata.source_video`, `metadata.subtitle_path`) **ditulis ulang ke path
   Drive** sebelum `save_history` — agar preview video (`GET /video`) dan
   resume/rerender tetap berfungsi di sesi Colab berikutnya.
4. Session Colab mati → disk lokal hilang, hasil + riwayat aman di Drive.

### Perubahan kode Workstream A

| Komponen | Perubahan |
|---|---|
| `backend/colab_api.py` | Set `AUTO_CLIPPER_LOCAL_WORKDIR=/content/projects` (kerja) + `AUTO_CLIPPER_WORKSPACE` tetap Drive (DB). Assert T4, cek tunnel sehat sebelum start, auto-cleanup disk saat start. |
| `backend/db.py` `get_app_data_dir()` | Prioritas: `AUTO_CLIPPER_LOCAL_WORKDIR` → `AUTO_CLIPPER_WORKSPACE` → default OS. Catatan: `history.db` harus tetap di Drive — DB path di-resolve dari `AUTO_CLIPPER_WORKSPACE` secara eksplisit, bukan dari `get_app_data_dir()`. |
| `backend/jobs.py` `get_project_workspace()` | Di cloud mode: buat workspace proyek di local workdir; saat job selesai (`_finalize_job`), salin `clips/` + `subtitles/` ke folder Drive yang sama, lalu hapus file source/temp lokal. |
| `backend/jobs.py` `_finalize_job()` | **Penulisan ulang path:** sebelum `save_history`, di cloud mode semua path absolut di `job["clips"][*]["path"]` dan `metadata.source_video`/`metadata.subtitle_path` yang menunjuk local workdir ditulis ulang ke path Drive yang sesuai. Tanpa ini, preview `GET /video` dan fitur resume/rerender rusak setelah session Colab restart (path lokal mati). |
| `backend/main.py` `POST /upload` | Cloud mode → simpan ke `/content/uploads` (disk lokal). Desktop: perilaku lama. |
| `backend/main.py` CORS | Daftar origin pindah ke env var `AUTO_CLIPPER_ALLOWED_ORIGINS` (comma-separated, dibaca saat startup). Regex lama tetap jadi default bila env kosong. Tambah `clip.fransiskus.my.id` & domain Vercel ke default. |
| `web/src/api.ts` | Default `API_URL` hardcode diganti `https://be-clipper.fransiskus.my.id` (fallback bila `VITE_API_URL` tidak diset). |
| `web/src/components/Steps/StepInput.tsx` | Tab input 3 mode: **Link** (URL — perilaku sekarang) · **Upload** (file picker + drag-drop + progress bar chunked) · **Drive** (modal browser Drive yang sudah ada). |
| `Auto_Clipper_Colab.ipynb` | Sel baru: (1) verifikasi runtime T4 GPU dengan pesan error jelas bila bukan; (2) form field Cloudflare token + API token + allowed origins; (3) cek kesehatan tunnel (GET /health via tunnel URL); (4) sel cleanup disk opsional. |
| `README.md` | Opsi 5 ditulis ulang: Cloudflare (bukan NGROK), alur upload chunked + browser Drive + domain baru. |
| `docs/cloud-architecture-plan.md` | Domain lama diganti domain baru; tambahkan bagian upload chunked & workspace terpisah (atau tandai sebagai superseded oleh spec ini). |

### Chunked upload (endpoint baru)

```
Browser                                   Backend Colab
────────                                  ─────────────
POST /upload/init  {filename, size}  →    validasi (ekstensi video, sisa disk
                                         ≥ size + 5GB buffer), buat upload_id
                                    ←    {upload_id, chunk_size: 20971520}
POST /upload/chunk/{id}/{n}          →    append binary ke /content/uploads/.parts/<id>/
POST /upload/complete/{id}           →    gabung parts → file final → validasi
                                         total size → hapus parts
                                    ←    {url: "local:/content/uploads/<file>"}
GET  /upload/status/{id}             →    daftar chunk sudah diterima (untuk
                                    ←    progress bar & retry yang hilang)
```

- Chunk size 20MB (aman di bawah batas body Cloudflare ~100MB).
- `upload_id` UUID4; tiap chunk ditulis sebagai file terpisah
  `.parts/<id>/<n>`; saat `complete`, semua part digabung dengan streaming
  copy berurutan ke file final, lalu direktori `.parts/<id>/` dihapus.
- Upload tidak diselesaikan >24 jam dibersihkan otomatis saat sesi Colab start.
- Nama file disanitasi (hanya `[A-Za-z0-9._-]`); ekstensi diizinkan:
  `.mp4 .mkv .mov .webm .avi .m4v .ts`.
- Semua endpoint upload dilindungi middleware Bearer token yang sudah ada.
- Endpoint `POST /upload` lama tetap ada (kompatibilitas desktop Tauri), di
  cloud mode dialihkan ke disk lokal.
- Client-side: `XMLHttpRequest` untuk upload progress event; retry otomatis
  3x per chunk dengan exponential backoff; validasi ekstensi + ukuran
  maksimal 30GB sebelum mulai.

### Deploy Vercel

1. Import repo, Root Directory `web/`, Framework Vite, Build `npm run build`,
   Output `dist/`.
2. Env var: `VITE_API_URL=https://be-clipper.fransiskus.my.id`.
3. Custom domain: `clip.fransiskus.my.id` (CNAME ke `cname.vercel-dns.com`).
4. Cloudflare tunnel diperbarui di akun Cloudflare user: public hostname
   `be-clipper.fransiskus.my.id` → `http://localhost:8000`.

---

## Workstream B — Face Tracking Modern

### Akar masalah (Haar Cascade)

`backend/crop_utils.py` memakai Haar Cascade (2001) untuk
`sample_face_trajectory` / `detect_video_layout`:

1. **Goyang/patah-patah** — Haar sering gagal deteksi (wajah menyamping,
   gelap, kecil) → trajectory bolong → lompatan setelah forward-fill.
2. **Salah orang** — kode mengambil wajah terbesar per frame tanpa identitas →
   kalau orang lain lebih dekat kamera, crop pindah ke orang salah.
3. **Wajah terpotong** — false positive Haar membuat median position meleset.

### Solusi

**Detektor: MediaPipe Face Detection (BlazeFace short-range)** — akurasi jauh
di atas Haar, robust terhadap pose/pencahayaan, pip install langsung jalan di
Colab/Linux, CPU saja sudah real-time (GPU Colab tetap untuk Whisper),
Apache-2.0.

**Algoritma Dominant Face Lock:**

```
1. SCAN AWAL (~10 frame tersebar di window):
   deteksi semua wajah + skor.
2. PILIH TARGET: wajah dengan skor tertinggi:
   score = Σ (kehadiran antar frame × ukuran × kedekatan posisi antar-frame).
   Wajah yang konsisten muncul + dominan = target.
3. TRACKING (tiap 0.25s): deteksi semua wajah → pilih deteksi dengan jarak
   centroid terkecil ke posisi target terakhir (gating: maks 25% lebar frame)
   → update posisi target.
   - Target hilang ≤ 5 detik → TAHAN posisi terakhir (hold).
   - Hilang > 5 detik tapi wajah lain muncul di posisi serupa (IoU ≥ 0.3) →
     lanjutkan track wajah itu (orang sama kemungkinan besar, mis. wajah
     kembali terdeteksi setelah menyamping).
   - Hilang > 15 detik → re-scan penuh (pilih target baru).
4. SMOOTHING: One-Euro filter (alpha dinamis: nyaris nol jitter saat diam,
   responsif saat gerak cepat) → deadband 0.08 (dipertahankan dari kode lama)
   → clamp in-frame.
5. OUTPUT: list[(t, x)] — format identik dengan trajectory lama →
   `build_dynamic_crop_filter` & BST lerp FFmpeg dipakai ulang tanpa perubahan.
```

### Integrasi & kompatibilitas

- **Modul baru `backend/face_tracker.py`** — semua logika deteksi+tracking
  terisolasi di satu file. Public API:
  - `sample_face_trajectory(video_path, start, end, interval=0.25, should_cancel)`
    → `list[(t, x)]` (drop-in replacement untuk fungsi lama di crop_utils).
  - `detect_video_layout(video_path, ...)` → dict sama dengan fungsi lama
    (mode gaming/standard, face_box, face_center, face_area_ratio).
  - Selector detektor internal: MediaPipe bila tersedia; fallback Haar
    (import modul lama sebagai fallback path).
- **`crop_utils.py`**: `sample_face_trajectory` & `detect_video_layout` di
  crop_utils didelegasikan ke face_tracker (atau dipindahkan). Interface
  pemanggil di `jobs.py` tidak berubah.
- **Cloud (Colab)**: `mediapipe` ditambahkan ke requirements Colab
  (install di notebook), aktif otomatis.
- **Desktop**: tanpa mediapipe → jalur Haar lama tetap utuh (fokus Colab,
  desktop tidak dirusak).
- Interval sampling 0.5s → 0.25s di cloud (trajectory lebih rapat, pan halus).

### Error handling

- MediaPipe gagal load di awal job → fallback per-job ke Haar, log warning.
- MediaPipe crash/error per frame → frame dianggap "tidak ada deteksi"
  (hold logic menangani), tidak crash job.
- Video tanpa wajah → fallback center 0.5 (perilaku lama).
- `should_cancel` tetap dicek di setiap iterasi sampling (perilaku lama).

### Testing

- **Unit test `face_tracker`** dengan mock detector:
  - Dua wajah sintetis, satu dominan → trajectory tetap mengikuti wajah
    dominan meski wajah kedua lebih besar di beberapa frame.
  - Wajah hilang 3 detik → posisi hold, tidak lompat.
  - One-Euro filter: output monotonic saat input jitter kecil; responsif
    saat input bergerak cepat.
  - Clamp: trajectory tidak pernah keluar batas [lo, hi].
  - Output format identik dengan konsumen lama (`build_dynamic_crop_filter`).
- **Test regresi**: unit test crop_utils lama tetap lulus (interface tidak
  berubah).
- **Test manual di Colab**: video 2 orang berbicara, video wajah menyamping,
  video gaming facecam corner, video gelap.

---

## Urutan implementasi

1. **Fase 1 (Workstream A):** workspace terpisah local vs Drive + sinkronisasi
   hasil + CORS env var + domain baru + notebook assert T4 + README.
2. **Fase 2 (Workstream A):** chunked upload backend + tab Upload di web UI.
3. **Fase 3 (Workstream B):** `face_tracker.py` MediaPipe + Dominant Face Lock
   + integrasi crop_utils + tests.
4. **Fase 4:** deploy Vercel + verifikasi end-to-end dari browser.

## Out of scope

- Mode bicara aktif (lip-sync / active speaker detection) — ditunda.
- Ganti detektor desktop (desktop tetap Haar).
- Upload persisten ke Drive (file upload hanya di disk lokal Colab, hilang
  saat session mati — hasil klip tetap disalin ke Drive).
- Multi-user / autentikasi lanjutan (tetap single static token).
