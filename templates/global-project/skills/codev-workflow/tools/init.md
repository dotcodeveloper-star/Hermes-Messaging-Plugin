# Init

Dipakai sekali saat onboarding, sebelum menerima request apa pun. Empat langkah, berurutan.

## 1. Setup koneksi Mattermost

Belum ada channel, jadi ini satu-satunya saat CoDev bertanya lewat sesi operator. Semua perubahan dijalankan CoDev sendiri lewat `terminal`, hasilnya diverifikasi nyata, dan bagian yang belum terbukti dilaporkan apa adanya.

**Arsitektur.** Bot Mattermost dimiliki profil `default` dan dipakai bersama. Profil CoDev adalah satellite: tidak butuh token sendiri, tidak menjalankan gateway kedua. Yang menghubungkan channel ke CoDev adalah *route* di config `default` plus mode multiplex.

**1a. Discovery.** Jalankan `hermes profile list` dan `hermes profile show codev` untuk memastikan nama profil, `HERMES_HOME`, dan path config (`hermes -p codev config path`). Tanya operator satu hal: **channel ID** tim. Validasi tepat 26 karakter `[a-z0-9]`; kalau tidak valid, tanya ulang, jangan dikoreksi diam-diam. Lebih dari satu channel ditanyakan dalam satu pertanyaan. Tidak minta token atau password lewat chat.

**1b. Profil.** Reuse profil yang ada; jangan buat ulang atau hapus state. Cek `hermes -p codev config get --json model` dan `hermes -p codev config check`. Credential yang kurang dipasang operator di `.env` profil `codev`; sebut nama variabel dan tujuannya, bukan nilainya. Set `terminal.cwd` ke workspace absolut lewat CLI. Jangan hand-edit `config.yaml`; selalu `hermes config set`.

**1c. Verifikasi bot.** Pakai koneksi Mattermost profil `default` yang sudah terkonfigurasi untuk memanggil `GET /api/v4/users/me` (identitas bot), `GET /api/v4/channels/CHANNEL` (channel ada), dan `GET /api/v4/channels/CHANNEL/members/BOT_ID` (bot member). Kalau `/users/me` saja sudah 403 HTML padahal adapter bisa login, masalahnya proxy/transport, bukan token atau membership; samakan transport dengan adapter (mis. `trust_env=False`) kalau diizinkan, jangan bypass proxy wajib. Kalau bot memang bukan member, minta operator menambahkan bot; jangan tambah anggota lain.

**1d. Gate penerimaan.** Baca allowlist efektif di profil `default`: `MATTERMOST_ALLOWED_CHANNELS` di `.env` mengalahkan `mattermost.allowed_channels` di YAML. Kalau allowlist nonempty, **append** channel target, pertahankan semua entri lama. Jangan kosongkan allowlist, jangan allow-all-users, jangan matikan mention requirement. Override legacy di `.env` diubah terarah di tempatnya, bukan dengan menulis YAML yang akan diabaikan.

**1e. Route.** Baca `hermes -p default config get --json gateway.profile_routes` dan `gateway.multiplex_profiles`. Parse JSON, append idempoten:

```yaml
name: mattermost-codev
platform: mattermost
chat_id: <CHANNEL_ID>
profile: codev
```

Key-nya `gateway.profile_routes`, bukan `messaging.profile_routes`. Route yang sama ke `codev` = no-op. Route channel yang sama ke profil lain = berhenti, tanya operator. Tulis lewat `hermes -p default config set gateway.profile_routes '<JSON>'` dengan quoting aman, pastikan `gateway.multiplex_profiles` true, lalu baca ulang dan pastikan daftar lama utuh.

**1f. Aktivasi.** `hermes -p default gateway restart` sekali; hormati graceful drain. "Service restart requested" atau PID bukan bukti siap: cek proses gateway dan log terbaru sampai `WebSocket connected and authenticated` dan startup multiplex selesai. Bounded check; jangan restart berulang.

**1g. Verifikasi end-to-end.** Tes outbound = langkah 2 (greetings), baca kembali post ID-nya. Tes inbound = balasan user asli dengan mention bot; jangan memalsukan pesan user, jangan post ke diri sendiri. Setelah balasan masuk, cek session store profil `codev` (query SQLite read-only, filter `source=mattermost`, `chat_id`, `profile_name`; output minimal). Kalau belum ada inbound, minta operator kirim satu `@bot tes`.

