# Web AI Engine Selection + Drive Search + Source Sync + Telegram Notif + Face Tracking — Design Spec

**Tanggal:** 2026-08-25
**Status:** Approved (design approved per-section by user)
**Terkait:** `docs/superpowers/specs/2025-11-15-colab-t4-drive-vercel-face-tracking-design.md` (Workstream A, B & C — Workstream B digabung ke sini)

## Latar Belakang

Backend Potongan.id di Colab sudah memiliki paritas penuh dengan desktop
(pipeline yang sama: faster-whisper transkripsi → LLM pilih highlight →
ffmpeg render). Backend juga sudah mendukung pilihan provider AI lengkap
(openai, gemini, deepseek, groq, openrouter, xai, mistral, custom
OpenAI-compatible, manual_ai), pemilihan model per provider, fetch daftar
model (`/api/providers/models`), dan test key (`/api/settings/test-ai`).

Namun UI web (Vercel) saat ini:

1. Meng-hardcode `provider: "manual"` di StepInput — pengguna tidak bisa
   memakai AI otomatis (mis. gateway 9router milik pengguna) dari web;
   hanya mode copy-paste prompt manual.
2. Hanya bisa browse folder Drive per folder — tidak ada pencarian video.
3. Video sumber hasil download tidak disimpan ke Drive — hilang saat
   session mati, dan path history menunjuk path Drive yang tidak ada
   (re-render dari history gagal setelah session restart).
4. Tidak ada notifikasi saat job selesai di luar web (user harus
   memantau polling web).

Tujuan spec ini: (1) expose pemilihan AI provider/model/API key di web UI
(mirror dari Settings desktop), (2) tambah search video di Google Drive,
(3) opsi simpan video sumber ke Drive, (4) notifikasi Telegram saat job
selesai/gagal beserta link unduh klip.

## Keputusan Pengguna

- "9router" = gateway AI OpenAI-compatible milik pengguna (mirip
  OpenRouter/livrouter) → masuk lewat provider `custom` dengan
  `custom_base_url`.
- Manajemen key: **full auto seperti desktop** — key diisi di web,
  disimpan di localStorage browser, dikirim per-request ke backend.
- Pilihan provider di web: **dropdown lengkap** (registry sama dengan
  desktop).
- Drive search: **search rekursif sisi backend** (scan nama file via
  os.walk di Drive yang sudah ter-mount).
- Pendekatan UI: **Opsi B — Settings modal terpusat** + chip ringkasan di
  StepInput + search bar di modal Drive.
- Wizard: **adaptif per mode** — 3 step (mode AI otomatis) / 4 step
  (mode manual); JSON highlight AI tidak pernah muncul ke pengguna di
  mode otomatis.
- Simpan source ke Drive: **toggle per-job di web, default ON**.
- Notif Telegram: **teks + link unduh** (tanpa file terlampir), dikirim
  **hanya saat DONE/ERROR**, konfigurasi via **form notebook Colab**
  (env var), bukan web UI.
- Face tracking: **digabung dari spec besar (Workstream B / Fase 3)** —
  MediaPipe + Dominant Face Lock, **tanpa setting user-facing baru**
  (kualitas naik via default yang lebih baik).

## 1. AI Engine Selection (Settings Modal)

### Komponen baru: `web/src/components/AISettingsModal.tsx`

Dibuka lewat gear icon di header web (sebelah tombol History). Meniru
flow Settings desktop (`src/components/settings/ProviderSection.tsx`):

- **Dropdown Provider**: OpenAI, Gemini, DeepSeek, Groq, OpenRouter, xAI,
  Mistral, Custom (gateway 9router), Manual (copy-paste prompt).
- **Registry provider di-porting**: salin `src/lib/providers.ts` ke
  `web/src/lib/providers.ts` (TypeScript murni, tanpa dependensi React)
  supaya desktop & web punya registry identik. Perubahan provider baru
  cukup dilakukan di dua file yang identik (porting manual, tanpa build
  shared package — menjaga kedua app tetap build-able terpisah).
- **API Key input** per provider (password field + toggle show/hide).
  Disimpan di localStorage key `ac_api_keys` (JSON
  `{provider: key}`) — format sama dengan desktop.
- **Custom gateway fields** (hanya jika provider = Custom): Base URL,
  Model Name, tombol **Fetch Models** → `POST /api/providers/models`.
