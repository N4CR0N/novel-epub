# WebNovel Downloader & Translator

[English](README.md) · **Türkçe**

Bir web novel linki ya da dosya verirsin: araç bölüm listesinin tamamını alır, bölümleri indirip denetler,
istersen yapay zekâyla edebi bir dile çevirir (Türkçe ve 17 dil daha) ve hepsini **tek bir EPUB** yapar (Word, HTML,
TXT ya da Markdown da seçilebilir).
EPUB'u telefondaki kitap uygulamasıyla (Moon+ Reader, ReadEra, Apple Books, Google Play Kitaplar…) okursun.

## Kurulum (Windows uygulaması)

1. **[WebNovelDownloaderTranslator.exe](https://github.com/N4CR0N/novel-epub/releases/latest/download/WebNovelDownloaderTranslator.exe)**'yi indir (son sürüm). Tüm sürümler
   [Releases](https://github.com/N4CR0N/novel-epub/releases) sayfasında; sürüm numarası uygulamada adın altında yazar.
2. Çift tıkla. Kurulum yok; kendi penceresinde açılır.
   - İmzasız olduğu için Windows ilk seferde "Windows bilgisayarınızı korudu" diyebilir: **Ek bilgi → Yine de çalıştır**.
     Her sürüm notunda dosyanın SHA-256 özeti var; PowerShell'de `Get-FileHash WebNovelDownloaderTranslator.exe` ile karşılaştırabilirsin.
3. **Yapay zekâ** sekmesine API anahtarını yapıştır, **Ekle**. Anahtarın hangi sağlayıcıya ait olduğu ve erişebildiğin
   modeller kendiliğinden bulunur; kullanmak istediklerini işaretle.

Veriler (kitaplık, EPUB'lar, ayarlar) **Belgeler\WebNovel Downloader & Translator** klasöründe durur. Eski
"Novel EPUB" sürümünü kullandıysan **Belgeler\Novel EPUB** klasörü olduğu gibi kullanılır (kitaplık, sözlükler,
anahtar korunur). Exe'nin yanında `kutuphane` klasörü varsa orası kullanılır (taşınabilir kullanım).
Uygulama kayıtları: veri klasöründe `uygulama.log`.

Exe, her `main` push'unda GitHub Actions'ta (Windows) derlenir, testlerden ve pencere açmadan bir öz-testten
geçer, sonra Releases'e konur (`.github/workflows/windows-uygulama.yml`).

### Geliştirici kurulumu (kaynak koddan)

1. [Python 3.10+](https://www.python.org/downloads/) kur ("Add python.exe to PATH").
2. `gelistir.bat` (pencerede açar) ya da `baslat.bat` (tarayıcıda açar).

## Android uygulaması

Aynı uygulama Android telefonlarda da çalışır (Android 7.0 ve üstü, 64 bit): indirme, yapay zekâ çevirisi ve kitaplık
telefonun kendisinde; ekran kapalıyken bildirim ilerlemeyi gösterir.

1. Telefonda **[WebNovelDownloaderTranslator.apk](https://github.com/N4CR0N/novel-epub/releases/latest/download/WebNovelDownloaderTranslator.apk)**'yı indirip aç. Android bir kez tarayıcından uygulama
   kurmaya izin ister; izin ver. Güncellemeler eski sürümün üzerine kurulur, kitaplığın kalır.
2. **Yapay zekâ** bölümüne bilgisayardaki gibi anahtarını yapıştır.
3. Biten kitaba dokun: **İndirilenler/WebNovel**'e kaydedilir ve okuma uygulamanla açılır. Tarayıcında bir roman
   sayfasını **Paylaş → WebNovel** ile göndererek linki de doldurabilirsin.

Telefonda sayfalar Android'in kendi bağlantısıyla açılır; bunu reddeden siteler (ör. Royal Road) yalnız Windows
uygulamasında çalışır.

## Kullanım

- **Arayüz:** sağ üstten tema (açık / koyu / sistem) ve arayüz dili (Türkçe, English, Deutsch, Español, Русский);
  ilk açılışta cihazın dili seçilir. Pencere ilk açılışta ekranı kaplar, sonra son boyutu hatırlar.

- **İndir ve çevir:** linki yapıştır (roman sayfası ya da herhangi bir bölüm), istersen bölüm aralığı ver, **Başlat**.
  "Siteyi dene" bölüm listesini ve ilk bölümü deneyip sonucu gösterir.
- İlerleme çubuğu ve kayıt canlı akar. Bitince EPUB "Hazır kitaplar" listesine düşer.
- **Denetle ve düzelt:** Kitaplık'taki **Denetle ve düzelt** bütün çevrilmiş bölümleri tarar: İngilizce kalmış
  kelimeler ("Dean Ming"), sözlüğe uymayan terimler, eski/ağdalı kelimeler, atlanmış ya da tekrar eden paragraflar,
  kaynakla uyuşmayan sayılar, bölüm başlığı ve seviye yazımı. Yalnız sorunlu paragraflar yapay zekâya gider; yeni
  çeviriler de aynı denetimden kendiliğinden geçer.
- **Oku:** hazır EPUB'un yanındaki **Oku**'ya bas. Gömülü okuyucuda sayfa çevirme (kenarlara dokun, kaydır ya da ok
  tuşları) veya kaydırarak okuma, gündüz / sepya / gece / siyah tema, yazı boyutu, satır aralığı, kenar boşluğu,
  tırnaklı ya da düz yazı tipi ve aranabilir içindekiler var; kaldığın yeri hatırlar.
- **Telefondan:** "Hazır kitaplar"ın altında yazan `http://192.168.x.x:5000` adresini aynı Wi‑Fi'deki telefonda aç;
  kitapları oradan indirip okuyabilirsin. Güvenlik duvarı sorarsa **Özel ağlar**'a izin ver.
- **Google Drive:** "Hazır kitaplar"ın altındaki panelden Google ile giriş yap. Biten kitaplar Drive'ındaki
  "WebNovel Downloader & Translator" klasörüne yüklenir (otomatik ya da **Drive ↑** ile); başka cihazda tek dokunuşla
  indirilir. **Kitaplığı yedekle** indirilen ve çevrilen bölümleri, sözlükleri ve okuma yerlerini tek zip olarak kaydeder.

Komut satırı:

```
set GEMINI_API_KEY=...            (ya da OPENAI_API_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, OPENROUTER_API_KEY…)
python -m novel_epub https://freewebnovel.com/novel/stellar-transformations --cevir ^
       --model "gemini/gemini-3.8-flash, gemini/gemini-3.1-flash-lite"
```

Anahtar/model verilmezse uygulamanın kayıtlı ayarları kullanılır.

## Yapay zekâ sağlayıcıları

Çeviri, uygulamanın kendi hafif istemcisiyle yapılır (`novel_epub/llm.py`: OpenAI uyumlu uç + Gemini + Claude; ek paket
yok). Anahtarlar biçiminden tanınır (tanınmazsa sağlayıcıların model listesi uçları sırayla denenir):

| Sağlayıcı | Anahtar | Not |
|---|---|---|
| Google Gemini | `AIza…`, `AQ.…` | Ücretsiz katman var (aistudio.google.com/apikey) |
| OpenAI | `sk-proj-…`, `sk-…` | |
| Anthropic Claude | `sk-ant-…` | |
| DeepSeek | `sk-` + 32 hane | |
| OpenRouter | `sk-or-…` | Yüzlerce modele tek anahtar |
| Groq, xAI, Cerebras, Fireworks, Together, Mistral | kendi biçimleri | |
| Ollama (bu PC) | `ollama` ya da `http://…:11434` | Anahtarsız, yerel modeller |

Seçilen modeller **en iyiden en kötüye** otomatik sıralanır (model adındaki sürüm ve sınıftan: pro/opus > sonnet/flash >
mini/lite). Kotası dolan atlanır; **bir saat sonra en iyi modeller yeniden denenir** (gün içinde kota yenilenince kitap
yine en iyi modelle sürer). Anahtarı geçersiz sağlayıcının modelleri zincirden çıkar; hepsi biterse o ana kadar
çevrilenlerle kısmi EPUB çıkar, aynı linkle tekrar başlatınca kaldığı yerden sürer.

## Kaynaklar ve hedef dil

- **Özel destekli siteler:** freewebnovel.com, libread.com, novelbin, NovelFull ailesi (novelfull.com, readnovelfull.com,
  allnovelfull.net / novgo.net, novelfull.net), Royal Road, FanMTL / ReadWN / WuxiaBox, NovelBuddy (1. bölümden
  "sonraki" ile gezilir), Wattpad (herkese açık API; ücretli bölümler yalnız ön izleme kadar). Diğer siteler genel
  okuyucuyla denenir.
- **Desteklenmeyenler:** bot koruması sert olan ya da metni şifreli/JS ile yükleyen siteler (novelfire, scribblehub,
  novelupdates, ranobes, wtr-lab, wuxiaworld, webnovel). Bunlar için tarayıcı eklentisi
  [WebToEpub](https://github.com/dteviot/WebToEpub) ile EPUB alıp **Dosya** sekmesinden çevirebilirsin.
- **Dosya:** EPUB, PDF (metinli), Word (.docx), TXT/MD, HTML. Bölümler dosyanın kendi yapısından ya da "Chapter/Bölüm/第…章"
  başlıklarından ayrılır; yoksa ~3000 kelimelik parçalara bölünür. Çıktı her zaman EPUB'dır.
- **Hedef dil:** Türkçe, English, Deutsch, Français, Español, Italiano, Português, Nederlands, Polski, Русский,
  Українська, Azərbaycan dili, العربية, فارسی, Bahasa Indonesia, 日本語, 简体中文, 한국어. Türkçeye özel kurallar
  (-dı'lı anlatım, sen/siz, "Cilt N Bölüm M") yalnız Türkçede uygulanır.
- **Site bul:** bu PC'deki Brave/Chrome/Edge geçmişi ve yer işaretlerinden novel adreslerini site site sayar (yalnız yerelde
  okunur). Root'lu Android telefonun geçmişi USB ile de okunabilir.

## Neler yapıyor

| Aşama | Ayrıntı |
|---|---|
| Bölüm listesi | Siteye özel uçlar (freewebnovel `?ajax=chapters`, novelbin `/ajax/chapter-archive`, FanMTL `fy.php` sayfaları, Wattpad API); diğerlerinde sayfadaki bağlantılar ya da "Sonraki" ile gezme. |
| İndirme | Tarayıcı taklidi (`curl_cffi`), istekler arası bekleme + 3 paralel işçi, hatada artan bekleme. |
| Temizlik | Reklam, filigran (süslü Unicode dahil), "Translated by", "End of …" notları, kopya paragraflar atılır. |
| Denetim | Boş/kısa bölüm, engel sayfası, aynı içerik, numara boşlukları raporlanır; sorunlular yeniden indirilir. |
| Yarım çeviri onarımı | Kaynak dilde kalmış paragraflar (kesik/kopya yanıt, kesinti) bulunur ve yalnız onlar yeniden çevrilir; her çalıştırmada eski çeviriler de taranır, çevrilemeyen bölümler sonda tek tek yeniden denenir. Redaksiyon çeviriyi bozarsa taslak korunur. |
| Çeviri | Bölümler uzunluğa göre paketlenir (tek istekte birden çok bölüm), JSON şemalı yanıt; kitaba özel **terim sözlüğü**, **hikâye hafızası** (özet, karakter notları, kalıcı sen/siz tablosu), sonraki bölümün ilk paragrafları bağlam olarak gider. |
| Redaksiyon | İsteğe bağlı ikinci tur: editör gözüyle anlam, akıcılık, hitap ve imla düzeltmesi. |
| Kaldığı yerden | İnen/çevrilen her bölüm `kutuphane/`'de saklanır; tekrar başlatınca yalnız eksikler yapılır. |
| Çıktı | Varsayılan EPUB (kapak, künye, içindekiler, okunaklı CSS). Hedef dilin yanındaki **Biçim**'den Word (DOCX), tek dosya HTML, TXT ya da Markdown seçilebilir (hatırlanır). `cikti/` klasörüne yazılır. |

## İpuçları

- **Terimleri düzeltmek:** Kitaplık → Terim sözlüğü. Yanlış çevrilen bölümleri "Yeniden çevrilecek" ile işaretle
  (eski çeviri yedeğe alınır; "Eskiye dön" geri getirir), sonra aynı linkle Başlat.
- **Ücretsiz Gemini kotası** model başına ve istek sayısıyla sayılır, her gün Türkiye saatiyle 11:00'de yenilenir.
  Birden çok model seçmek ve redaksiyonu açık tutmak kaliteyi korur; hız için redaksiyonu kapatabilirsin (istek sayısı yarıya iner).
- **Ayrıntılar:** düşünme seviyesi (orta önerilir), sıcaklık (0,6–0,8), bir istekte en çok bölüm (0 = otomatik).

Kişisel okuma içindir; sitelerin kullanım koşullarına ve yazar/çevirmen emeğine saygı göster.

## Gizlilik ve güvenlik

- API anahtarları Windows Kimlik Bilgisi Yöneticisi'nde saklanır (o kullanılamazsa veri klasöründeki `ayarlar.json`'da;
  Android'de uygulamanın özel alanında). Nerede durduğu Yapay zekâ sekmesinde yazar. Kayda ya da EPUB'a yazılmaz; arayüz
  yalnız son dört karakteri gösterir. Biçimi tanınmayan anahtar her sağlayıcıda denenmez; hangisine ait olduğunu sen seçersin.
- Wi‑Fi'deki diğer cihazlar **yalnız** kitap listesini görebilir, kitap indirip okuyabilir. Ayarlar, anahtarlar, kitaplık ve iş başlatma her açılışta değişen, yalnız
  uygulamanın kendi penceresinin bildiği bir erişim anahtarı ister; aynı bilgisayardaki ya da telefondaki başka
  programlar da bunlara dokunamaz. Başka sitelerden gelen istekler (CSRF) ve DNS yeniden bağlama istekleri reddedilir.
- Google Drive `drive.file` iznini kullanır: uygulama Drive'ında yalnız kendi oluşturduğu dosyaları görür, diğer
  dosyalarına erişemez. Giriş anahtarı Windows Kimlik Bilgisi Yöneticisi'nde (Android'de uygulamanın özel alanında)
  durur; uygulamadan çıkış yapabilir ya da https://myaccount.google.com/permissions adresinden erişimi kaldırabilirsin.
- Novel sayfalarındaki bağlantılar (sonraki bölüm, kapak resmi) yalnız internet adresiyse açılır: `file://`, `localhost`
  ve yerel ağ adresleri reddedilir.
- Açtığın novel siteleri ve seçtiğin yapay zekâ sağlayıcısı dışında hiçbir yere veri gönderilmez.
- Güvenlik açığı bulursan lütfen [gizli güvenlik bildirimi](https://github.com/N4CR0N/novel-epub/security/advisories/new) aç.

## Geliştirme

```
pip install -r requirements.txt pytest
python -m pytest -q
```

Yeni site için `novel_epub/sources/` altına `Source` alt sınıfı yaz (`novel()` ve `chapter()`), `sources/__init__.py`'deki
`SOURCES` listesine ekle, `tests/test_sources_sites.py`'ye uydurma HTML ile ağsız test yaz.

## Lisans

[MIT](LICENSE)
