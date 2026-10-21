# novel-epub — Novel → EPUB (çevirili) masaüstü uygulaması

Kullanıcıyla Türkçe konuş. Sıcak, doğrudan, somut ol; kendi gerekçeli görüşünü söyle. Kullanıcı kod yazmaz:
istediği değişikliği sen yap, sına, commit'le, `main`'e push et; exe'yi GitHub Actions derler.

## Ne yapar
Web novel linki ya da dosya (EPUB/PDF/DOCX/TXT/MD/HTML) → bölümleri ayır/indir → denetle → (isteğe bağlı) Gemini ile
seçilen dile çevir (+ redaksiyon) → tek EPUB. Arayüz yerel Flask sunucusu; masaüstünde pywebview penceresinde açılır
(tarayıcı/konsol yok). Aynı Wi‑Fi'deki telefon da arayüzü açıp EPUB indirebilir.

## Çalıştırma (geliştirici)
- `gelistir.bat` (Windows): .venv kurar, uygulamayı **kaynak koddan** pencerede açar. Kod değişince pencereyi kapat-aç.
- Elle: `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt pywebview pytest`, sonra
  `.venv\Scripts\python uygulama.py` (pencere) ya da `python -m novel_epub` (tarayıcıda, 127.0.0.1:5000).
- Testler: `.venv\Scripts\python -m pytest -q` (ağsız; şu an 50 test). Her değişiklikte çalıştır, kırmızıyla push etme.
- Veri klasörü: exe/kaynak klasöründe `kutuphane/` varsa orası, yoksa `Belgeler\Novel EPUB` (`NOVEL_EPUB_HOME` ile değişir).
  İçinde: `kutuphane/<kaynak>-<kitap>/` (ham/, ceviri[-dil]/, ceviri_eski/, sozluk[-dil].json, hafiza[-dil].json,
  talimat[-dil].txt), `cikti/*.epub`, `ayarlar.json`, `uygulama.log`, `yuklenen/`, `telefon-gecmis/`.