- **Model dropdown**: opsi fallback dari `fallbackModels` registry +
  hasil fetch. Default = `defaultModel` provider.
- **Tombol Test Key** → `POST /api/settings/test-ai`. Sukses → pesan
  sukses inline (teks hijau) di dalam modal; gagal → pesan error inline
  (teks merah) dengan pesan error backend. Web belum punya sistem toast,
  jadi feedback ditampilkan inline di modal (sederhana, tanpa
  menambah-sistem baru).

### Perubahan StepInput (`web/src/components/Steps/StepInput.tsx`)

- Chip ringkasan: `🤖 AI Engine: Custom · gpt-4o-mini` — klik membuka
  AISettingsModal.
- Saat submit, payload berubah dari hardcode `provider: "manual"`
  menjadi `{provider, api_key, model, custom_base_url,
  custom_model_name}` dari settings.
- Provider = Manual → flow lama tetap berjalan (transkrip → prompt →
  paste JSON → render).

### State baru

- localStorage: `ac_provider`, `ac_model`, `ac_api_keys` (identik dengan
  desktop sehingga perilaku yang sudah dikenal dipertahankan).
- `AISettingsContext` (React context kecil di `web/src`) supaya chip
  StepInput & modal share state tanpa prop-drilling.

### Error handling

- Backend `POST /jobs` sudah memanggil `ping_provider` sebelum job dibuat
  (fail-fast). Pesan error ping ditampilkan di web pada Step 1 lewat
  state `error` `useJobPolling` yang sudah ada.
- Key kosong untuk provider non-custom/non-manual → pesan "API Key
  kosong, buka Settings" saat submit (validasi sisi web).
- Custom tanpa base URL/model name → `ping_provider` backend sudah
  melempar "Custom provider requires a Base URL and Model Name."

## 2. Drive Search

### Backend: endpoint baru `GET /gdrive-search?q=<query>`

Di `backend/main.py`, mengikuti pola `/gdrive-browser`:

- Guard Cloud Mode sama seperti `/gdrive-browser`.
- `q` bebas (contoh: "podcast", "vlog jakarta"). Walk rekursif dari
  `/content/drive/MyDrive` via `os.walk`, filter file video (`.mp4`,
  `.mov`, `.mkv`, `.webm`), cocokkan `q` ke nama file case-insensitive
  (substring).
- Batas: maksimum **100 hasil** + guard waktu **10 detik**.
- Response: `{status, results: [{name, path}], truncated: bool}` —
  `truncated: true` jika terpotong karena limit/waktu. Tanpa `is_dir`
  karena hanya file video yang dicari.

### Frontend: search bar di `GDriveBrowserModal`

- Input search + tombol cari di bagian atas modal.
- Submit → `apiSearchGDrive(q)` baru di `web/src/api.ts`.
- Hasil search menggantikan list folder sementara; klik hasil →
  `onSelectFile(item.path)` (sama seperti klik file video sekarang →
  `url = local:<path>`).
- Tombol X clear search → kembali ke mode browse.
- Empty state: "Tidak ada video yang cocok dengan '<q>'".

### Error handling

- Drive belum ter-mount → error backend ditampilkan di modal.
- Query kosong → tidak fetch; kembali ke browse.
- `truncated: true` → tampil note kecil "Menampilkan 100 hasil pertama".

## 3. Data Flow & Status Flow

```
Browser (Vercel)                          Colab Backend
─────────────────                         ─────────────
StepInput submit
  provider=openai|gemini|custom(9router)
  + api_key + model + custom_base_url
  → POST /jobs ─────────────────────────→ ping_provider (fail-fast)
                                          → create_job (thread)
                                          → whisper GPU transkrip
                                          → LLM pilih highlights
                                          → ffmpeg render clips
  ← poll GET /jobs/{id} (1.8s) ←──────── status/progress/clips
StepResult tampilkan clips + download
```

### Wizard adaptif per mode (keputusan review)

Navigasi wizard dihitung dari mode job (bukan lagi fixed 4 step):

