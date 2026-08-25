# Web AI Engine Selection + Drive Search + Source Sync & Telegram Notif — Design Spec

**Tanggal:** 2026-08-25
**Status:** Approved (design approved per-section by user)
**Terkait:** `docs/superpowers/specs/2025-11-15-colab-t4-drive-vercel-face-tracking-design.md` (Workstream A & C)

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

## 4. Testing

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

## 6. Simpan Video Sumber ke Drive

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

## 7. Notifikasi Telegram

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

## 8. Testing (tambahan)

- **Unit test** `backend/tests/test_notifier.py` (mock `requests.post`):
  sukses kirim, token kosong (tidak kirim), error jaringan (tidak
  raise), pesan panjang (terpotong).
- **Unit test** `sync_source_to_persistent`: file tersalin ke path
  Drive yang benar; `save_source_to_drive=False` → tidak menyalin;
  sumber `local:` tidak diduplikasi.
- **Test integrasi ringan**: `_finalize_job` memanggil notifier saat
  DONE/ERROR dan tidak memanggil saat CANCELLED/AWAITING_MANUAL (mock).

## 9. Di Luar Scope (tambahan)

- Upload file klip sebagai attachment Telegram (ditolak: 20-80 MB per
  klip, upload lama dari Colab; link unduh cukup).
- Notifikasi per fase transkripsi/render (ditolak: berisik; hanya
  selesai/gagal sesuai keputusan user).
- Konfigurasi Telegram via web UI (ditolak untuk sekarang: form Colab
  cukup untuk single-user; token bot tidak perlu tersimpan di browser).

## 5. Di Luar Scope

- Pipeline subtitle/highlight/render backend (sudah paritas desktop).
- Face tracking MediaPipe (Fase 3 spec besar, tetap terpisah).
- Upload chunked (Fase 2 spec besar, tetap terpisah).
- Menyimpan API key di backend/Drive (ditolak: risiko key plaintext di
  Drive; localStorage cukup untuk single-user).

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