## Yayın
`main`'e push → `.github/workflows/windows-uygulama.yml` (windows-latest): pytest → PyInstaller tek dosya
`NovelEPUB.exe` (`--windowed`, simge `assets/icon.ico`) → `--oz-test` (pencere açmadan arayüz/sunucu/kasa denetimi) →
Releases `son` etiketi. Push'tan sonra Actions sonucunu kontrol et; kullanıcıya Releases linkini ver
(https://github.com/N4CR0N/novel-epub/releases/tag/son). Exe imzasız: kullanıcı "Özellikler → Engellemeyi kaldır" yapar.
Yeni bir Python paketi eklersen `requirements.txt`'e ve gerekiyorsa workflow'daki `--collect-*` bayraklarına ekle.

## Mimari (novel_epub/)
- `sources/` site eklentileri: `base.Source` (`novel(url)→Novel`, `chapter(ref)→Chapter`), `freewebnovel`
  (`?ajax=chapters`), `novelbin` (sınanmadı: bulut IP'sine 503), `novelfull` (novelfull.com, readnovelfull.com,
  allnovelfull.net/novgo.net, novelfull.net — 3 düzen), `royalroad` (CSS ile gizlenen korsanlık karşıtı satırlar
  atılır), `generic` (içindekiler bağlantıları ya da "Sonraki" ile gezme). Kayıt: `sources/__init__.py` → `SOURCES`.
- `fetcher.py` curl_cffi (Chrome taklidi; basit Cloudflare'i geçer), istek arası bekleme, yeniden deneme.
- `cleaner.py` paragraf çıkarma/temizlik (reklam, filigran, süslü Unicode filigran NFKC, "End of b1c13", tek "."),
  bölüm denetimi (kısa/boş/engel/kopya/eksik numara); `clean_output_paragraphs` EPUB öncesi çıktı temizliği.
- `files.py` dosya okuyucular; bölüm ayırma: EPUB spine/TOC, PDF yer imi → başlık → ~3000 kelimelik parça
  (satır birleştirme, sayfa no ve tekrarlanan üst/alt bilgi atılır), DOCX başlık stilleri.
- `translator.py` Gemini (google-genai): JSON şemalı yanıt; bölüm paketleme (kelime sayısından token tahmini,
  gerçek kullanımdan öğrenme, kesik yanıtta bütçe küçülür); model zinciri (günlük kota/404 → sıradaki model);
  geçici hatada en çok 60 sn bekleyip 10 deneme; hikâye hafızası (özet, karakter notları, **kalıcı sen/siz hitap
  tablosu**), sonraki bölümün ilk 3 paragrafı (`next_context`), redaksiyon (`edit_batch`, EDIT_PROMPT),
  İngilizce kalmış kelime tespiti. `LANGUAGES` 18 hedef dil; `TURKISH_RULES` yalnız Türkçede eklenir.
- `pipeline.py` iş akışı (`Options`, `Job`): indir/oku → denetle → çevir (+redaksiyon, eski çevirileri de redakte
  eder) → EPUB. Kota bitince kısmi EPUB; olmayan bölüm "[Çevrilemedi]" ile orijinal kalır; "ilk 20'de dur".
- `store.py` kitap önbelleği (dil başına ayrı; Türkçe eski adları korur), yedekle/geri dön.
- `web.py` Flask uçları + ayarlar (API anahtarı Windows Kimlik Bilgisi kasasında, `keyring`); `templates/index.html`
  tek sayfa arayüz. `app.py` masaüstü penceresi + `--oz-test`. `history.py` PC tarayıcı geçmişi/yer işaretlerinden
  ve root'lu Android'den (adb + su) novel sitelerini bulma (yalnız yerel).

## Yeni site eklerken
1. `novel_epub/sources/<site>.py`: `name`, `domains`; novel sayfası **ve** bölüm linkinden çalışsın; bölüm listesinin
   TAMAMI sırayla (sayfalı/ajax uçlarını bul); içerik seçicisi; `self.build_chapter(...)`.
2. `SOURCES`'a ekle. `tests/test_sources_sites.py`'ye uydurma ("Lorem") HTML ile ağsız test yaz (FakeFetcher deseni).
3. Canlı doğrulamada yalnız sayı yazdır (bölüm sayısı, ilk/son başlık, bir bölümün paragraf/karakter sayısı).
   **Bölüm metnini ekrana, teste ya da commit'e koyma** (telif).
4. Uygulamada "Siteyi test et" ile kullanıcıya da denet.

## Kararlar (kullanıcı)
- Ayrı depo; PC'de masaüstü uygulaması (pencere, konsol yok); çeviri Gemini ücretsiz anahtar.
- Ücretsiz kota model başına (ör. gemini-3.8-flash günde 20 istek, 3.x Flash Lite 500). Önerilen zincir:
  `gemini-3.8-flash, gemini-3.6-flash, gemini-3-flash, gemini-2.5-flash, gemini-3.5-flash-lite, gemini-3.1-flash-lite`
  (adları Ayarlar → Listele doğrular; olmayan ad atlanır). Argon/Pro ücretsiz katmanda kapalı.
- Sıcaklık 0.7 (redaksiyon ≤0.5), düşünme "orta", redaksiyon varsayılan açık. Hata olunca durma; yalnız tüm modellerin
  günlük kotası bitince ya da anahtar geçersizse dur.
- Türkçe: anlatım -dı/-di, "-maktadır" yok; sen/siz tablosu ilk kayıtta sabit; "Book N Chapter M" → "Cilt N Bölüm M".
- Kod imzalama yok (Azure Artifact Signing Türkiye'den bireysel alınamıyor; SignPath için depo açık kaynak olmalı).
- Stellar Transformations için kullanıcının sözlüğü/talimatı uygulamada (Kitaplığım) duruyor.

## Açık işler
- Kullanıcının okuduğu siteler: telefon root'lu değil; Brave geçmişinde "chapter/novel/bölüm" aramasının ekran
  görüntülerinden ya da PC'deki "Bu PC'yi tara" sonucundan gelecek listeye göre site eklentileri eklenecek.
- Gerçek Gemini ile toplu çeviri/redaksiyon/hitap tablosunun kalitesi kullanıcıdan gelen örneklerle izlenmeli.
- novelbin canlı doğrulanmadı; wuxiaworld (liste JS ile), ranobes/webnovel (sert Cloudflare) desteklenmiyor.
