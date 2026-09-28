# Status card di board

Card bergerak di board yang tim sudah pakai, mengikuti progres nyata. Board GitLab digerakkan label (satu list = satu label), jadi "menggeser card" berarti mengganti label status-nya. CoDev tidak pernah membuat label atau list baru, tidak mengganti nama list, dan tidak pernah memindah card ke Done/Closed. Dipakai di Init (peta dibuat), Working, Blocked, AwaitingReview, AddressingFeedback, Completed (peta dipakai).

## 1. Peta board per repo (Init; diulang kalau board berubah)

Baca board yang **sudah ada** lewat API sebelum memutuskan label apa pun; nama label tidak ditebak dari kebiasaan umum.

```
GET projects/<id>/boards
GET projects/<id>/boards/<board_id>/lists
```

Tiap list membawa `label.name` (list milestone/assignee/iteration tidak dipakai). Kalau project punya lebih dari satu board, pilih yang benar-benar dipakai tim: cek label status pada 20 issue terbaru dan pilih board yang list-nya cocok; masih ragu → tanya sekali di thread onboarding, satu pertanyaan dengan opsi nama board-nya. Project tanpa board sendiri tapi issue-nya memakai label grup → `GET groups/<group-id>/boards` dengan aturan yang sama.

Petakan list yang ada ke state CoDev; state tanpa list yang cocok ditandai `-`, bukan diberi label baru:

| State CoDev | List board yang biasanya cocok |
|---|---|
| Working (masuk pertama kali, dan kembali dari AddressingFeedback) | Doing / In Progress / Development |
| Blocked | Blocked / On Hold / Waiting |
| AwaitingReview | Review / Code Review / In Review |
| Completed langkah 2 (handoff QA) | Testing / QA / Ready for QA |

Pencocokan yang tidak jelas (misalnya ada "In Progress" dan "Development" sekaligus, atau "Review" bisa berarti review PM) ditanyakan di thread onboarding sekali, satu pertanyaan per repo dengan opsinya; tidak dikejar, dan sampai dijawab list itu `-`.

Tulis hasilnya ke `memories/semantic/repositories/<gitlab-id>.md`, section `## Board`, lalu index seperti biasa:

```markdown
## Board
board: <board_id> "<nama board>" — verified_at: <tanggal>
scoped: ya | tidak            # label `status::x` saling eksklusif, GitLab mencopot yang lama sendiri
doing: "<label persis>"
blocked: "<label persis>" | -
review: "<label persis>" | -
testing: "<label persis>" | -
```

Project tanpa board sama sekali → `## Board: tidak ada`, dan label card tidak pernah disentuh CoDev.

## 2. Menggeser card (Working, Blocked, AwaitingReview, AddressingFeedback, Completed)

- Baca `## Board` di memory repo dulu. Tidak ada, `verified_at` lebih dari 30 hari, atau label tujuan sudah tidak ada di board → refresh peta (langkah 1) dulu, jangan menebak.
- Geser hanya pada transisi state nyata, sekali per transisi:

```
PUT projects/<id>/issues/<iid>
  add_labels=<label tujuan>
  remove_labels=<label status lain dari peta yang sedang terpasang>   # dilewati kalau scoped
```

  Label lain di issue (prioritas, tipe, area, milestone) tidak disentuh.
- Setelah PUT, baca ulang issue dan pastikan label tujuan terpasang. Gagal → satu kalimat di balasan final ("card belum bisa digeser ke Review: <sebab>"), tanpa retry berulang; ini bukan blocker.
- Card yang dipindah manual oleh tim ke list lain tidak ditarik balik. Transisi berikutnya menimpanya sesuai progres nyata.
- State yang petanya `-` → card tidak digeser untuk state itu, dan tidak ada label yang diciptakan.
- Tidak pernah: Done/Closed/Merged, list milestone/assignee/iteration, membuat atau mengubah label, list, atau board.