- **Mode AI otomatis** (provider bukan manual): 3 step —
  `Input & Style` → `AI Processing` → `Render & Download`.
  - Step 2 ("AI Processing") menampilkan progress live sesuai status
    backend: mendownload video / transkripsi Whisper / "AI memilih
    highlight via <provider>…" / merender klip N dari M.
  - JSON highlight dari AI **tidak pernah muncul ke pengguna** — backend
    langsung mengonsumsinya dan lanjut render tanpa henti.
  - Implementasi: `STEPS_CONFIG` di `web/src/App.tsx` menjadi fungsi
    `getSteps(mode)`; logika auto-sync step yang sudah ada
    (baris 84-96) memetakan status → step untuk 3-step layout
    (TRANSCRIBING/CROPPING/DONE → step "AI Processing" lalu
    "Render & Download").
- **Mode Manual** (provider = manual): 4 step seperti sekarang — tidak
  berubah (Step 2 prompt → Step 3 paste JSON → Step 4 render).

Opsi yang dipertimbangkan dan ditolak: (1) wizard tetap 4 step dan mode
auto melewati Step 3 — ditolak karena step "hantu" membingungkan;
(3) review highlight sebelum render dengan status backend baru — ditolak
karena menambah interaksi manual padahal tujuan mode auto adalah
hands-free (bisa jadi fitur masa depan terpisah).

## 4. Testing (AI selection & Drive search)

- **Backend unit test** `backend/tests/test_gdrive_search.py`:
  tmp_path berisi file dummy (.mp4/.txt) + folder nested; assert filter
  ekstensi, case-insensitive match, limit 100, flag truncated, guard
  Cloud Mode.
- **Regresi**: test `/jobs` dengan provider `manual_ai` tetap hijau.
- **Frontend**: `npm run build` sukses; smoke test manual — pilih Custom
  → isi base URL 9router → Fetch Models → Test Key → buat job dengan
  video pendek dari Drive → klip selesai.
- **Wizard adaptif**: verifikasi mode manual masih 4 step (regresi), dan
  mode AI menampilkan 3 step dengan progress yang benar (unit logika
  `getSteps(mode)` + pemetaan status→step bila di-test via component
  test ringan atau smoke test manual).
- Tidak ada perubahan pipeline render/subtitle → tidak perlu test
  tambahan untuk crop/subtitle.

## 5. Simpan Video Sumber ke Drive

### Latar

Fase 1 (by design) hanya menyinkronkan `clips/` + `subtitles/` ke Drive;
video sumber tetap di disk Colab dan hilang saat session mati. Namun
`_finalize_job` me-rewrite path `source_video` di metadata ke path Drive
— file yang tidak pernah disalin — sehingga re-render dari history gagal
setelah session mati ("Video sumber tidak ditemukan"). Fitur ini
sekaligus menutup gap tersebut.

### Perubahan

- **Web Step 1**: checkbox baru **"Simpan video sumber ke Drive"**
  (default **ON**) → field `save_source_to_drive: bool = true` di
  payload `POST /jobs` (Pydantic `CreateJobRequest` + model job).
- **Backend** `cloud_sync.py`: fungsi baru
  `sync_source_to_persistent(local_project_dir)` — salin
  `source/source_video.mp4` ke
  `Drive/AutoClipperData/projects/<judul>/source/source_video.mp4`.
- **`_finalize_job`** (jobs.py): setelah sync clips/subtitles, jika
  `save_source_to_drive` → sync source. Path rewrite `source_video`
  kini menunjuk file yang benar-benar ada di Drive → re-render dari
  history tetap berfungsi setelah session restart (untuk job dengan
  toggle ON).
- **Sumber `local:` (upload/Drive picker)**: tidak diduplikasi — file
  sudah berada di sisi user/Drive; path rewrite cukup.
- **Error handling**: gagal copy (mis. Drive penuh) → `log_error`, job
  tetap DONE, notif Telegram menyertakan peringatan "source video
  tidak tersimpan ke Drive".

## 6. Notifikasi Telegram

### Modul baru: `backend/notifier.py`

Satu tanggung jawab: mengirim pesan Telegram (best-effort).

- `send_telegram_message(text, bot_token, chat_id)` — POST
  `https://api.telegram.org/bot<token>/sendMessage`.
- `notify_job_finished(job_id, status, job, metadata)` — format pesan
  + kirim; dipanggil dari `_finalize_job` saat status `DONE` atau
  `ERROR` (bukan CANCELLED/AWAITING_MANUAL), dijalankan di thread
  terpisah agar tidak memperlambat finalize.

