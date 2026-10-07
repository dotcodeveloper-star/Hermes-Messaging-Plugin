# Planning

Planning mengubah request menjadi plan di card GitLab. Dua skill berurutan: `superpowers/brainstorming` menghasilkan desain yang disetujui tim, `superpowers/writing-plans` mengubahnya menjadi plan. Semuanya berjalan di surface asal, tanpa file dan tanpa commit; file `docs/superpowers/specs/` dan `docs/superpowers/plans/` yang kedua skill itu minta baru ditulis dan dicommit oleh sesi issue di Working.

1. **Desain dengan `superpowers/brainstorming`.** Baca `memories/semantic/repositories/<gitlab-id>.md` (konvensi, entry point) dan `semantic/decisions/` (keputusan yang sudah ada) sebelum mengusulkan apa pun. Klasifikasikan path dan sebutkan ke tim: spike, bounded, atau architectural; ragu → path yang lebih berat. Pertanyaan satu per satu, pilihan ganda kalau bisa. Setiap pertanyaan atau desain yang menunggu jawaban → AwaitingContext; balasan masuk → kembali ke langkah ini. Visual companion tidak tersedia, jangan ditawarkan.
   - **Spike**: sepakati pertanyaan dan cara probe, investigasi read-only (tanpa file, tanpa commit), laporkan rekomendasi di surface asal. Tidak ada card dan tidak ada plan → AwaitingRequest. Probe yang butuh kode bukan spike: klasifikasi ulang.
   - **Bounded**: pertanyaan yang memang mengubah desain, lalu desain singkat di surface asal (pendekatan, file yang disentuh, cara test). Berhenti sampai tim bilang ya.
   - **Architectural**: pertanyaan, 2–3 pendekatan dengan rekomendasi, desain per section dengan persetujuan tiap section, lalu spec tertulis diposting utuh di surface asal untuk review (bukan file). Spec disetujui → langkah 2.
2. **Plan dengan `superpowers/writing-plans`.** Dari desain (bounded) atau spec (architectural) yang disetujui, susun plan lengkap sesuai skill: header, file per task, interface antar task, step test-first, cara verifikasi, commit per task, self-review. Declared preference CoDev untuk skill ini:
   - Bounded juga mendapat plan tertulis, karena sesi Working tidak melihat percakapan ini. Plan bounded pendek, satu atau dua task.
   - Execution method selalu Native (`superpowers/executing-plans` di Working). Tidak ditanyakan.
   - Execution handoff diganti langkah 3: plan tidak disimpan ke file, tapi ke card.
3. **Buat atau perbarui issue GitLab.** Terapkan aturan **Template issue dan MR** di `SKILL.md` sebelum menyusun deskripsi; tempatkan isi wajib berikut ke struktur template issue repo tujuan. Card adalah satu-satunya jembatan konteks ke sesi Working, yang tidak bisa melihat percakapan Mattermost. Isi wajib:
   - **Tujuan** dan **pendekatan** yang disepakati.
   - **Spec** (architectural) utuh, section terpisah.
   - **Plan** hasil writing-plans, utuh di deskripsi card.
   - **Konteks diskusi**: keputusan yang diambil, alternatif yang ditolak dan alasannya, constraint, siapa yang memutuskan.
   - **Definition of done / AC**; untuk QA sertakan langkah tes dan expected result.
   - **Permalink** thread Mattermost (atau diskusi GitLab) tempat brainstorming terjadi, plus PIC yang terlibat. Pakai `permalink` dari `mattermost-access thread`/`post`, jangan tulis hostname sendiri. Permalink ini yang dibaca gateway saat issue di-assign: sesi Working menerimanya sebagai `Mattermost origin`, dan balasan finalnya (pertanyaan, blocker, hasil) diteruskan ke thread itu. Tanpa permalink, sesi Working tidak tahu asal request.
   Kalau brainstorming menghasilkan keputusan yang berlaku lintas issue, tulis `memories/semantic/decisions/<id>-<slug>.md` (konteks, alternatif, keputusan, alasan, status) dan index-kan; istilah/requirement baru ke `semantic/project.md`.
4. **Konfirmasi lanjut.** Setelah card ada, balasan final berisi link card dan satu pertanyaan ya/tidak: lanjut implementasi sekarang? Tidak menyuruh tim meng-assign. Lalu → AwaitingAssignment.
   - **Ya** (dari user yang berhak) → pastikan permalink thread ini sudah ada di card (langkah 3), lalu CoDev meng-assign dirinya sendiri ke issue lewat GitLab API. Self-assignment adalah handoff: gateway men-dispatch sesi Working di issue itu, dengan konteks dari card dan link thread asal; pertanyaan, blocker, dan hasil dari sesi itu diteruskan gateway ke thread ini. Balasan final mengikuti aturan laporan ke user di `SKILL.md`: link issue dan pekerjaan yang akan dilakukan. Implementasi tidak pernah dimulai dari sesi ini. Follow-up dipilah sesuai `tools/understanding.md`: read-only dan operasi non-coding ditangani langsung dari sesi asal; hanya task coding serta jawaban/info untuk melanjutkan coding diteruskan ke sesi issue dengan `hermes -p default gitlab continue --issue '<project-id>:issues:<iid>'`, bukan dijawab dengan meminta user ke GitLab. Kalau bot sudah assignee, jangan assign ulang: lanjutkan task coding lewat `continue` sesuai `tools/understanding.md`.
   - **Tidak**, atau tidak dijawab → tetap AwaitingAssignment. Tim bisa assign manual kapan saja; tidak dikejar.
   - Request awal sudah minta "langsung assign" atau "assign ke kamu" → lewati pertanyaan, langsung self-assign. "Jangan assign dulu" → lewati pertanyaan, tetap AwaitingAssignment.
   Assignment, oleh tim atau self-assign setelah ya, adalah persetujuan atas plan di card; review plan terjadi di card, bukan lewat pertanyaan tambahan di thread.
5. Perubahan business scope atau arsitektur besar → siapkan proposal konkret, keputusan di tim, sebelum langkah 4.
6. Dependency atau ambiguitas yang menghentikan rencana → Blocked.
