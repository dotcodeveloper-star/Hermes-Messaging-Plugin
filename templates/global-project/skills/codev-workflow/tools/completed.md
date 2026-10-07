# Completed

Masuk saat MR approved atau merged. **Completed bukan card closed.** Tanggung jawab CoDev berlanjut sampai perubahan berhasil di-deploy dan lolos QA, demo, serta acceptance client di production. Card hanya ditutup PM/QA setelah itu; CoDev tidak pernah menutup card sendiri.

Siklus card setelah merge:

```
Merged → Deployed (tanggung jawab CoDev) → QA testing sesuai AC → Demo client → Pass di production → Closed (oleh PM/QA)
```

## 1. Deploy

CoDev memastikan perubahan sampai ke environment tujuan (staging/UAT, atau sesuai `memories/semantic/workflows/` project itu):

- Kalau deploy lewat pipeline yang CoDev boleh jalankan, jalankan dan pantau sampai selesai.
- Kalau deploy butuh DevOps, minta ke PIC DevOps dengan format blocker: versi/commit, environment tujuan, dan apa yang perlu dilakukan.
- Verifikasi hasilnya sendiri di environment itu (smoke test sesuai AC), bukan hanya status pipeline hijau.
- Deploy gagal karena kode → issue yang sama, worktree yang sama, MR baru. Gagal karena infra → blocker ke DevOps.

Ownership repo tidak memberi otoritas deploy ke production. Production hanya lewat jalur dan orang yang berwenang.

## 2. Handoff ke QA

Geser card ke list Testing sesuai peta `## Board` repo (`tools/board.md`; peta `-` → tidak digeser, cukup sebut di komentar), bukan closed, lalu mention PIC QA di card. Isi handoff:

- Environment dan versi yang di-deploy.
- Checklist AC dari card dan tautan section **Test Suggestion** terbaru pada issue/MR sesuai `SKILL.md`; pastikan prasyarat dan skenario sesuai versi yang di-deploy.
- Bukti yang sudah ada: hasil test, screenshot/log smoke test.
- Coverage gap: apa yang belum diuji CoDev dan kenapa.

## 3. Lapor di surface asal

Catat handoff QA di issue GitLab. Untuk Mattermost, tentukan dulu **di mana sesi ini di-route**, karena itu menentukan mekanismenya:

- **Sesi ini adalah thread Mattermost asal** → ringkasan non-teknis (apa yang sekarang bisa dilakukan, environment, siap QA) adalah **balasan final sesi**, dikirim gateway. Jangan `mattermost-access post`; hasilnya dobel.
- **Sesi ini adalah GitLab issue dengan `Mattermost origin:` di dispatch** → ringkasan lengkap menjadi balasan final; gateway meneruskannya ke thread asal. Jangan `mattermost-access post` dari sesi ini.
- **Sesi ini adalah GitLab issue tanpa relay tersebut**, tetapi permalink thread asal tercatat di issue dan terverifikasi → SOUL mengizinkan satu ringkasan ke thread itu lewat `mattermost-access post`. Verifikasi post berhasil; balasan final di GitLab merujuk permalink-nya.
- Asal tidak terbukti, atau ringkasan sudah pernah sampai di thread itu → tidak ada pesan Mattermost.

Thread, channel, dan DM lain tetap memerlukan izin eksplisit.

## 4. Setelah handoff

- Temuan QA, hasil demo, atau bug dari client di production masuk sebagai diskusi GitLab di issue yang sama → AwaitingRequest → Conversation → perbaikan di worktree issue yang sama dengan MR baru. Card tidak dibuat ulang.
- Worktree issue dipertahankan sampai card closed, bukan sampai MR merged.
- Memory: handoff, environment, versi, dan link MR ke `memories/episodic/YYYY-MM-DD.md`. Cara deploy dan verifikasinya yang baru terbukti masuk bagian Build & deploy di runbook repo (`tools/runbook.md`). Keputusan yang berubah selama review → update `semantic/decisions/`. Refresh `INDEX.md` kalau ada halaman baru.

→ AwaitingRequest.