### Aktivasi via form notebook Colab (sel 6)

- Form field baru `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (default
  kosong = notif off).
- `colab_api.py` men-set env `AUTO_CLIPPER_TELEGRAM_BOT_TOKEN` +
  `AUTO_CLIPPER_TELEGRAM_CHAT_ID`; `notifier.py` membaca env tersebut.
- User membuat bot via @BotFather dan mengambil chat ID via
  @userinfobot (dokumentasi singkat ditambahkan ke README).

### Format pesan (teks + link unduh, tanpa file terlampir)

```
🎬 Potongan.id — Job Selesai
📌 Judul: <judul proyek>
✅ Status: DONE  (atau ❌ ERROR: <pesan singkat>)
🎞 Klip: 5 berhasil, 0 gagal
⏱ Durasi proses: 12 menit

📥 Unduh klip:
1. Judul_clip_1.mp4 — https://be-clipper.fransiskus.my.id/video?path=...&v=...
2. ...

⏳ Link aktif selama backend Colab menyala.
```

- Link = URL endpoint `/video` backend yang sudah ada (dipakai web
  player) — diklik di Telegram langsung play/unduh.
- Base URL tunnel dibaca dari env `AUTO_CLIPPER_PUBLIC_BASE_URL`
  (di-set form Colab, default
  `https://be-clipper.fransiskus.my.id`).

### Error handling

- Token/chat ID kosong → notif off, tanpa error.
- Kirim gagal (token salah, jaringan) → `log_error`, tidak
  menggagalkan job (best-effort).
- Pesan > 4096 karakter → dipotong + "…dan N klip lainnya, buka web
  untuk melihat semua".
- Pesan menyatakan eksplisit bahwa link unduh hanya berlaku selama
  session Colab aktif.

## 7. Testing (source sync & notifier)

- **Unit test** `backend/tests/test_notifier.py` (mock `requests.post`):
  sukses kirim, token kosong (tidak kirim), error jaringan (tidak
  raise), pesan panjang (terpotong).
- **Unit test** `sync_source_to_persistent`: file tersalin ke path
  Drive yang benar; `save_source_to_drive=False` → tidak menyalin;
  sumber `local:` tidak diduplikasi.
- **Test integrasi ringan**: `_finalize_job` memanggil notifier saat
  DONE/ERROR dan tidak memanggil saat CANCELLED/AWAITING_MANUAL (mock).

## 8. Face Tracking Modern (MediaPipe + Dominant Face Lock)

> Port dari spec besar `2025-11-15-...` Workstream B / Fase 3 — sudah
> disetujui sebelumnya. Digabung ke spec ini agar dikerjakan dalam satu
> implementasi.

### Akar masalah (Haar Cascade)

`backend/crop_utils.py` memakai Haar Cascade untuk
`sample_face_trajectory` / `detect_video_layout`:

1. **Goyang/patah-patah** — Haar sering gagal deteksi (wajah menyamping,
   gelap, kecil) → trajectory bolong → lompatan setelah forward-fill.
2. **Salah orang** — kode mengambil wajah terbesar per frame tanpa
   identitas → crop pindah ke orang salah.
3. **Wajah terpotong** — false positive Haar membuat median position
   meleset.

### Solusi

**Detektor: MediaPipe Face Detection (BlazeFace short-range)** — akurasi
jauh di atas Haar, robust pose/pencahayaan, jalan di CPU Colab (GPU
tetap untuk Whisper), Apache-2.0.

**Algoritma Dominant Face Lock:**

1. SCAN AWAL (~10 frame tersebar): deteksi semua wajah + skor.
2. PILIH TARGET: wajah dengan skor konsistensi (kehadiran antar frame ×
   ukuran × kedekatan posisi) tertinggi.
3. TRACKING (tiap 0.25s): pilih deteksi dengan jarak centroid terkecil
   ke posisi target terakhir (gating maks 25% lebar frame).
   - Target hilang ≤ 5 detik → TAHAN posisi terakhir (hold).
   - Hilang > 5 detik + wajah serupa muncul (IoU ≥ 0.3) → lanjutkan
     track (orang sama).
   - Hilang > 15 detik → re-scan penuh (pilih target baru).
