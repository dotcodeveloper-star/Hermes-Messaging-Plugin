# Working

Prasyarat: issue GitLab benar-benar di-assign ke CoDev. Diverifikasi ulang setiap resume.

**Card ke Doing.** Saat masuk Working, termasuk kembali dari AddressingFeedback, geser card ke list Doing sesuai peta `## Board` repo itu (`tools/board.md` langkah 2). Peta belum ada → refresh dulu dari board yang ada; tetap tidak ada list yang cocok → card tidak digeser.

**Runbook dulu.** Sebelum menyentuh kode, baca `memories/semantic/workflows/<gitlab-id>-runbook.md` (lihat `tools/runbook.md`) dan pilih kelas verifikasi di bawah. Kalau ada dan current: pakai langkah yang diperlukan kelas itu, termasuk setup, seed, start, dan login bila pengujiannya membutuhkan app berjalan. Kalau tidak ada atau gagal: discovery terbatas pada kebutuhan verifikasi, dan tulis langkah yang berhasil di runbook. Setup seluruh stack bukan prasyarat Implementing untuk setiap perubahan.

**Urutan skill superpowers.** `superpowers/using-git-worktrees` → `superpowers/executing-plans` → `superpowers/test-driven-development` → `superpowers/requesting-code-review` → `superpowers/finishing-a-development-branch`. Muat masing-masing saat sub-state-nya masuk, bukan semuanya di awal.

**Worktree.** Buat lewat `superpowers/using-git-worktrees`; aturan di paragraf ini adalah declared preference-nya (tanpa consent prompt, tanpa `.worktrees/` di root repo selain path kanonis di bawah). Satu issue = satu worktree di `workspace/`, branch dinamai dari nomor issue. Dari sesi GitLab issue yang di-assign, verifikasi main clone di `PROJECT.yaml`, base commit, dan worktree yang sudah terdaftar dengan `git worktree list --porcelain`. Sebelum membuat worktree baru, pastikan `/.worktrees/` ada di local Git exclude main clone (`.git/info/exclude`) dan verifikasi dengan `git check-ignore -q .worktrees/`; ini mencegah checkout lain masuk ke `git add -A` pada main clone. Pilih prefix branch `feature`, `fix`, atau `chore` sesuai task, lalu gunakan native Git:

```sh
git -C "$HERMES_HOME/workspace/<project-id>" worktree add \
  -b "feature/<project-id>-issues-<iid>" \
  "$HERMES_HOME/workspace/<project-id>/.worktrees/<project-id>-issues-<iid>" \
  '<verified-base-commit>'
```

Pastikan target kanonis tetap di workspace profil dan belum dipakai worktree lain. Verifikasi path dan branch hasilnya dengan `git worktree list --porcelain`, lalu gunakan path itu untuk semua edit, test, commit, dan MR. Jangan berbagi worktree antar issue. Saat resume, pakai worktree terdaftar yang sama; bila path hilang tetapi branch masih ada, periksa riwayat lalu tautkan kembali dengan `git worktree add <path> <existing-branch>` tanpa `-b`. Jangan jalankan `git clean -ffdx` dari main clone karena dapat menghapus worktree di bawah `.worktrees/`. Jangan force, reset, atau menghapus branch untuk mengatasi konflik.

**InspectingRepository** — Sesi ini tidak punya memori percakapan Mattermost; konteks diambil dari artefak, urutannya:
1. Deskripsi dan komentar issue: tujuan, keputusan, alternatif yang ditolak, AC.
2. Thread Mattermost asal: baris `Mattermost origin:` di pesan dispatch (gateway mengambilnya dari permalink di card) atau permalink yang ditautkan di issue. Buka lewat API Mattermost (baca saja), ambil detail yang belum tertulis di card. Kalau dispatch memuat `Mattermost origin`, balasan final sesi ini (pertanyaan, blocker, hasil) diteruskan gateway ke thread itu; jangan `post` ulang isi yang sama ke sana.
3. Memory: `semantic/repositories/<gitlab-id>.md` (konvensi, command), `semantic/decisions/` (keputusan lintas issue), `semantic/workflows/` (cara setup/test). Cek `verified_at` dan `status` sebelum mengandalkannya.
4. Kode dan history GitLab yang relevan saja.
Kalau card tidak punya konteks maupun permalink dan scope ambigu → NeedsContext, ditanyakan di issue GitLab, bukan di Mattermost. Detail yang ditemukan dari thread dan penting untuk MR dicatat ke issue supaya reviewer tidak perlu membuka Mattermost.

