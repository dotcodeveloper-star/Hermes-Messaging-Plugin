# Penulisan issue GitLab melalui glab

Gunakan resep ini untuk membuat atau memperbarui card dengan deskripsi Markdown panjang dan payload JSON. Pemilihan template, scope, serta izin assignment mengikuti SKILL.md.

## Urutan eksekusi

1. Susun payload dari template yang telah dibaca. Tetapkan title, description, label yang telah diverifikasi, confidentiality, issue type, dan assignee sesuai otorisasi; untuk card yang belum di-assign gunakan `assignee_ids: []` agar pembuatan card tidak memulai implementasi.
2. Kirim JSON dengan header eksplisit `Content-Type: application/json` ketika memakai `--input -`; input JSON tanpa header ini dapat ditolak sebagai tipe media yang tidak didukung.
3. Simpan project ID, IID, dan `web_url` dari response. Baca kembali issue berdasarkan project ID dan IID, lalu verifikasi deskripsi, label, assignee, dan status yang dimaksud.
4. Untuk card berpasangan, buat card pertama dengan keterangan relasi sementara yang jujur, buat card kedua dengan URL pertama, lalu update deskripsi pertama memakai URL kedua. Baca kembali setiap target setelah write dan pastikan tidak ada placeholder tautan yang tersisa.
5. Laporkan hanya card yang telah diverifikasi. Jangan mengulang POST untuk menyelesaikan kegagalan pemeriksaan lokal setelah GitLab sudah mengembalikan IID, karena operasi create tersebut sudah berhasil.

## Contoh pengiriman JSON

Contoh berikut menerima payload yang telah disusun; tidak membaca atau menampilkan credential.

```python
import json
import subprocess

result = subprocess.run(
    [
        "glab", "api", "--hostname", host,
        "--method", "PUT" if issue_iid is not None else "POST",
        "--header", "Content-Type: application/json",
        endpoint, "--input", "-",
    ],
    input=json.dumps(payload),
    capture_output=True,
    text=True,
    timeout=60,
)
result.check_returncode()
issue = json.loads(result.stdout)
```

## Verifikasi dan retry

- Pisahkan keberhasilan write dari keberhasilan assertion read-back. Jika sudah memiliki IID, baca dan perbaiki issue itu; jangan membuat ulang card hanya karena assertion gagal.
- Periksa diff sebelum menyimpulkan deskripsi berubah. GitLab dapat menghapus newline penutup; bandingkan dengan payload yang sejak awal tidak memiliki newline penutup atau izinkan hanya perbedaan newline terakhir. Pertahankan isi Markdown dan identifier secara persis; jangan memakai normalisasi whitespace umum yang dapat menyembunyikan perubahan isi.
- Jika request gagal sebelum IID diterima atau hasilnya tidak pasti, cari issue dengan title yang dimaksud dan verifikasi author, scope, serta deskripsinya sebelum mengulang create. Pencarian kosong akibat akses atau hasil terpotong bukan bukti issue belum dibuat.
- Pada update, kirim hanya field yang hendak diubah agar label, assignee, dan metadata lain tidak ikut tertimpa.

## Metadata MR dan reviewer

- Untuk field array seperti `reviewer_ids`, kirim JSON eksplisit, misalnya `{"reviewer_ids": [398]}`, melalui `glab api --method PUT --header 'Content-Type: application/json' --input '<file-json>'`. Field CLI `-F 'reviewer_ids[]=398'` dapat diabaikan tanpa error; read-back wajib memeriksa ID reviewer, bukan hanya status HTTP.
- Untuk undraft, baca title terbaru dan hapus hanya prefix draft yang dikenali. Verifikasi `draft: false` pada GET setelah update; perubahan title tidak mengubah author atau assignee.
- Pertahankan reviewer existing kecuali pengguna meminta penggantian. Assignment reviewer berbeda dari assignment pelaksana MR; kirim hanya field yang diotorisasi.

## Pembaruan format test scenario pada card existing

1. Baca deskripsi lengkap dan metadata target, lalu baca template terbaru repo tujuan. Ambil tabel hanya dari section pengujian, karena tabel lain dapat berisi kontrak API yang tidak boleh berubah.
2. Pertahankan ID dan Expected Result setiap baris. Pisahkan kolom gabungan menjadi Scenario yang menyebut kondisi/perilaku dan Test Steps yang berisi tindakan bernomor. Jadikan setiap skenario mandiri: sebutkan halaman, jenis fixture, nilai request, dan cara memeriksa hasil tanpa hanya menulis “ulangi skenario sebelumnya”. Untuk edit dengan field master disabled, arahkan QA membuka fixture terkait, bukan memilih ulang field yang terkunci.
3. Cocokkan ID sebelum dan sesudah, pertahankan status eksekusi serta catatan QA, dan pastikan semua teks di luar tabel pengujian tetap sama. Pemisahan kolom bukan izin menambah scope atau menandai test lulus.
4. Baca ulang target tepat sebelum PUT. Jika deskripsi berubah sejak pembacaan awal, gabungkan perubahan terbaru dahulu agar edit tim tidak tertimpa. Kirim hanya `description`, kemudian GET target yang sama untuk memverifikasi tabel akhir dan memastikan title, labels, assignees, milestone, serta state tetap seperti sebelum write.