4. SMOOTHING: One-Euro filter (nol jitter saat diam, responsif saat
   gerak cepat) → deadband 0.08 (dipertahankan) → clamp in-frame.
5. OUTPUT: `list[(t, x)]` — format identik trajectory lama →
   `build_dynamic_crop_filter` & lerp FFmpeg dipakai ulang tanpa
   perubahan.

### Integrasi & kompatibilitas

- **Modul baru `backend/face_tracker.py`** — semua logika deteksi +
  tracking terisolasi. Public API drop-in:
  - `sample_face_trajectory(video_path, start, end, interval=0.25,
    should_cancel)` → `list[(t, x)]`
  - `detect_video_layout(video_path, ...)` → dict identik (mode
    gaming/standard, face_box, face_center, face_area_ratio)
  - Selector detektor internal: MediaPipe bila tersedia; fallback Haar.
- **`crop_utils.py`**: `sample_face_trajectory` & `detect_video_layout`
  didelegasikan ke `face_tracker`. Interface pemanggil di `jobs.py`
  tidak berubah.
- **Cloud (Colab)**: `mediapipe` ditambah ke requirements Colab
  (install di notebook), aktif otomatis.
- **Desktop**: tanpa mediapipe → jalur Haar lama tetap utuh (desktop
  tidak dirusak).
- Interval sampling 0.5s → 0.25s di cloud.

### Error handling

- MediaPipe gagal load di awal job → fallback per-job ke Haar, log
  warning.
- MediaPipe crash/error per frame → frame dianggap "tidak ada deteksi"
  (hold logic menangani), tidak crash job.
- Video tanpa wajah → fallback center 0.5 (perilaku lama).
- `should_cancel` tetap dicek tiap iterasi sampling.

### Testing

- **Unit test `face_tracker`** (mock detector): wajah dominan diikuti
  walau wajah kedua lebih besar di beberapa frame; hold saat hilang 3
  detik; One-Euro responsif; clamp in-frame; output format identik
  konsumen lama.
- **Test regresi**: unit test crop_utils lama tetap lulus (interface
  tidak berubah).
- **Test manual Colab**: video 2 orang, wajah menyamping, gaming
  facecam corner, video gelap.

## 9. Di Luar Scope

- Pipeline subtitle/highlight/render backend (sudah paritas desktop).
- Upload chunked (Fase 2 spec besar, tetap terpisah).
- Menyimpan API key di backend/Drive (ditolak: risiko key plaintext di
  Drive; localStorage cukup untuk single-user).
- Upload file klip sebagai attachment Telegram (ditolak: 20-80 MB per
  klip, upload lama dari Colab; link unduh cukup).
- Notifikasi per fase transkripsi/render (ditolak: berisik; hanya
  selesai/gagal sesuai keputusan user).
- Konfigurasi Telegram via web UI (ditolak untuk sekarang: form Colab
  cukup untuk single-user; token bot tidak perlu tersimpan di browser).
- Setting tracking user-facing (deadband/alpha slider) — ditolak:
  kualitas naik via default yang lebih baik, bukan slider teknis.

## Unit Interfaces (Ringkas)

| Unit | Tanggung jawab | Dependency |
| --- | --- | --- |
| `web/src/lib/providers.ts` | Registry provider (id, label, defaultModel, fallbackModels) | — |
| `web/src/components/AISettingsModal.tsx` | Pilih provider/key/model, fetch models, test key | providers.ts, api.ts |
| `AISettingsContext` | Share state provider/key/model ke StepInput | providers.ts |
| `getSteps(mode)` (App.tsx) | Hitung konfigurasi navigasi wizard per mode (3 step AI / 4 step manual) | — |
| `GET /gdrive-search` | Search file video rekursif di MyDrive | Cloud Mode + Drive mount |
| `apiSearchGDrive` | HTTP wrapper search Drive | api.ts |
| `sync_source_to_persistent` | Salin source_video.mp4 ke Drive saat diminta | cloud_sync.py, env cloud mode |
| `backend/notifier.py` | Format + kirim pesan Telegram (best-effort) | env token/chat ID, requests |
| `backend/face_tracker.py` | Deteksi + tracking wajah (MediaPipe/BlazeFace + Dominant Face Lock, fallback Haar) | mediapipe, crop_utils |
