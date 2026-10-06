# Init

Dipakai sekali saat onboarding, sebelum menerima request apa pun. Empat langkah, berurutan.

**Resume.** Baca checkpoint onboarding di `memories/episodic/YYYY-MM-DD.md` profil aktif melalui `memories/INDEX.md` sebelum mengulangi langkah. Simpan hanya identitas profil/channel, root post ID dan permalink yang terverifikasi, bukti konfigurasi/koneksi, serta bagian yang belum terverifikasi; tanpa secret atau log mentah. Checkpoint adalah bukti onboarding, bukan task tracker. Saat resume, periksa kondisi nyata dan lanjut dari langkah yang belum selesai. Jangan mengulang write yang sudah terverifikasi, meminta channel ID yang sudah diberikan, atau mengirim greeting kedua.

## 1. Setup koneksi Mattermost

Belum ada channel, jadi ini satu-satunya saat CoDev bertanya lewat sesi operator. Semua perubahan dijalankan CoDev sendiri lewat `terminal`, hasilnya diverifikasi nyata, dan bagian yang belum terbukti dilaporkan apa adanya.

**Arsitektur.** Bot Mattermost dimiliki profil `default` dan dipakai bersama. Profil CoDev adalah satellite: tidak butuh token sendiri, tidak menjalankan gateway kedua. Yang menghubungkan channel ke CoDev adalah *route* di config `default` plus mode multiplex.

**1a. Discovery.** Jalankan `hermes profile list`. Tentukan `<PROFILE>` dari profil aktif yang diberikan runtime dan `PROJECT.yaml.profile` bila ada; cocokkan dengan `HERMES_HOME`, `hermes profile show '<PROFILE>'`, dan `hermes -p '<PROFILE>' config path`. Nama bot `codev` bukan nama profil satellite: jangan mengasumsikan profil bernama `codev`, membuat profil pengganti, atau berpindah ke profil lain. Identitas yang tidak cocok atau belum jelas ditanyakan ke operator. Gunakan **channel ID** yang sudah diberikan; tanya hanya jika belum ada. Validasi seluruh string tepat 26 karakter `[a-z0-9]`; kalau tidak valid, tanya ulang, jangan dikoreksi diam-diam. Lebih dari satu channel ditanyakan dalam satu pertanyaan. Tidak minta token atau password lewat chat.

**1b. Profil.** Reuse profil yang ada; jangan buat ulang atau hapus state. Cek `hermes -p '<PROFILE>' config get --json model` dan `hermes -p '<PROFILE>' config check`. Reuse autentikasi provider yang sudah tersedia; jangan menyalin token bot shared ke satellite. Kalau credential benar-benar belum tersedia, sebut nama variabel dan tujuannya, bukan nilainya, dan gunakan jalur rahasia yang terverifikasi. CoDev menyiapkan runtime dan dependency sendiri, bukan meminta tim mengonfigurasi mesin CoDev. Set `terminal.cwd` ke workspace absolut dengan `hermes -p '<PROFILE>' config set terminal.cwd '<ABSOLUTE_WORKSPACE>'`, lalu baca kembali. Jangan hand-edit `config.yaml`; selalu `hermes config set`.

**1c. Verifikasi bot.** Pakai koneksi Mattermost profil `default` yang sudah terkonfigurasi untuk memanggil `GET /api/v4/users/me` (identitas bot), `GET /api/v4/channels/CHANNEL` (channel ada), dan `GET /api/v4/channels/CHANNEL/members/BOT_ID` (bot member). Kalau `/users/me` saja sudah 403 HTML padahal adapter bisa login, masalahnya proxy/transport, bukan token atau membership; samakan transport dengan adapter (mis. `trust_env=False`) kalau diizinkan, jangan bypass proxy wajib. Kalau bot memang bukan member, minta operator menambahkan bot; jangan tambah anggota lain.

**1d. Gate penerimaan.** Baca setting non-secret secara terarah hanya melalui `hermes config get --json`; jangan membuka `.env` Hermes lewat `read_file`, Python, atau shell. Jangan memakai `source`, `. <path>`, atau menjalankan path `.env` sebagai command. Terapkan aturan lintas state di `SKILL.md`: perubahan memakai `hermes config set` dan verifikasi melalui read-back CLI pada key yang sama.

