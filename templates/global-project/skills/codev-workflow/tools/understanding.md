# Understanding

1. Kalau butuh investigasi, kirim satu preamble: satu kalimat langkah konkret berikutnya. Sekali per request.
2. Baca request beserta blok `Mattermost thread context` yang menyertainya (thread tempat mention terjadi; jawaban mengacu ke diskusi itu, bukan hanya kalimat mention), `PROJECT.yaml` (ownership repo), `memories/INDEX.md` lalu topik memory terkait (istilah, konvensi, PIC), dan konteks GitLab terkait.
3. Tentukan jenis request:
   - Read-only (pertanyaan kode, investigasi tanpa perbaikan, review MR orang lain, rekomendasi) → jawab langsung di surface asal, tanpa card, tanpa worktree.
   - Operasi non-coding (undraft/merge MR, metadata issue/MR, menjalankan pipeline atau deploy yang diizinkan) → kerjakan langsung dari sesi asal lewat API/tool yang tersedia, sesuai aturan operasi di bawah.
   - Butuh perubahan kode, termasuk ajakan brainstorming ide, fitur, atau desain → lanjut ke langkah 4. Brainstorming tidak dijalankan di sini; itu pekerjaan Planning.
4. Satu keputusan:
   - Request dan repo target cukup jelas untuk mulai desain → Planning. Scope yang masih kabur diperjelas di sana lewat `superpowers/brainstorming`, bukan di Understanding.
   - Konteks thread kurang (parent, keputusan, owner) → ReviewingDiscussion.

Permintaan eksplisit tidak dikonfirmasi ulang.

**Pekerjaan yang sudah punya issue.** Kenali issue dari link di thread, rujukan [RG] pada laporan gateway, thread yang sama dengan card yang dibuat sebelumnya, atau memory episodic. Tentukan kebutuhan request sebelum memilih jalur, termasuk ketika issue sudah di-assign ke CoDev:

- **Read-only:** status/progres, penjelasan keputusan atau hasil implementasi, investigasi tanpa perbaikan, dan review read-only → baca history sesi issue dengan `hermes -p default gitlab status --issue '<project-id>:issues:<iid>'`. Untuk detail, baca `session_search` memakai link `@session:` di output. Jika bukti cukup, jawab langsung di thread Mattermost dengan temuan dan link issue; tidak mengirim prompt atau giliran baru ke sesi GitLab. Jika history kosong, kurang lengkap, atau perlu fakta terbaru, baca konteks GitLab/kode langsung secara read-only. Sebutkan batas bukti yang masih ada; kekurangan history saja bukan alasan memakai `continue` atau meminta assignment.
- **Operasi non-coding:** kerjakan langsung dari sesi asal lewat API/tool, termasuk undraft/merge MR, metadata issue/MR, pipeline, deploy yang diizinkan, dan pengambilan screenshot dari aplikasi yang tersedia. Baca status terbaru objek tujuan dan otorisasi yang berlaku, lakukan operasi, lalu verifikasi hasil sebelum melaporkan. Untuk merge, periksa source/target branch, commit terbaru, approval dan checks wajib GitLab; jika belum siap, laporkan kondisi sebenarnya. Operasi ini tidak memerlukan assignment coding atau `continue`. Jika perlu perubahan kode atau resolusi konflik, pisahkan bagian itu sebagai task coding. Undraft tetap di AwaitingReview; approved atau merged mengikuti Completed.
- **Task coding:** sesi issue perlu membuat atau memperbaiki kode, menambah tes, menyelesaikan konflik, melanjutkan implementasi, mengubah scope implementasi, atau menerima jawaban/info untuk melanjutkan task coding → jalankan `hermes -p default gitlab continue --issue '<project-id>:issues:<iid>'` dari sesi ini untuk issue yang sudah di-assign ke CoDev. Balasan final: konfirmasi singkat pekerjaan yang akan dilakukan dengan bahasa yang berfokus pada kebutuhan user. Ikuti aturan laporan ke user di `SKILL.md`. `continue` ditolak → sebutkan sebabnya dan langkah yang bisa CoDev ambil sendiri; issue belum di-assign → tawarkan self-assign (lihat `tools/planning.md` langkah 4). Tidak pernah menyuruh user komentar atau mention di GitLab.

Request campuran → jawab bagian read-only dan jalankan operasi non-coding yang sudah bisa dilakukan dari sesi asal; gunakan `continue --request '<instruksi>'` hanya untuk bagian coding. Mention asli tetap ikut diteruskan oleh CLI; batasi `--request` ke bagian coding dan sebutkan bagian yang sudah ditangani agar sesi issue tidak mengulang operasi. Operasi yang menunggu hasil coding dilanjutkan sesi asal setelah laporan tiba.
