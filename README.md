# Novel → EPUB (Türkçe çeviri)

Bir web novel linki verirsin: araç bölüm listesinin tamamını alır, bölümleri indirip denetler,
istersen Gemini ile edebi bir Türkçeye çevirir ve hepsini **tek bir EPUB** yapar. EPUB'u
telefondaki kitap uygulamasıyla (Moon+ Reader, ReadEra, Apple Books, Google Play Kitaplar…) okursun.

## Kurulum (Windows uygulaması — önerilen)

1. GitHub'da bu deponun **Releases** sayfasından (sağ tarafta "Novel EPUB — son sürüm") **NovelEPUB.exe**'yi indir.
2. Çift tıkla. Kurulum yok; kendi penceresinde açılır (tarayıcı ya da siyah konsol penceresi açılmaz).
   - İmzasız olduğu için Windows ilk seferde "Windows bilgisayarınızı korudu" diyebilir:
     **Ek bilgi → Yine de çalıştır**.
   - Güvenlik duvarı izin sorarsa **Özel ağlar**'a izin ver (telefondan indirme için).
3. **Ayarlar**'a Gemini API anahtarını gir (Windows Kimlik Bilgisi Yöneticisi'nde saklanır).

Veriler (kitaplık, EPUB'lar, ayarlar) **Belgeler\Novel EPUB** klasöründe durur. Eski kurulumun
`kutuphane` klasörünü oraya kopyalarsan kaldığın yerden devam eder; ya da `NovelEPUB.exe`'yi eski klasörün
içine koy (yanında `kutuphane` varsa orayı kullanır). "Klasörü aç" düğmesi EPUB'ların olduğu klasörü açar.
Uygulama kayıtları: `Belgeler\Novel EPUB\uygulama.log`.

Exe, her `main` push'unda GitHub Actions'ta (Windows) derlenir, testlerden ve pencere açmadan bir öz-testten
geçer, sonra Releases'e konur (`.github/workflows/windows-uygulama.yml`).

### Geliştirici kurulumu (kaynak koddan)

1. [Python 3.10+](https://www.python.org/downloads/) kur ("Add python.exe to PATH").
2. `baslat.bat` (tarayıcıda açar) ya da `pip install pywebview` sonrası `python uygulama.py` (pencerede açar).

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

## Kaynaklar ve hedef dil

- **Web sitesi:** freewebnovel, novelbin, NovelFull ailesi (novelfull.com, readnovelfull.com, allnovelfull.net /
  novgo.net, novelfull.net), Royal Road için özel destek; diğer siteler genel okuyucuyla denenir.
  **Siteyi test et** düğmesi bölüm listesini ve ilk bölümü deneyip sonucu gösterir.
- **Dosya:** EPUB, PDF (metinli; taranmış PDF için OCR gerekir), Word (.docx), TXT/MD, HTML. Bölümler dosyanın
  kendi yapısından (EPUB içindekiler, PDF yer imleri, Word başlıkları) ya da "Chapter/Bölüm/第…章" başlıklarından
  ayrılır; yoksa ~3000 kelimelik parçalara bölünür. PDF'te satır sonu kırılmaları birleştirilir, sayfa numaraları
  ve tekrarlanan üst/alt bilgiler atılır. Çıktı her zaman EPUB'dır.
- **Hedef dil:** Türkçe, English, Deutsch, Français, Español, Italiano, Português, Nederlands, Polski, Русский,
  Українська, Azərbaycan dili, العربية, فارسی, Bahasa Indonesia, 日本語, 简体中文, 한국어. Türkçeye özel kurallar
  (-dı'lı anlatım, sen/siz, "Cilt N Bölüm M") yalnız Türkçede uygulanır. Her dilin çevirisi, sözlüğü ve hafızası
  ayrı tutulur (Türkçe: `ceviri/`, `sozluk.json`; diğerleri: `ceviri-en/`, `sozluk-en.json`…).
- **Okuduğum siteleri bul:** bu PC'deki Brave/Chrome/Edge geçmişi ve yer işaretlerinden novel/bölüm adreslerini
  site site sayar, hangisinin özel desteği olduğunu gösterir (yalnız yerelde okunur). Telefondaki geçmiş için iki
  cihazda da Brave Sync'te "Geçmiş" ve "Yer işaretleri" açık olmalı.
  **Root'lu Android telefon:** "📱 Telefondan oku" düğmesi telefonu USB ile okur: Google'ın resmî `adb` aracını
  (yoksa onayınla indirir), telefonda USB hata ayıklama ve root (`su`) iznini kullanarak Brave/Chrome/Edge'in
  `History`, `History-wal` ve `Bookmarks` dosyalarını `Veri klasörü\telefon-gecmis\` altına kopyalar ve tarar.

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
- **Ücretsiz Gemini sınırı:** ücretsiz katmanda kota **istek sayısıyla** ve **model başına** sayılır
  (ör. `gemini-3.8-flash` için günde 20 istek). Araç bu yüzden **bölümleri uzunluğuna göre otomatik paketler**:
  her bölümün kelime (Çince/Japoncada karakter) sayısından Türkçe çıktının kaç token tutacağını tahmin eder,
  tek isteğe bütçeye sığdığı kadar bölüm koyar (ör. ~2.800 kelimelik bölümlerde 4, kısa bölümlerde daha çok).
  Her yanıttan sonra gerçek token kullanımını ölçüp tahminini düzeltir; yanıt kesilir ya da eksik gelirse
  bütçeyi küçültüp o bölümleri tek tek çevirir, sorunsuz yanıtlarda bütçeyi yavaşça büyütür.
  Ayarlar → "Bir istekte en fazla kaç bölüm": 0 = otomatik (önerilen), sayı verirsen üst sınır olur. Ayrıca Ayarlar'daki model listesini sırayla kullanır: biri dolunca sıradakine geçer
  (varsayılan `gemini-flash-latest, gemini-flash-lite-latest`). Hepsi dolunca o ana kadar çevrilen
  bölümlerle **kısmi EPUB** çıkarır; kota yenilenince aynı linkle başlat, kaldığı yerden sürer.
  Uzun bir kitabı ücretsiz kotayla bitirmek haftalar sürer; hızlı bitirmek istersen AI Studio'da
  faturalandırmayı aç (kullandıkça öde; 680 bölümlük bir kitap kabaca 3M girdi + 5M çıktı token eder,
  güncel fiyat için AI Studio'daki fiyat sayfasına bak) ve bir bütçe sınırı koy.
- **Kalite özellikleri:**
  - *Redaksiyon turu* (ana ekranda kutucuk, varsayılan açık): her paket çevrildikten sonra model kaynakla
    taslağı yan yana okuyup editör gibi düzeltir (anlam, atlanmış cümle, akıcılık, hitap tutarlılığı, imla).
    İstek sayısını ikiye katlar. Redakte edilmemiş eski çeviriler sonraki çalıştırmada redakte edilir.
  - *Hikâye hafızası* (`kutuphane/<kitap>/hafiza.json`): kısa olay özeti + karakter notları (kim kimdir,
    kime nasıl hitap eder). Her istekte metinde adı geçen karakterlerin notları modele gider, her yanıtla güncellenir.
  - *Düşünme seviyesi* (Ayarlar): düşük / orta (varsayılan) / yüksek.
  - *Sözlük kontrolü*: "ilk 20 bölümden sonra dur" kutucuğu; sonra **Kitaplığım · Sözlük · Hafıza**
    bölümünden sözlüğü düzelt, ilgili bölümleri "Yeniden çevrilecek" ile işaretle ve aynı linkle Başlat.
- **Daha fazla kalite ayarı:**
  - *Sonraki bölüme bakma:* her isteğe sonraki bölümün ilk 3 paragrafı (çevrilmeden) bağlam olarak eklenir.
  - *Kitaba özel çeviri talimatı* (Kitaplığım ekranı, `talimat.txt`): üslup, hitaplar, zaman kipi gibi kurallar
    her isteğin sistem talimatına eklenir. Terim karşılıkları için yine sözlüğü kullan.
  - *Sıcaklık* (Ayarlar, varsayılan 0,7): anlatımı doğal Türkçe roman diline uyarlayacak esneklik;
    redaksiyon en çok 0,5 ile çalışır. Anlatım geniş zamanla yazılmış olsa da -dı'lı geçmiş zamanla çevrilir.
  - *Eski çeviriler korunur:* "Yeniden çevrilecek" eski çeviriyi `ceviri_eski/` klasörüne taşır;
    "Eskiye dön" en son yedeği geri getirir.
  - *Süslü Unicode filigranlar* (ör. 𝐟𝗿𝐞𝚎𝚠𝐞𝚋𝕟𝐨𝚟𝐞𝕝.𝕔𝕠𝚖) ve "End of b1c…" notları kodla silinir; önbellekteki
    eski indirmeler de çeviriden önce yeniden temizlenir.
- **Tutarlılık denetimleri:**
  - *Sen/siz hitap tablosu* (`hafiza.json` → `address`): model bir konuşan–dinleyen çiftinin hitabını ilk
    belirlediğinde kaydedilir ve kalıcıdır; o iki karakter aynı metinde geçtikçe kural modele (çeviri ve redaksiyon) gider.
    Yanlış kaydedilmiş bir hitabı `hafiza.json`'dan elle düzeltebilirsin.
  - *Karakter adları takma adlarıyla eşleşir* ("Hou Fei (Fei Fei)" → metinde "Fei Fei" geçince de notu gider;
    "Hou" gibi parçalar "house" içinde eşleşmez).
  - *İngilizce kalmış kelimeler:* kaynakta küçük harfle geçip taslakta aynen kalan kelimeler (ör. "berserk",
    "ethereal") kayıtta gösterilir ve redaksiyona "düzelt" diye iletilir.
  - Redaksiyona önceki bölümün son paragrafları da bağlam olarak gider.
  - "End of c1b13", "C6B2'nin sonu.", tek "." satırları hem kaynakta hem çeviride silinir; "***", "..." gibi
    sahne geçişi/sessizlik satırları korunur.
- **API anahtarı** Windows'ta Kimlik Bilgisi Yöneticisi'nde (şifre kasası) saklanır; eski sürümde `ayarlar.json`'a
  yazılmış anahtar ilk açılışta oraya taşınıp dosyadan silinir. Kasa yoksa (ör. bazı Linux kurulumları) dosyada kalır.
- **Hata olunca durmaz:** ağ kopması, Google yoğunluğu (503), dakikalık sınır (429) ya da bozuk yanıtta
  en çok 60 sn bekleyip yeniden dener (10 deneme). Sürerse aynı isteği listedeki diğer modelle dener;
  o da olmazsa o bölümleri atlar, EPUB'da "[Çevrilemedi]" başlığıyla orijinal metin olarak bırakır ve
  devam eder (tekrar başlatınca yeniden denenir). Art arda 3 istek başarısızsa 5 dk bekler. Yalnızca
  **seçili modellerin hepsinin günlük kotası bitince** ya da API anahtarı geçersizse durur. "Durdur"
  bekleme sırasında da çalışır.
- **Model:** Ayarlar → *Listele* anahtarının erişebildiği Gemini modellerini getirir; kutuya virgülle
  birden fazla model yazabilirsin (ör. `gemini-3.8-flash, gemini-3.7-flash, gemini-flash-lite-latest`). Daha edebi sonuç için bir Pro modeli seçebilirsin
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