**Implementing** — Jalankan plan dari card dengan `superpowers/executing-plans`; kalau `docs/superpowers/plans/<plan>.md` belum ada di repo, tulis dari isi card dan commit di worktree ini. Tiap task test-first lewat `superpowers/test-driven-development`. Perubahan terkecil yang lengkap. Commit dengan pesan yang menjelaskan alasan, bukan hanya perubahan. Nilai secret tidak pernah masuk commit atau log.

**Validating** — Jalankan pemeriksaan sesuai kelas verifikasi di bawah dari worktree, memakai runbook. Sebelum PreparingMergeRequest, `superpowers/requesting-code-review` atas diff worktree terhadap base commit (reviewer lewat `delegate_task`, inline kalau tidak ada); temuan Critical dan Important diperbaiki dulu. Jalankan SonarQube dan perbaiki findings sampai quality gate lolos hanya jika repo sudah memiliki setup Sonar yang dapat dijalankan. Jika belum ada setup, catat status itu di runbook dan MR; Sonar bukan syarat kelulusan untuk repo tersebut. Perubahan yang mengubah cara setup/jalan (dependency, env, migration, seed) wajib memperbarui runbook di MR yang sama.

### Kelas verifikasi

Pilih dari dampak kegagalan dan batas sistem yang berubah, bukan jumlah baris atau label "perubahan UI". Untuk perubahan campuran, pakai kelas tertinggi yang relevan. AC atau quality gate repo yang eksplisit tetap wajib. Catat kelas dan alasannya dalam satu kalimat di plan/MR; perbarui kalau dampak baru ditemukan.

| Kelas | Kapan | Bukti minimum | E2E |
|---|---|---|---|
| A — Statis atau visual | Dokumen, komentar, copy, warna, spacing, atau layout tanpa perubahan perilaku, aksesibilitas interaktif, atau kontrak data. | Cek statis/build yang relevan; untuk tampilan, lihat hasil render dan screenshot state/viewport terdampak. Preview komponen cukup jika mewakili konteks perubahan. | Tidak wajib. |
| B — Perilaku terisolasi | Logika lokal, validasi input, state komponen, atau endpoint/job yang kontrak, otorisasi, dan integrasi pemanggilnya tetap. | Unit/component/integration test yang membuktikan perilaku berubah dan kasus gagal relevan. Untuk UI, smoke interaksi terdampak dan screenshot. | Tidak wajib jika cek terfokus membuktikan AC; naik ke C bila ada wiring lintas batas yang belum terbukti. |
| C — Alur lintas sistem atau kritis | Wiring UI–API–penyimpanan, kontrak lintas layanan, routing/session/login/otorisasi, pembayaran, aksi destruktif, migration/data integrity, atau regresi yang hanya muncul dalam alur lengkap. Termasuk perubahan backend tanpa UI. | Test terfokus plus E2E pada alur terdampak dan kasus gagal yang relevan, dengan hasil lulus. UI menyertakan screenshot. | Wajib; pilih skenario terkecil yang melewati batas/risiko tersebut. |

**Cakupan E2E wajib.** Wajib E2E berarti membuktikan perilaku terdampak pada batas yang diperlukan, bukan menambah journey lengkap lintas modul. Pakai runner dan skenario yang sudah ada; tambah/update hanya gap yang langsung terkait AC atau risiko perubahan. Seed/fixture, session tersimpan, atau akun uji membawa test langsung ke awal langkah terdampak. Login, onboarding, dan modul lain hanya masuk skenario jika perilaku atau integrasinya ikut berubah. Tiap langkah/assertion harus membuktikan AC atau risiko tersebut; prasyarat lain disiapkan lewat fixture/API. Mock cukup untuk A/B, tetapi E2E C harus melewati batas yang sedang dibuktikan, termasuk penyimpanan bila persistensi berubah. Contoh: perubahan simpan alamat diuji dari form alamat dengan user sudah login → simpan → reload dan cek persistensi; tidak perlu membuat user, checkout, pembayaran, dan pengiriman. Alur lintas modul diuji hanya bila hubungan antarmodul itu sendiri terdampak atau diwajibkan AC/gate repo.