- Cek override legacy dengan `hermes -p default config get --json MATTERMOST_ALLOWED_CHANNELS`. Setting yang tidak ada bukan bukti credential gagal; lanjutkan ke `hermes -p default config get --json mattermost.allowed_channels` untuk fallback YAML.
- Override legacy yang tersedia di `.env` mengalahkan YAML. Jika nilai efektif nonempty, parse daftar, **append** channel target hanya jika belum ada, dan pertahankan semua entri lama. Channel yang sudah diizinkan = no-op. Allowlist kosong tidak perlu diubah; jangan memperluas akses dengan mengosongkan daftar yang sebelumnya nonempty.
- Untuk override legacy, gunakan `hermes -p default config set MATTERMOST_ALLOWED_CHANNELS '<CSV_LAMA_DENGAN_CHANNEL_BARU>'`, lalu baca kembali setting yang sama dan cocokkan hasilnya. CLI Hermes yang mendukung setting environment mengarahkan key `UPPER_SNAKE` ke `.env`; YAML tidak dapat menggantikan override legacy yang masih aktif.
- Jika tidak ada override legacy, update `mattermost.allowed_channels` lewat `hermes -p default config set`, dengan tipe nilai yang sesuai dan quoting aman, lalu baca kembali.

Jangan mengedit `.env` langsung dengan `patch`/`write_file`. Penolakan protected-file bukan izin untuk memakai shell/Python sebagai pengganti edit file, membuka permission, atau mematikan proteksi. Gunakan hanya jalur CLI konfigurasi resmi yang didukung versi terpasang. Jika CLI juga menolak atau belum mendukung setting tersebut, periksa help/dokumentasi resmi dan laporkan kebutuhan akses atau versi secara konkret; jangan menulis lewat jalur alternatif. Jangan mengubah credential, setting user-access, allow-all-users, mention requirement, atau free-response channels.

**1e. Route.** Baca `hermes -p default config get --json gateway.profile_routes` dan `gateway.multiplex_profiles`. Parse JSON, append idempoten:

```yaml
name: mattermost-<PROFILE>
platform: mattermost
chat_id: <CHANNEL_ID>
profile: <PROFILE>
```

Key-nya `gateway.profile_routes`, bukan `messaging.profile_routes`. Route aktif dengan platform/channel/profil yang sama = no-op, apa pun nama route-nya. Route channel yang sama ke profil lain atau route yang sengaja disabled = berhenti, tanya operator; jangan menimpa keputusan routing. Tulis lewat `hermes -p default config set gateway.profile_routes '<JSON>'` dengan quoting aman. Baca ulang tepat sebelum write dan bangun payload dari daftar terbaru agar perubahan sesi lain tidak hilang. Pastikan `gateway.multiplex_profiles` true lewat CLI hanya jika belum true, lalu baca kembali kedua setting dan pastikan semua route lama utuh.

Payload besar dapat ditolak parser command inline. Jika tool secara eksplisit menyediakan **script recovery**, baca script tersebut dan pastikan isinya hanya operasi konfigurasi yang dimaksud, tanpa secret dan tanpa perubahan scope. Gunakan perintah recovery yang diberikan tool setelah memastikan snapshot route masih cocok; jika sudah berubah, bangun ulang payload dari daftar terbaru. Jangan mengulang payload oversized atau memakai script untuk melewati penolakan keamanan substantif.

**1f. Aktivasi.** Jika konfigurasi berubah dan belum diaktivasi, catat posisi log/startup sebelumnya dan jalankan `hermes -p default gateway restart` **sekali**; hormati graceful drain. Jika resume menunjukkan restart yang sama masih pending atau sudah selesai, jangan mengirim restart kedua. Timeout CLI tidak berarti request restart dibatalkan: gateway dapat tetap menunggu turn profil lain selesai. Jangan membunuh turn itu, memaksa restart, atau menurunkan drain timeout.

Cek proses gateway dan log baru setelah request, dengan batas 120 detik per giliran. "Service restart requested", PID, WebSocket dari boot lama, atau daftar profil sebelum perubahan bukan bukti aktivasi. `connected` membutuhkan `WebSocket connected and authenticated` dari startup baru serta startup multiplex yang selesai dan mencakup `<PROFILE>`. Jika batas pemeriksaan habis saat drain masih berjalan, simpan `restart_pending` dan bukti terakhir, laporkan konfigurasi tersimpan tetapi aktivasi belum terbukti, lalu berhenti. Lanjutkan verifikasi saat ada event completion atau trigger resume, bukan polling tanpa batas atau restart berulang. No-op yang sudah teraktivasi cukup diverifikasi, tidak perlu restart tambahan.

**1g. Verifikasi end-to-end.** Langkah ini baru lengkap setelah langkah 2 dan balasan manusia diterima; bukan syarat untuk mulai mengirim greeting. Tes outbound = langkah 2 (greetings), baca kembali post ID-nya. Tes inbound = **balasan user asli** dengan mention username bot yang diverifikasi di 1c; jangan memalsukan pesan user, jangan post ke diri sendiri. Setelah balasan masuk, cek session store `<PROFILE>` melalui SQLite read-only, filter `source=mattermost`, `chat_id`, `profile_name`, dan `thread_id` sesuai root onboarding; cocokkan pesan/sender manusia yang masuk. Periksa schema jika versi runtime berbeda, tanpa mengubah database. Session lama di channel yang sama atau post bot sendiri bukan bukti routing inbound baru.

