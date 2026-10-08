# Channel Mattermost tambahan

Gunakan untuk menambahkan channel ke profil CoDev yang sudah ada, termasuk channel log. Ini operasi non-coding dari Understanding, bukan assignment GitLab atau pengulangan Init.

## Prosedur

1. **Tentukan scope dan identitas.** Ambil profil aktif dari runtime dan `PROJECT.yaml.profile`; cocokkan dengan `hermes profile show '<PROFILE>'` dan `hermes -p '<PROFILE>' config path` melalui `terminal`. Validasi channel ID yang diberikan tepat 26 karakter `[a-z0-9]`, tanpa mengubah string. Bedakan permintaan keanggotaan saja dari persetujuan mengaktifkan balasan mention. Untuk log otomatis, pastikan jenis informasi dan tujuan publikasinya memang diotorisasi; label channel bukan persetujuan.

2. **Verifikasi channel dan bot.** Muat `mattermost-access`; gunakan helper credential yang disetujui milik profil `default`, tanpa membuka `.env` langsung atau mencetak token. Baca `GET /api/v4/users/me`, `GET /api/v4/channels/<CHANNEL_ID>`, dan `GET /api/v4/channels/<CHANNEL_ID>/members/<BOT_ID>`. Cocokkan ID, username bot, channel, dan team. Keanggotaan yang sudah ada adalah no-op, bukan alasan mengirim pesan tes. Jika hanya keanggotaan yang diminta dan bot sudah menjadi anggota, pekerjaan itu selesai; route yang belum diminta membutuhkan keputusan terpisah.

3. **Baca konfigurasi terbaru sebelum mengaktifkan balasan.** Melalui `terminal`, gunakan:

   ```sh
   hermes -p default config get --json gateway.profile_routes
   hermes -p default config get --json gateway.multiplex_profiles
   hermes -p default config get --json MATTERMOST_ALLOWED_CHANNELS
   hermes -p default config get --json mattermost.allowed_channels
   hermes -p default config get --json mattermost.require_mention
   ```

   Gunakan YAML sebagai fallback jika override environment tidak tersedia, bukan dengan menggabungkan dua allowlist. Route aktif untuk platform/channel/profil yang sama adalah no-op; route ke profil lain atau route disabled memerlukan keputusan. Lanjutkan hanya setelah scope aktivasi jelas.

4. **Append secara idempoten.** Baca kembali tepat sebelum write, lalu bangun payload dari snapshot terbaru. Tambahkan route dengan `platform: mattermost`, `chat_id: <CHANNEL_ID>`, `profile: <PROFILE>`, dan nama route yang tidak berbenturan. Tulis melalui `hermes -p default config set gateway.profile_routes '<JSON>'`. Untuk allowlist nonempty, append channel ke setting yang efektif; override legacy ditulis dengan `hermes -p default config set MATTERMOST_ALLOWED_CHANNELS '<CSV>'`, fallback YAML melalui `mattermost.allowed_channels`. Jangan mengubah allowlist kosong menjadi pembatas baru tanpa permintaan. Pertahankan seluruh entri lama, mention requirement, free-response channels, dan izin pengguna. Pastikan multiplex aktif tanpa menulis ulang jika sudah true.

5. **Read-back dan aktivasi.** Baca setting yang baru ditulis dan pastikan route target benar serta entri lama utuh. Ikuti `tools/init.md` bagian 1f untuk satu graceful restart dan verifikasi startup baru; jangan menjalankan bagian greeting/PIC/repos. Simpan posisi log sebelum restart agar pesan WebSocket dari boot lama tidak dianggap bukti. Timeout command restart dapat meninggalkan request drain tetap berjalan; periksa bukti terbaru sebelum tindakan berikutnya, jangan mengulang restart atau membunuh pekerjaan profil lain. PID dan `Service restart requested` belum membuktikan kesiapan.

6. **Buktikan batas hasil.** Konfigurasi tersimpan dan transport connected belum membuktikan mention masuk ke profil tujuan. Untuk end-to-end, tunggu mention manusia asli di channel tambahan, lalu periksa database profil secara read-only dengan filter source, channel, profil, dan thread/pesan yang diuji sesuai `tools/init.md` bagian 1g. Sesi dari channel utama tidak memvalidasi channel tambahan. Jangan membuat pesan manusia palsu, self-mention, atau post tes tanpa izin.

## Handoff

Catat identitas channel, route, scope izin, dan bukti verifikasi pada topik proyek yang relevan tanpa secret atau log mentah. Laporan akhir cukup menyebut channel tersambung atau aktivasi masih pending, serta satu tes mention yang diperlukan jika inbound belum terbukti. Jangan menyatakan penerusan log otomatis aktif hanya karena route mention sudah tersedia.
