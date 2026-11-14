# WebNovel Downloader & Translator

Bir web novel linki ya da dosya verirsin: araç bölüm listesinin tamamını alır, bölümleri indirip denetler,
istersen yapay zekâyla edebi bir dile çevirir (Türkçe ve 17 dil daha) ve hepsini **tek bir EPUB** yapar.
EPUB'u telefondaki kitap uygulamasıyla (Moon+ Reader, ReadEra, Apple Books, Google Play Kitaplar…) okursun.

## Kurulum (Windows uygulaması)

1. GitHub'da bu deponun **Releases** sayfasından ("WebNovel Downloader & Translator — son sürüm")
   **WebNovelDownloaderTranslator.exe**'yi indir.
2. Çift tıkla. Kurulum yok; kendi penceresinde açılır.
   - İmzasız olduğu için Windows ilk seferde "Windows bilgisayarınızı korudu" diyebilir: **Ek bilgi → Yine de çalıştır**.
   - Güvenlik duvarı izin sorarsa **Özel ağlar**'a izin ver (telefondan indirme için).
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

## Kullanım

- **İndir ve çevir:** linki yapıştır (roman sayfası ya da herhangi bir bölüm), istersen bölüm aralığı ver, **Başlat**.
  "Siteyi dene" bölüm listesini ve ilk bölümü deneyip sonucu gösterir.
- İlerleme çubuğu ve kayıt canlı akar. Bitince EPUB "Hazır kitaplar" listesine düşer.
- **Telefondan:** PC ile telefon aynı Wi‑Fi'deyse, uygulamada yazan `http://192.168.x.x:5000` adresini telefonda aç;
  EPUB'a dokununca doğrudan telefona iner.

Komut satırı:

```
set GEMINI_API_KEY=...            (ya da OPENAI_API_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, OPENROUTER_API_KEY…)
python -m novel_epub https://freewebnovel.com/novel/stellar-transformations --cevir ^
       --model "gemini/gemini-3.8-flash, gemini/gemini-3.1-flash-lite"
```

Anahtar/model verilmezse uygulamanın kayıtlı ayarları kullanılır.

## Yapay zekâ sağlayıcıları

Çeviri [LiteLLM](https://github.com/BerriAI/litellm) üzerinden yapılır; şu anahtarlar biçiminden tanınır (tanınmazsa
sağlayıcıların model listesi uçları sırayla denenir):

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
| Çeviri | Bölümler uzunluğa göre paketlenir (tek istekte birden çok bölüm), JSON şemalı yanıt; kitaba özel **terim sözlüğü**, **hikâye hafızası** (özet, karakter notları, kalıcı sen/siz tablosu), sonraki bölümün ilk paragrafları bağlam olarak gider. |
| Redaksiyon | İsteğe bağlı ikinci tur: editör gözüyle anlam, akıcılık, hitap ve imla düzeltmesi. |
| Kaldığı yerden | İnen/çevrilen her bölüm `kutuphane/`'de saklanır; tekrar başlatınca yalnız eksikler yapılır. |
| EPUB | Kapak, künye, içindekiler, okunaklı CSS; `cikti/` klasörüne. |

## İpuçları

- **Terimleri düzeltmek:** Kitaplık → Terim sözlüğü. Yanlış çevrilen bölümleri "Yeniden çevrilecek" ile işaretle
  (eski çeviri yedeğe alınır; "Eskiye dön" geri getirir), sonra aynı linkle Başlat.
- **Ücretsiz Gemini kotası** model başına ve istek sayısıyla sayılır, her gün Türkiye saatiyle 11:00'de yenilenir.
  Birden çok model seçmek ve redaksiyonu açık tutmak kaliteyi korur; hız için redaksiyonu kapatabilirsin (istek sayısı yarıya iner).
- **Ayrıntılar:** düşünme seviyesi (orta önerilir), sıcaklık (0,6–0,8), bir istekte en çok bölüm (0 = otomatik).

Kişisel okuma içindir; sitelerin kullanım koşullarına ve yazar/çevirmen emeğine saygı göster.

## Geliştirme

```
pip install -r requirements.txt pytest
python -m pytest -q
```

Yeni site için `novel_epub/sources/` altına `Source` alt sınıfı yaz (`novel()` ve `chapter()`), `sources/__init__.py`'deki
`SOURCES` listesine ekle, `tests/test_sources_sites.py`'ye uydurma HTML ile ağsız test yaz.
