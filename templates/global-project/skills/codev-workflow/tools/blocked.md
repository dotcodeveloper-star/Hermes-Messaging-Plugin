# Blocked

Blocker adalah permintaan, bukan laporan. Format:

```
@pic-dev blocker di <task>: <apa yang terjadi, 1–2 kalimat>.
Butuh: <keputusan / akses / info / merge #X> untuk lanjut.
```

- Tanpa narasi, tanpa daftar hal yang sudah dicoba kecuali diminta.
- Kebutuhan disebut persis: siapa, apa, untuk apa.
- Hal yang bisa CoDev sediakan sendiri di mesinnya bukan blocker.
- Card digeser ke list Blocked sesuai peta `## Board` repo (`tools/board.md`); peta `-` → tidak digeser.
- Kirim → AwaitingContext. Setelah kebutuhan terpenuhi → Planning.
