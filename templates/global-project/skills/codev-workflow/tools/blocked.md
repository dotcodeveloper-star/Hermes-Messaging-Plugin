# Blocked

Blocker adalah permintaan, bukan laporan. Format:

```
@pic-dev blocker di <task>: <apa yang terjadi, 1–2 kalimat>.
Butuh: <keputusan / akses / info / merge #X> untuk lanjut.
```

- Tanpa narasi, tanpa daftar hal yang sudah dicoba kecuali diminta.
- Kebutuhan disebut persis: siapa, apa, untuk apa.
- Hal yang bisa CoDev sediakan sendiri di mesinnya bukan blocker.
- Blocker berupa card lain yang sedang dikerjakan CoDev (misalnya butuh merge #X dulu) tetap ditulis dengan format di atas, menyebut card itu. Kalau request datang dari thread Mattermost, laporan card #X nanti tiba di sesi thread itu sebagai giliran otomatis dan sesi itu meneruskannya ke sini lewat `gitlab continue --request`; tidak perlu polling atau mengejar.
- Card digeser ke list Blocked sesuai peta `## Board` repo (`tools/board.md`); peta `-` → tidak digeser.
- Kirim → AwaitingContext. Setelah kebutuhan terpenuhi → Planning.
