---
name: codev-workflow
description: Menjalankan state machine CoDev dari Init sampai Completed. Load saat CoDev masuk state mana pun yang punya aksi; SKILL.md ini hanya router, perilaku tiap state ada di tools/<state>.md dan dibaca hanya saat state itu aktif.
---

# codev-workflow

CoDev selalu berada di tepat satu state. Skill ini menentukan tool mana yang dibaca untuk state itu. Baca satu tool per state, bukan semuanya. Membaca tool bukan izin untuk mengirim pesan, meng-assign, atau membersihkan apa pun.

## Routing

| State | Tool |
|---|---|
| Init | `tools/init.md` |
| Understanding | `tools/understanding.md` |
| ReviewingDiscussion | `tools/reviewing-discussion.md` |
| NeedsContext | `tools/needs-context.md` |
| Planning | `tools/planning.md` |
| Working (Inspecting, Implementing, Validating, PreparingMR) | `tools/working.md` |
| AwaitingReview (aksi masuk: minta review) | `tools/awaiting-review.md` |
| AddressingFeedback | `tools/addressing-feedback.md` |
| Blocked | `tools/blocked.md` |
| Completed | `tools/completed.md` |
| Lintas state: setup & operasi app per repo | `tools/runbook.md` (dibaca dari Init, Working, Completed) |

State idle (AwaitingRequest, AwaitingContext, AwaitingAssignment, AwaitingReview) diam sampai ada trigger dari gateway, tanpa polling, tanpa mengejar. Pengecualian: AwaitingReview punya satu aksi saat masuk (minta review ke PIC dan notify thread asal, `tools/awaiting-review.md`) dan satu reminder kalau MR lewat batas waktu yang disepakati tim; di AwaitingAssignment, jawaban "ya" atas konfirmasi lanjut dari Planning memicu self-assign sesuai `tools/planning.md`.

## Aturan lintas state

- Kode hanya disentuh di Working dan AddressingFeedback, dan hanya untuk issue GitLab yang di-assign ke CoDev. Diverifikasi ulang setiap resume.
- Read-only (pertanyaan, investigasi tanpa perbaikan, review MR orang lain) selesai di Understanding tanpa masuk Planning.
- Blocker di state mana pun → `tools/blocked.md`. Yang bisa CoDev sediakan sendiri di mesinnya bukan blocker.
- Dari Mattermost, apa pun yang ditujukan ke pekerjaan yang sudah punya issue ter-assign (perintah baru, jawaban atas pertanyaan atau blocker sesi issue, perubahan scope) diteruskan CoDev sendiri dengan `hermes -p default gitlab continue --issue '<project-id>:issues:<iid>'`, di state mana pun. Sesi Mattermost tidak pernah menyuruh user komentar atau mention di GitLab.
- Satu preamble per request, di awal Understanding, kalau memang butuh investigasi.

## Skill superpowers

`superpowers/` di direktori skill bersama adalah salinan utuh skills obra/superpowers 6.4.1. Muat dengan `skill_view("superpowers/<nama>")`; referensi `superpowers:<nama>` di dalam skill-skill itu resolve ke path yang sama. Jangan panggil nama telanjangnya: `test-driven-development`, `systematic-debugging`, dan `requesting-code-review` juga ada sebagai skill bawaan profil, dan nama ambigu ditolak `skill_view`.

| State | Skill |
|---|---|
| Planning | `superpowers/brainstorming` → `superpowers/writing-plans` |
| Working | `superpowers/using-git-worktrees` → `superpowers/executing-plans` → `superpowers/test-driven-development` → `superpowers/requesting-code-review` → `superpowers/finishing-a-development-branch` |

Detailnya ada di tool state. Terjemahan ke konteks CoDev, berlaku untuk semua skill superpowers:
- "Your human partner" = tim di surface asal (thread Mattermost, issue/MR GitLab). Sesi Working bertanya lewat issue GitLab.
- "Dispatch a subagent" = `delegate_task`; kalau tidak tersedia, kerjakan inline.
- Aturan codev-workflow yang sudah tertulis (lokasi worktree, nama branch, MR sebagai satu-satunya jalur integrasi) adalah *declared preference* bagi skill itu: tidak ditanyakan ulang.
- Kode, spec file, dan plan file hanya ditulis di Working dan AddressingFeedback. Sebelum itu, spec dan plan hidup di surface asal lalu di issue GitLab.
- Brainstorming adalah bagian Planning, bukan Understanding: Understanding hanya memutuskan jenis request. Output Planning selalu plan hasil `writing-plans` di card, termasuk untuk path bounded; execution method selalu Native.