**Suite penuh.** Menjalankan suite yang sudah ada berbeda dari menulis coverage baru. Suite penuh hanya untuk perubahan infrastruktur bersama yang memengaruhi banyak alur, dependency/runtime global, gate repo, atau permintaan eksplisit. Bahkan ketika suite penuh dijalankan, test baru tetap terbatas pada gap perubahan; beberapa skenario terdampak cukup untuk perubahan terbatas.

**Batas waktu.** Pakai durasi/timeout runner yang diketahui dari runbook. Jika belum diketahui, default 10 menit per run, lalu diagnosis dari log/artifact. Total setup dan diagnosis E2E lokal dibatasi 10 menit per task, termasuk resume; tambah satu percobaan hanya setelah penyebab konkret diperbaiki, tetap dalam anggaran. Jika CI yang sudah tersedia bisa menjalankan skenario sama, gunakan hasilnya pada revisi yang diuji. Setelah anggaran habis, hentikan percobaan E2E lokal: A/B ditutup dengan bukti minimum yang lulus dan catatan E2E tidak wajib; C atau gate repo tetap belum terverifikasi, MR Draft, laporkan blocker konkret. Timeout bukan hasil lulus dan bukan alasan menurunkan kelas. Perbaikan kode untuk kegagalan produk tetap dilanjutkan; anggaran ini membatasi setup/diagnosis lingkungan, bukan membatasi penyelesaian bug.

**Bukti MR.** Catat kelas/alasan, skenario, perintah/hasil, revisi, dan coverage gap. Screenshot berasal dari render pada revisi yang diuji, di-upload ke GitLab atau artifact yang dapat diakses reviewer; path lokal saja tidak cukup. MR siap review setelah bukti wajib kelasnya dan gate repo lulus. E2E yang tidak wajib tidak menahan review; pemeriksaan wajib yang gagal atau bukti wajib yang hilang tetap menahan review.

**PreparingMergeRequest** — Tutup dengan `superpowers/finishing-a-development-branch`; pilihannya sudah ditentukan: opsi "push and create pull request" (MR ke base branch), tanpa merge lokal, worktree dipertahankan. MR terikat ke satu issue. Terapkan aturan **Template issue dan MR** di `SKILL.md` sebelum menyusun atau memperbarui deskripsi; template MR repo tujuan menggantikan format generik dari skill penutup. Deskripsi: apa yang berubah, kenapa, cara verifikasi, coverage gap kalau ada. Bukti kualitas = self-review diff + CI + Sonar jika repo sudah memiliki setup Sonar yang dapat dijalankan. Tanpa setup Sonar, tulis "Sonar belum dikonfigurasi" di MR; kondisi itu sendiri tidak menahan MR sebagai Draft. Jika pemeriksaan wajib lain belum lengkap, MR tetap Draft dan ditandai belum terverifikasi.

**Memory selama Working** — Kegagalan yang berguna, hasil validasi, dan link commit/MR dicatat ke `memories/episodic/YYYY-MM-DD.md`. Koreksi terverifikasi atas konvensi atau command repo diperbarui di `semantic/repositories/<gitlab-id>.md` (ubah `Current`, simpan alasan lama di `History`). Percobaan yang gagal tetap berlabel gagal, bukan prosedur.

**Titik pelaporan** — Lanjutkan implementasi, commit, validasi, review, dan pembuatan MR dalam sesi yang sama. Tunggu hasil reviewer AI, tangani temuannya, lalu buat MR; review yang masih berjalan bukan alasan mengakhiri giliran dengan laporan progres. Audit berjalan, snapshot commit, inventaris sementara, dan lampiran yang belum siap cukup menjadi catatan internal. Sebelum MR siap review, balasan final hanya untuk pertanyaan atau blocker yang membutuhkan tindakan manusia; permintaan status eksplisit dijawab sesuai `tools/understanding.md`.

**Penutupan giliran Working** — Setelah MR dibuat, jalankan AwaitingReview sebelum idle: laporan wajib memuat link MR, kesiapan berdasarkan pemeriksaan wajib, dan tindakan reviewer. MR Draft yang tertahan dilaporkan bersama blocker konkretnya, bukan disebut siap review. Saat resume, periksa MR yang sudah ada dan laporan di thread asal; jika MR sudah siap tetapi belum diberitahukan, selesaikan pelaporannya lewat AwaitingReview tanpa membuat MR baru. Selesainya development atau reviewer AI belum menutup kewajiban laporan ini.

Blocker teknis → Blocked. MR dibuat → AwaitingReview (`tools/awaiting-review.md`: minta review sebelum idle).
