# Working

Prasyarat: issue GitLab benar-benar di-assign ke CoDev. Diverifikasi ulang setiap resume.

**Runbook dulu.** Sebelum menyentuh kode, baca `memories/semantic/workflows/<gitlab-id>-runbook.md` (lihat `tools/runbook.md`). Kalau ada dan current: ikuti untuk setup, seed, start, login, test. Kalau tidak ada atau gagal: discovery, dan tulis runbook sambil jalan. App harus bisa dijalankan dan diakses CoDev sendiri sebelum Implementing dimulai; perubahan tidak dianggap terverifikasi kalau hanya lolos unit test tanpa pernah dilihat jalan.

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

**Validating** — Jalankan app dari worktree sesuai runbook dan verifikasi perilaku baru langsung (endpoint, UI, atau job), lalu test. Sebelum PreparingMergeRequest, `superpowers/requesting-code-review` atas diff worktree terhadap base commit (reviewer lewat `delegate_task`, inline kalau tidak ada); temuan Critical dan Important diperbaiki dulu. Jalankan SonarQube dan perbaiki findings sampai quality gate lolos hanya jika repo sudah memiliki setup Sonar yang dapat dijalankan. Jika belum ada setup, catat status itu di runbook dan MR; Sonar bukan syarat kelulusan untuk repo tersebut. Perubahan yang mengubah cara setup/jalan (dependency, env, migration, seed) wajib memperbarui runbook di MR yang sama.

**PreparingMergeRequest** — Tutup dengan `superpowers/finishing-a-development-branch`; pilihannya sudah ditentukan: opsi "push and create pull request" (MR ke base branch), tanpa merge lokal, worktree dipertahankan. MR terikat ke satu issue. Deskripsi: apa yang berubah, kenapa, cara verifikasi, coverage gap kalau ada. Bukti kualitas = self-review diff + CI + Sonar jika repo sudah memiliki setup Sonar yang dapat dijalankan. Tanpa setup Sonar, tulis "Sonar belum dikonfigurasi" di MR; kondisi itu sendiri tidak menahan MR sebagai Draft. Jika pemeriksaan wajib lain belum lengkap, MR tetap Draft dan ditandai belum terverifikasi.

**Memory selama Working** — Kegagalan yang berguna, hasil validasi, dan link commit/MR dicatat ke `memories/episodic/YYYY-MM-DD.md`. Koreksi terverifikasi atas konvensi atau command repo diperbarui di `semantic/repositories/<gitlab-id>.md` (ubah `Current`, simpan alasan lama di `History`). Percobaan yang gagal tetap berlabel gagal, bukan prosedur.

Blocker teknis → Blocked. MR dibuat → AwaitingReview (`tools/awaiting-review.md`: minta review sebelum idle).
