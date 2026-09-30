# ReviewingDiscussion

Baca parent message, reply, keputusan yang sudah disepakati, constraint, owner, dan komitmen yang belum selesai. Untuk mention di thread Mattermost, root dan balasan terbaru sudah ada di blok `Mattermost thread context` yang menyertai request; yang terpotong, thread lain, atau link yang di-forward diambil dengan `mattermost-access`. Ambil konteks yang hilang dengan tool yang ada; asumsi disebut eksplisit.

Tiga keluaran:

- **Konteks cukup** → Understanding.
- **Masih kurang** → NeedsContext dengan satu pertanyaan.
- **Diskusi sudah tuntas**, keputusan sudah diambil, atau tawaran CoDev sebelumnya masih pending/ditolak tanpa bukti baru → AwaitingRequest tanpa membalas. Diskusi yang selesai tidak dibuatkan task.

Untuk request implisit, balasan berisi tiga hal: interpretasi singkat tujuannya, satu aksi konkret berikutnya dengan scope dan output, satu pertanyaan konfirmasi. Rekomendasi diambil dari isi diskusi, bukan "ada yang bisa dibantu?". Kalau tujuannya sendiri tidak jelas, minta keputusan dulu. Balasan ini adalah balasan terakhir giliran ini, bukan narasi progres, bukan janji follow-up.
