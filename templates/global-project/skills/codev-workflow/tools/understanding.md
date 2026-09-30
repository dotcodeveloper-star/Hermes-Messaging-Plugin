# Understanding

1. Kalau butuh investigasi, kirim satu preamble: satu kalimat langkah konkret berikutnya. Sekali per request.
2. Baca request beserta blok `Mattermost thread context` yang menyertainya (thread tempat mention terjadi; jawaban mengacu ke diskusi itu, bukan hanya kalimat mention), `PROJECT.yaml` (ownership repo), `memories/INDEX.md` lalu topik memory terkait (istilah, konvensi, PIC), dan konteks GitLab terkait.
3. Tentukan jenis request:
   - Read-only (pertanyaan kode, investigasi tanpa perbaikan, review MR orang lain, rekomendasi) → jawab langsung di surface asal, tanpa card, tanpa worktree.
   - Butuh perubahan kode, termasuk ajakan brainstorming ide, fitur, atau desain → lanjut ke langkah 4. Brainstorming tidak dijalankan di sini; itu pekerjaan Planning.
4. Satu keputusan:
   - Request dan repo target cukup jelas untuk mulai desain → Planning. Scope yang masih kabur diperjelas di sana lewat `superpowers/brainstorming`, bukan di Understanding.
   - Konteks thread kurang (parent, keputusan, owner) → ReviewingDiscussion.

Permintaan eksplisit tidak dikonfirmasi ulang.

**Pekerjaan yang sudah punya issue.** Kalau request menyangkut issue yang sudah di-assign ke CoDev (link issue di thread, rujukan [RG] pada laporan gateway, thread yang sama dengan card yang dibuat sebelumnya, atau memory episodic), jangan dijawab, dianalisis ulang, atau diteruskan ke user: jalankan `hermes -p default gitlab continue --issue '<project-id>:issues:<iid>'` dari sesi ini. Ini berlaku untuk perintah baru, jawaban atas pertanyaan atau blocker yang dikirim sesi issue ke thread ini, dan perubahan scope. Balasan final: satu kalimat bahwa instruksi diteruskan ke sesi issue, plus link issue. Tidak pernah menyuruh user komentar atau mention di GitLab. `continue` ditolak → sebutkan sebabnya dan langkah yang bisa CoDev ambil sendiri; issue ada tapi belum di-assign → tawarkan self-assign (lihat `tools/planning.md` langkah 4).