Status dilaporkan terpisah: `configured` / `connected` / `end-to-end verified`. Jangan mengklaim koneksi selesai sebelum inbound terbukti. Kalau blocked, sebut langkah operator terkecil yang dibutuhkan.

## 2. Post greetings thread

Satu pesan di channel yang diberikan, jadi thread induk untuk sisa onboarding dan sekaligus tes outbound (baca kembali post ID setelah kirim). Pendek, maksimal tiga kalimat, nada menyapa, bukan manual:

- Sapaan dan perkenalan satu kalimat: CoDev, developer baru di tim, mengerjakan issue GitLab yang di-assign ke CoDev.
- Ajak kenalan: siapa PIC FE, BE, QA, PM, DevOps, dan project apa saja yang jadi tanggung jawab CoDev. Minta dibalas di thread ini.

Contoh: "Halo semua, saya CoDev, developer baru di tim yang akan mengerjakan issue GitLab yang di-assign ke saya. Biar bisa mulai, boleh kenalan dulu: siapa PIC FE, BE, QA, PM, dan DevOps, dan project apa saja yang jadi tanggung jawab saya? Balas di thread ini ya."

Cara memberi task belum dijelaskan di sini; itu disampaikan di balasan penutup langkah 4. Semua balasan onboarding di thread ini. Tidak ada DM ke orang yang belum pernah berinteraksi.

## 3. Petakan PIC

Dari balasan thread, catat PIC per peran: FE, BE, QA, PM, DevOps. Simpan di `memories/semantic/team.md` (username Mattermost + GitLab, peran, bukti perannya, tanggal verifikasi); peran yang belum jelas ditandai sebagai gap di file yang sama. Peran yang belum terjawab ditanyakan sekali lagi di thread yang sama, lalu ditandai "belum ada" tanpa mengejar.

Peta ini yang dipakai seterusnya: blocker di-mention ke PIC peran yang relevan, bukan ke channel; pertanyaan business scope ke PM; deploy/env ke DevOps; acceptance ke QA.

## 4. Pelajari registered projects

Untuk tiap project yang disebut:

1. Cocokkan dengan `PROJECT.yaml`. Inventory ini dikelola plugin: yang belum terdaftar ditambahkan lewat repository mapping, bukan hand-edit. Yang ambigu ditanyakan di thread, jangan menebak.
2. Clone ke `workspace/`, baca README, manifest, entry point, pipeline CI, quality gate SonarQube.
3. Jalankan app end-to-end sendiri dan tulis runbook-nya (`tools/runbook.md`): install, env, migrate/seed, start, health check, login dengan akun uji, test. Minta akun uji dan credential yang tidak ada di repo ke PIC yang relevan; simpan di private runtime state, runbook hanya menunjuk lokasinya. Yang gagal karena butuh informasi (env yang tidak ada di repo, service eksternal, credential) ditanyakan ke PIC yang relevan di thread; credential hanya diterima lewat DM terverifikasi. Yang gagal karena hal yang bisa diselesaikan di mesin CoDev diselesaikan sendiri.
4. Baca board GitLab yang sudah ada untuk repo itu (`tools/board.md` langkah 1): daftar list dan labelnya, pilih board yang benar-benar dipakai tim, petakan ke state CoDev, dan tulis section `## Board` di `memories/semantic/repositories/<gitlab-id>.md`. Pencocokan yang ambigu ditanyakan sekali di thread onboarding; tidak ada board → catat "tidak ada", jangan membuat label.
5. Catat ke memory sesuai rumahnya: peran repo, entry point, command, konvensi → `memories/semantic/repositories/<gitlab-id>.md`; cara setup/test yang sudah terbukti jalan (nama variabel dan lokasinya, tanpa nilai) → `semantic/workflows/<slug>.md`; istilah domain dan batas produk → `semantic/project.md`; dependensi antar repo → `semantic/architecture.md`. Setiap halaman baru di-index di `memories/INDEX.md`; ringkasan startup di `MEMORY.md` lewat native memory tool.

Selesai saat semua project bisa dijalankan, diakses, dan di-test dari mesin CoDev, tiap repo punya runbook `status: current`, dan tiap repo punya section `## Board` (peta atau "tidak ada"). Tutup dengan satu balasan di thread: project mana yang sudah siap, mana yang masih butuh apa dari siapa, lalu satu kalimat cara memberi task (assign issue GitLab ke CoDev, atau minta CoDev buat issue dan jawab "ya" saat ditanya lanjut; CoDev juga bisa diajak brainstorming dan ditanya soal kode). Transisi ke AwaitingRequest.
