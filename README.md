# Novel → EPUB (Türkçe çeviri)

Bir web novel linki verirsin: araç bölüm listesinin tamamını alır, bölümleri indirip denetler,
istersen Gemini ile edebi bir Türkçeye çevirir ve hepsini **tek bir EPUB** yapar. EPUB'u
telefondaki kitap uygulamasıyla (Moon+ Reader, ReadEra, Apple Books, Google Play Kitaplar…) okursun.

## Kurulum (Windows)

1. [Python 3.10+](https://www.python.org/downloads/) kur ("Add python.exe to PATH" kutusunu işaretle).
2. Bu klasörde **`baslat.bat`**'a çift tıkla. İlk açılışta gerekli paketleri kurar, sonra tarayıcıda
   arayüz açılır (`http://127.0.0.1:5000`).
3. **Ayarlar**'ı aç, [Google AI Studio](https://aistudio.google.com/apikey)'dan aldığın ücretsiz
   Gemini API anahtarını yapıştır, **Kaydet**. (Anahtar yalnızca bu PC'de `ayarlar.json`'da durur.)

Linux/macOS: `./baslat.sh`

## Kullanım

- Linki yapıştır (novel ana sayfası ya da herhangi bir bölüm linki olur), istersen bölüm aralığı ver,
  **Başlat**.
- İlerleme çubuğu ve kayıt satırları canlı akar. Bitince EPUB "Hazır kitaplar" listesine düşer.
- **Telefondan:** PC ile telefon aynı Wi‑Fi'deyse, başlatınca konsolda yazan
  `http://192.168.x.x:5000` adresini telefonda aç; EPUB'a dokununca doğrudan telefona iner.
  (Windows güvenlik duvarı ilk seferde Python için izin sorarsa "Özel ağ"a izin ver.)

Komut satırı da var:

```
python -m novel_epub https://freewebnovel.com/novel/stellar-transformations --bas 1 --son 100 --cevir
```

## Neler yapıyor

| Aşama | Ayrıntı |
|---|---|
| Bölüm listesi | freewebnovel: `?ajax=chapters` ucundan tüm liste (680 bölüm ≈ 4 istek). novelbin: `/ajax/chapter-archive`. Diğer siteler: sayfadaki bölüm bağlantıları, bulunamazsa "Sonraki" bağlantılarını izleyerek. |
| İndirme | Tarayıcı taklidi (`curl_cffi`) ile Cloudflare'in basit kontrolünü geçer; istekler arası bekleme + 3 paralel işçi; hatada artan beklemeyle yeniden dener. |
| Temizlik | Reklam kutuları, script'ler, "Read latest chapters at…", "Translated by/Edited by" satırları, tekrar eden başlık ve art arda kopya paragraflar atılır. |
| Denetim | Boş/çok kısa bölüm, engel sayfası, aynı içerikli bölümler ve numara boşlukları raporlanır; sorunlu bölümler ikinci turda yavaşça yeniden indirilir. |
| Çeviri | Bölüm paragraf sınırları korunarak parçalanır, Gemini'ye JSON olarak gider. Kitaba özel **terim sözlüğü** (`kutuphane/<kitap>/sozluk.json`) her parçada verilir ve model yeni terim buldukça büyür; böylece "Qi Condensation" kitap boyunca hep aynı karşılıkla çevrilir. Önceki paragraflar bağlam olarak gider (Çince/Japonca öznesiz cümleler için). |
| Kaldığı yerden | İnen ve çevrilen her bölüm `kutuphane/`'de saklanır. Yarıda kesersen ya da API sınırına takılırsan tekrar başlat; yalnız eksikler yapılır. |
| EPUB | Kapak, künye sayfası, içindekiler, okunaklı CSS. Dosya `cikti/` klasörüne yazılır. |

## İpuçları

- **Terimleri düzeltmek:** `kutuphane/<kitap>/sozluk.json`'u aç, beğenmediğin karşılığı değiştir.
  Yeniden çevirmek istediğin bölümlerin `kutuphane/<kitap>/ceviri/0xxxx.json` dosyalarını sil, tekrar başlat.
- **Ücretsiz Gemini sınırı:** günlük istek sınırı dolarsa araç bekler/yeniden dener; dolmuşsa
  durdur, ertesi gün aynı linkle başlat, kaldığı yerden sürer. Uzun kitapları aralık aralık
  (ör. 1–200, 201–400) yapmak rahattır.
- **Model:** Ayarlar → *Listele* anahtarının erişebildiği Gemini modellerini getirir. Varsayılan
  `gemini-flash-latest` (her zaman güncel Flash). Daha edebi sonuç için bir Pro modeli seçebilirsin
  (daha yavaş, ücretsiz sınırı daha dar).
- **Bot koruması sert olan siteler** (tam Cloudflare doğrulaması isteyenler) bu araçla açılmayabilir;
  o durumda tarayıcı eklentisi [WebToEpub](https://github.com/dteviot/WebToEpub) ile orijinal EPUB'u indirip
  çeviriyi ayrı yapmak gerekir (bu araca "EPUB çevir" modu eklenebilir).

## Durum

- freewebnovel.com: sınandı (liste + bölüm + EPUB).
- novelbin: yazıldı, **sınanmadı** (geliştirme ortamından siteye erişilemedi). Çalışmazsa
  bir novelbin linkiyle hata kaydını gönder, düzeltelim.
- Genel kaynak: basit sitelerde çalışır, her sitede garanti değil.

Kişisel okuma içindir; sitelerin kullanım koşullarına ve yazar/çevirmen emeğine saygı göster.

## Geliştirme

```
pip install -r requirements.txt pytest
python -m pytest -q
```

Yeni site eklemek için `novel_epub/sources/` altına `Source` alt sınıfı yaz (`novel()` ve `chapter()`),
`sources/__init__.py`'deki `SOURCES` listesine ekle.