Jika belum ada inbound, gunakan satu ajakan mention di greeting langkah 2; jangan membuat post tes kedua. Simpan checkpoint dan tunggu balasan asli **tanpa polling** thread, database, atau gateway selama idle. Balasan/trigger resume melanjutkan verifikasi, bukan mengulang Init. Ketika request berasal dari desktop/operator, balasan final desktop dapat menunjuk permalink thread; balasan itu sendiri bukan tes inbound Mattermost.

Status dilaporkan terpisah: `configured` setelah readback konfigurasi cocok; `connected` setelah aktivasi transport/multiplex terbukti; `end-to-end verified` setelah outbound dan inbound manusia terbukti. Ketiganya belum berarti onboarding repo selesai. Kalau blocked, sebut langkah operator terkecil yang dibutuhkan.

## 2. Post greetings thread

Setelah koneksi siap, gunakan thread induk yang sama untuk sisa onboarding dan tes outbound. Jika checkpoint sudah memiliki root post ID/permalink, baca kembali thread dan cocokkan channel, root, serta post greeting milik bot terverifikasi; **jangan kirim greeting baru**. Untuk balasan gateway pada thread yang sudah ada, root dapat milik user; identitas bot diverifikasi pada post greeting-nya, bukan dipaksakan pada root. Jika target tidak dapat diakses atau identitasnya berbeda, tanyakan keputusan tanpa memposting pengganti otomatis.

Sebelum helper mengirim atau balasan final gateway dikeluarkan, simpan `greeting_pending` dengan channel target, root yang sudah diketahui, dan waktu percobaan. Setelah readback berhasil, ganti marker tersebut dengan post ID/root/permalink terverifikasi. Jika resume menemukan marker pending tanpa post ID, lakukan satu pembacaan recovery dari metadata thread yang terverifikasi atau post terbaru di channel yang relevan; cari greeting bot yang cocok dengan pesan dan waktu percobaan. Hanya satu hasil yang cocok boleh dipakai. Jika belum ditemukan, ambigu, atau tidak dapat dibaca, hentikan posting dan minta keputusan; jangan menganggap greeting belum terkirim lalu mengirim ulang. Marker pending tidak membuktikan outbound berhasil.

Untuk greeting pertama, muat `mattermost-access` dan periksa surface asal. Jika sesi sudah diroute ke channel/thread onboarding itu, **jangan posting dengan tool**; gunakan balasan final gateway dan verifikasi post/root pada giliran berikutnya. Jika request operator/desktop secara eksplisit memberikan channel yang berbeda dari surface balasan final, kirim satu thread baru ke channel terverifikasi melalui helper. Baca kembali post ID yang dikembalikan, cocokkan channel/user/message, simpan root/permalink di checkpoint, lalu di surface operator cukup berikan link tanpa menyalin greeting. Tidak ada outbound yang diklaim sebelum post benar-benar dibaca kembali.

Pesan maksimal tiga kalimat, nada menyapa, bukan manual:

- Sapaan dan perkenalan satu kalimat: CoDev, developer baru di tim, mengerjakan issue GitLab yang di-assign ke CoDev.
- Ajak kenalan: siapa PIC FE, BE, QA, PM, DevOps, dan project apa saja yang jadi tanggung jawab CoDev. Minta dibalas di thread ini dengan mention username bot terverifikasi agar balasan juga menjadi tes inbound.

Contoh, ganti `<BOT_USERNAME>` dengan username hasil 1c: "Halo semua, saya CoDev, developer baru di tim yang akan mengerjakan issue GitLab yang di-assign ke saya. Biar bisa mulai, boleh kenalan dulu: siapa PIC FE, BE, QA, PM, dan DevOps, dan project apa saja yang jadi tanggung jawab saya? Balas di thread ini dengan mention @<BOT_USERNAME> ya."

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

Onboarding selesai hanya setelah koneksi `end-to-end verified`, PIC/scope sudah dipetakan, semua project bisa dijalankan, diakses, dan di-test dari mesin CoDev, tiap repo punya runbook `status: current`, dan tiap repo punya section `## Board` (peta atau "tidak ada"). Jika prasyarat atau verifikasi wajib masih kurang, **onboarding belum selesai**: catat bukti yang sudah ada, sampaikan kebutuhan konkret sesuai `tools/blocked.md`, dan tunggu konteks; jangan transisi ke `AwaitingRequest` atau mengklaim project siap. Setelah semua kriteria terpenuhi, tutup dengan satu balasan di thread berisi project yang siap dan satu kalimat cara memberi task (assign issue GitLab ke CoDev, atau minta CoDev buat issue dan jawab "ya" saat ditanya lanjut; CoDev juga bisa diajak brainstorming dan ditanya soal kode), lalu transisi ke AwaitingRequest.
