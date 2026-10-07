# AwaitingReview

Masuk saat MR dibuat (dari Working) atau setelah push perbaikan (dari AddressingFeedback). Satu aksi saat masuk: minta review, ke orang yang tepat dan ke thread asal. Setelah itu idle sampai ada trigger.

## 1. Tentukan reviewer

- Baca `memories/semantic/team.md`. Pilih PIC dari area yang disentuh MR: FE untuk frontend, BE untuk backend/API, DevOps untuk CI/infra. MR yang menyentuh dua area → dua PIC. Reviewer yang biasa me-review repo itu (`semantic/repositories/<gitlab-id>.md`, history MR sebelumnya) lebih diutamakan daripada peran umum.
- Username GitLab dan Mattermost diambil dari `team.md` yang sudah terverifikasi, bukan ditebak dari display name. PIC tidak ada, belum terverifikasi, atau perannya ditandai gap → tidak ada mention ke orang; jangan pernah `@all`, `@channel`, atau `@here`.

## 2. Minta review di GitLab

- Geser card ke list Review sesuai peta `## Board` repo (`tools/board.md` langkah 2); peta `-` → tidak digeser.
- Set reviewer MR ke PIC lewat GitLab API kalau PIC teridentifikasi.
- Mention PIC di **balasan final sesi ini** (issue atau MR, tempat sesi di-route), bukan lewat komentar tambahan. Ikuti format laporan ke user di `SKILL.md`: nomor/link MR, pekerjaan yang terkait, dan hasil pemeriksaan serta review secara singkat. Detail cara pemeriksaan dan proses reviewer cukup di deskripsi MR. Nyatakan "sudah direview" hanya jika review selesai; MR Draft disebut "masih perlu pemeriksaan" dengan alasan yang memengaruhi kesiapan hasil. MR baru dilaporkan "sudah dibuat"; MR yang sudah ada dilaporkan "sudah diperbarui".

```
@pic-be MR !<nomor> untuk <pekerjaan/issue> sudah dibuat: <link MR>. <Ringkasan hasil pemeriksaan dan review yang terverifikasi>. Mohon review.
```

PIC tidak teridentifikasi → balasan final tetap berisi hal yang sama tanpa mention, ditutup dengan pertanyaan siapa yang me-review.

## 3. Notify thread Mattermost asal

Berlaku kalau permalink thread asal tercatat di issue (dari Planning) atau `origin_url` handoff terverifikasi, **terlepas dari PIC teridentifikasi atau tidak**.

- Verifikasi dulu dengan `mattermost-access thread --post '<permalink>'`: thread ada, channel cocok dengan yang tercatat.
- Kalau sesi ini sendiri di-route ke thread itu, jangan `post`; isi ini adalah balasan final. Kalau sesi ini di GitLab (kasus normal), kirim **satu** post ke thread itu lewat `mattermost-access post`, mention username Mattermost PIC kalau ada:

```
MR !<nomor> untuk <pekerjaan/issue> sudah dibuat: <link MR>. <Ringkasan hasil pemeriksaan dan review yang terverifikasi>. @pic mohon review.
```

```
MR !<nomor> untuk <pekerjaan/issue> sudah dibuat: <link MR>. <Ringkasan hasil pemeriksaan dan review yang terverifikasi>. Siapa yang bisa review?
```

- Satu post per kali masuk AwaitingReview yang memang butuh review ulang. Push kecil yang hanya menjawab komentar tanpa perubahan substantif tidak dikirim lagi. Setelah `post`, balasan final di GitLab hanya merujuk permalink-nya, tidak mengulang isinya.
- Thread asal tidak tercatat atau gagal diverifikasi → tidak ada pesan Mattermost. Channel, thread, atau DM lain tetap butuh izin eksplisit.

## 4. Lalu idle

- Permintaan operasi non-coding (misalnya undraft atau merge) ditangani langsung oleh sesi yang menerima request sesuai `tools/understanding.md`, dengan izin dan checks GitLab yang berlaku. Undraft tetap AwaitingReview; approved atau merged → Completed. Perubahan kode atau resolusi konflik → AddressingFeedback di sesi issue.

- Diam sampai trigger gateway: feedback atau konflik → AddressingFeedback; approved atau merged → Completed. Satu reminder ke reviewer boleh kalau MR lewat batas waktu yang disepakati tim, di surface GitLab, sekali.
- Memory: MR, reviewer yang diminta, dan permalink notice ke `memories/episodic/YYYY-MM-DD.md`. Reviewer yang terbukti aktif untuk repo itu dicatat di `semantic/repositories/<gitlab-id>.md`.
