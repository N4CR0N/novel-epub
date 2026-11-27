# novel-epub — WebNovel Downloader & Translator (masaüstü uygulaması)

Kullanıcıyla Türkçe konuş. Sıcak, doğrudan, somut ol; kendi gerekçeli görüşünü söyle. Kullanıcı kod yazmaz:
istediği değişikliği sen yap, sına, commit'le, `main`'e push et; exe'yi GitHub Actions derler.

## Ne yapar
Web novel linki ya da dosya (EPUB/PDF/DOCX/TXT/MD/HTML) → bölümleri ayır/indir → denetle → (isteğe bağlı) kendi hafif istemcimizle
(`llm.py`; Gemini, OpenAI, Claude, DeepSeek, OpenRouter, Groq, xAI, Mistral, Ollama…) seçilen dile çevir (+ redaksiyon) → tek EPUB. Arayüz yerel Flask sunucusu; masaüstünde pywebview penceresinde açılır
(tarayıcı/konsol yok). Aynı Wi‑Fi'deki telefon arayüzü açıp **yalnız** hazır EPUB'ları görüp indirebilir.
Depo herkese açık (MIT lisansı): gizli bilgi, kişisel bilgi, sunucu adresi asla commit'lenmez (testlerde uydurma anahtar).

## Çalıştırma (geliştirici)
- `gelistir.bat` (Windows): .venv kurar, uygulamayı **kaynak koddan** pencerede açar. Kod değişince pencereyi kapat-aç.
- Elle: `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt pywebview pytest`, sonra
  `.venv\Scripts\python uygulama.py` (pencere) ya da `python -m novel_epub` (tarayıcıda, 127.0.0.1:5000).
- Testler: `.venv\Scripts\python -m pytest -q` (ağsız; şu an 118 test; `tests/conftest.py` istemciye erişim anahtarını ekler). Her değişiklikte çalıştır, kırmızıyla push etme.
- Veri klasörü: exe/kaynak klasöründe `kutuphane/` varsa orası; yoksa `Belgeler\Novel EPUB` (eski sürüm) varsa o, yoksa
  `Belgeler\WebNovel Downloader & Translator` (`NOVEL_EPUB_HOME` ile değişir).
  İçinde: `kutuphane/<kaynak>-<kitap>/` (ham/, ceviri[-dil]/, ceviri_eski/, sozluk[-dil].json, hafiza[-dil].json,
  talimat[-dil].txt), `cikti/*.epub`, `ayarlar.json`, `uygulama.log`, `yuklenen/`, `telefon-gecmis/`.

## Yayın
`main`'e push → `.github/workflows/windows-uygulama.yml` (windows-latest): `requirements-ci.txt` (hash kilitli) → pytest → PyInstaller `uygulama.spec` (UPX yok: antivirüs yanlış alarmı)
(tek dosya, pencereli, simge `assets/icon.ico`; kullanılmayan paketler, UCRT ve x64 dışı WebView2Loader dışlanır) →
`--oz-test` (pencere açmadan arayüz/sunucu/kasa/erişim anahtarı + `llm` sahte yanıt denetimi) → boyut dökümü (PYZ paket paket) + SHA-256 sürüm notuna →
her main yayını ayrı sürüm: `VERSION` dosyası (ör. `1.2`) + sıradaki yama no → `v1.2.0` etiketi, İngilizce sürüm notu;
değişiklik listesi commit başlıklarından (yalnız .github/, CLAUDE.md, README'ye dokunan commit'ler hariç) → **commit
başlıklarını İngilizce ve kullanıcıya dönük yaz**; yalnız CI değişikliğinde `[skip ci]`; exe içine `novel_epub/_surum.py` yazılır (arayüzde adın altında görünür).
Yeni özellikte `VERSION`'ı artır (1.2 → v1.2.0), büyük değişiklikte 2.0. Push'tan sonra Actions sonucunu kontrol et;
kullanıcıya sürüm linkini ver (https://github.com/N4CR0N/novel-epub/releases/latest). Eski derlemeler
(silinen) `eski-surumler.yml` ile v0.1.0–v1.1.1 olarak yayımlandı (etiket commit'leri eski kaynak + main'in workflow'ları:
GitHub, Actions anahtarına workflow'u farklı commit'e etiket koydurmuyor; oturumdan etiket push'u ve sürüm
oluşturma/düzenleme kapalı — sürüm işleri yalnız Actions workflow'larıyla). Exe imzasız: kullanıcı "Özellikler → Engellemeyi kaldır" yapar.
**Her başarısız Actions çalıştırması kullanıcıya mail atar** (istemiyor): bilerek başarısız derleme tetikleme,
workflow betiklerini önce yerelde dene, emin olmadığın şeyi dal + `workflow run` ile tek seferde doğrula. Öz-test
(`--oz-test`) pencerenin WinForms/WebView2 tarafını da yükler (WebView2Loader'ın 3 mimari kopyası da pakette kalmalı).
Action'lar commit SHA'sına sabit (yorumda sürüm), izinler iş başına. Yeni bir Python paketi eklersen `requirements.txt`'e, gerekiyorsa `uygulama.spec`'e ekle ve kilidi yenile: `(cat requirements.txt; printf 'pywebview\npyinstaller\npytest\n') > /tmp/ci.in && uv pip compile /tmp/ci.in --python-platform windows --python-version 3.12 --generate-hashes -o requirements-ci.txt` (CI `--require-hashes --no-deps` ile kurar). Android pip sürümleri `android/app/build.gradle.kts`'te sabit. Boyut önemli (107 MB → ~18 MB;
hedef ≤10 MB): ağır paket ekleme (LiteLLM, lxml, EbookLib, python-docx bu yüzden çıkarıldı). Dal push'ları Actions'ı
tetiklemez: `gh workflow run windows-uygulama.yml --ref <dal>` (sürüm yalnız main'den yayımlanır).

## Mimari (novel_epub/)
- `sources/` site eklentileri: `base.Source` (`novel(url)→Novel`, `chapter(ref)→Chapter`), `freewebnovel`
  (`?ajax=chapters`; libread.com aynı motor), `readwn` (fanmtl/readwn/wuxiabox; `/e/extend/fy.php?page=N`),
  `novelbuddy` (liste JS → 1. bölümden follow_next), `wattpad` (API v3 + `apiv2/?m=storytext`), `novelbin` (sınanmadı: bulut IP'sine 503), `novelfull` (novelfull.com, readnovelfull.com,
  allnovelfull.net/novgo.net, novelfull.net — 3 düzen), `royalroad` (CSS ile gizlenen korsanlık karşıtı satırlar
  atılır), `syosetu` (ncode.syosetu.com; içindekiler `?p=N` sayfalı, 前書き/後書き ve ruby atılır; R18 alt alanı yok),
  `kakuyomu` (`__NEXT_DATA__` Apollo durumu `tableOfContentsV2`), `generic` (içindekiler bağlantıları ya da "Sonraki" ile
  gezme). Kayıt: `sources/__init__.py` → `SOURCES`. `Source.min_delay` siteye özel en az bekleme (Japon siteleri 2 sn),
  `Source.strip_ruby` okunuşları atar. Çince ham: `piaotia` (GBK, içindekiler tek sayfa, metin H1 sonrası tablodan sonra
  `<br />` satırları — dilimlenir), `ixdzs` (bölümler /read/<id>/p<N>.html sıralı; en yüksek N'den liste). 69shuba bölüm
  sayfaları bot korumalı (eklenmedi); Korece korsanlar alan adı değiştiriyor/erişilemiyor, resmîler (Kakao/Naver/Munpia) ücretli.
- `fetcher.py` curl_cffi (Chrome taklidi; basit Cloudflare'i geçer), istek arası bekleme, yeniden deneme.
- `cleaner.py` paragraf çıkarma/temizlik (reklam, filigran, süslü Unicode filigran NFKC, "End of b1c13", tek "."),
  bölüm denetimi (kısa/boş/engel/kopya/eksik numara); `clean_output_paragraphs` EPUB öncesi çıktı temizliği.
- `files.py` dosya okuyucular; bölüm ayırma: EPUB spine/TOC, PDF yer imi → başlık → ~3000 kelimelik parça
  (satır birleştirme, sayfa no ve tekrarlanan üst/alt bilgi atılır), DOCX başlık stilleri.
- `providers.py` sağlayıcı kaydı: anahtar biçiminden tanıma (`guess`/`detect`, belirsizse liste uçları denenir),
  model listeleme (sohbet dışı modeller elenir), `rank` (sürüm×4 + sınıf puanı; sağlayıcı sırası korunur), `ENV_KEYS`.
- `llm.py` LiteLLM yerine kendi istemcimiz (curl_cffi): OpenAI uyumlu uçlar, Gemini `generateContent` (responseSchema,
  thinkingLevel), Anthropic messages; LiteLLM biçiminde yanıt (`choices[0].message`, `usage.completion_tokens`) ve hata
  sınıfları (`status_code`). Model adı `sağlayıcı/model`; öneksiz ad Gemini sayılır.
- `translator.py` `Translator` (eski ad `GeminiTranslator`), `llm.completion` (`self.complete` testte sahtelenir):
  JSON şema (desteklemeyen modelde şema talimata yazılır + json_object), `_classify` hata eşleme (auth→sağlayıcı
  zincirden çıkar, 404→model çıkar, günlük kota→1 saat sonra en iyiden yeniden dene, 402/insufficient_quota→kota); bölüm paketleme (kelime sayısından token tahmini,
  gerçek kullanımdan öğrenme, kesik yanıtta bütçe küçülür); model zinciri (günlük kota/404 → sıradaki model);
  geçici hatada en çok 60 sn bekleyip 10 deneme; hikâye hafızası (özet, karakter notları, **kalıcı sen/siz hitap
  tablosu**), sonraki bölümün ilk 3 paragrafı (`next_context`), redaksiyon (`edit_batch`, EDIT_PROMPT),
  İngilizce kalmış kelime tespiti; `untranslated_paragraphs` (kaynakla aynı / İngilizce durak kelimesi oranı / CJK
  kalmış paragraf) + `repair()` yalnız bozuk paragrafları yeniden çevirir; redaksiyon çeviriyi bozarsa taslak kalır. `LANGUAGES` 18 hedef dil; `TURKISH_RULES` yalnız Türkçede eklenir.
- `quality.py` kalite denetimi (her çevrilen paket + Kitaplık "Çeviriyi denetle ve düzelt" = `Options.audit`, CLI
  `--denetle`): kodla `normalize_title` ("Chapter N X" → "Bölüm N: X"; kaynakta yoksa "Cilt" yok) ve `fix_levels`
  ("Lv./Sv./Level N" → "Seviye N"); `align` (Gale–Church benzeri, uzunluk + sayı/ad çapası; 1–1, 2–1, 1–2, atlama)
  ile paragraf eşleme → `paragraph_issues`: atlanmış kaynak paragrafı (`missing`, ardına eklenir), kaynakta olmayan
  tekrar/uydurma (boş dönerse silinir), kaynak dilde kalan kelime (`COMMON_EN` unvan/ad kelimeleri ya da kaynakta
  küçük harfle geçen; adlar ve `TR_SAME` hariç), sözlüğe uymama (çekim ekinden bağımsız kök), eski/ağdalı kelime
  (`ARCHAIC_TR`), uyuşmayan sayı, %60'tan kısa paragraf. `Translator.review` ("atlanmış" diye eklenen çeviri komşu paragraflarda zaten varsa — `covered_by` — eklenmez: tekrar paragrafların ana kaynağı eşleme kaymasıyla yapılan bu eklemeydi) sorunlu paragrafları POLISH_PROMPT ile
  40'arlı istekte onarır, `checked = QUALITY_VERSION` yazar (kurallar değişince artır). `fix_glossary`: karşılığında
  İngilizce ya da eski kelime kalan sözlük kayıtları (`suspicious_glossary`). Denetimde eski kelime yoğunluğu
  >4/1000 olan bölüm baştan redakte edilir. Tekrar temizliği modelsiz ve kesin kuralla (EPUB öncesi her çalıştırmada +
  `fix_chapter`): `drop_repeats` (≤3 paragraf arayla aynısı/içeriği, kısa olan ≥12 kelime; ya da aynı kaynağın farklı kelimelerle ikinci
  çevirisi: içerik kelimelerinin ilk 5 harfi önceki 1–3 paragrafla ≥%75/%60 örtüşüyor, ya da hemen öncekiyle ≥%80 (önceki daha uzun olabilir); ya da kısa paragraf (≥8 kök) 1–2 paragraf ötedekinde ≥%85 var ve kaynakta eşi yok; kaynakta da tekrar varsa dokunmaz; denetim paketinden sonra kaydetmeden önce de çalışır),
  `drop_boundary_repeat` (bölüm sonuna eklenmiş sonraki bölüm başı), `drop_next_chapter_copy` (site 742. sayfaya 743'ü de
  koymuşsa). Eski kural (kaynakta herhangi bir tekrar varsa denetimi atlıyordu, silmeyi modele bırakıyordu) yetmiyordu. Kök neden (2026-11): istemdeki "edebi/yayınevi kalitesinde" ağdalı dile
  itiyordu → "çağdaş, sade"; T3 "Book N Chapter M → Cilt" kuralı "Chapter N"i "Cilt N" yaptırıyordu;
  `untranslated_suspects` sözlüğün kaynak tarafındaki kelimeleri serbest sayıyordu ("Dean" yakalanmıyordu).
- Toplu sözlük (kitap başında bir kez, `sozluk-hazir[-dil].json` işareti): `quality.term_candidates` kitabın tamamından
  büyük harfli ad öbeklerini çıkarır (≥3 kez, ≥2'si cümle ortasında; iyelik/kısaltma/çoğul ayıklanır, küçük harfle de sık geçen
  tek kelimeler elenir; en çok 600), `Translator.build_glossary` BUILD_GLOSSARY_PROMPT ile 200'erli istekte zincirin en iyi
  kullanılabilir modeliyle çevirir (CJK kaynakta ilk ~40 bin karakterden model çıkarır); mevcut kayıtlara dokunmaz.
- Sözlük denetimi (kitap bitince bir kez, `sozluk-denetim[-dil].json`, `quality.GLOSSARY_AUDIT_VERSION`; "denetle"de her
  seferinde): `quality.glossary_audit_items` en sık ~150 terimi (kaynakta sıklık + hizalanmış 2 örnek) çıkarır,
  `Translator.audit_glossary` (GLOSSARY_AUDIT_PROMPT, 50'şerli) yanlış/yarım/tutarsız karşılıkları ve çeviride geçen yanlış
  biçimleri ("Detsizlik") döndürür; `Job._glossary_audit` sözlüğü (türetilmiş kayıtlar dahil) ve terimin kaynağında geçtiği
  bölümleri `quality.replace_term` (Türkçe ek uyumu `tr_harmonize`: Tribün'ün → Felaket'in) ile düzeltir; biçim metinde
  kaynaktan çok sıksa (>2×+5) ya da yeni karşılığın içindeyse metne dokunmaz. Yapılanlar işaret dosyasına yazılır.
- `pipeline.py` iş akışı (`Options`, `Job`): indir/oku → denetle → çevir (+redaksiyon, eski çevirileri de redakte
  eder) → EPUB. Başta eski çevirilerde yarım kalmış paragraf denetimi, sonda başarısız bölümler için bir tur daha.
  Kota bitince kısmi EPUB; olmayan bölüm "[Çevrilemedi]" ile orijinal kalır; "ilk 20'de dur".
- `exporters.py` çıktı biçimleri (`FORMATS`): epub (varsayılan, `epub_builder`), docx (zipfile; Title/Heading1
  stilleri, her bölüm yeni sayfa), tek dosya html (kapak gömülü), txt, md; yazmadan önce XML'de yasak denetim
  karakterleri atılır. Seçim İndir ve çevir formunda Hedef dil'in yanında (varsayılan EPUB,
  `output_format` ayarında hatırlanır; işte `format` alanı ezer; CLI `--bicim`), `Options.fmt`.
- `store.py` kitap önbelleği (dil başına ayrı; Türkçe eski adları korur), yedekle/geri dön.
- `web.py` Flask uçları + ayarlar: anahtarlar kasada `<sağlayıcı>_api_key` (Gemini'nin eski adı aynı), `ayarlar.json`'da
  `models` (`sağlayıcı/model` adları, sıralı), `theme` (light/dark/system), `ui_lang` ve `providers.<id>.models` (erişilen liste); `/api/keys` (ekle/sil/yenile),
  `/api/models`, `/api/sources`. `_guard` (before_request): Host yalnız IP/localhost (DNS rebinding), GET dışı istekte
Origin aynı host olmalı (CSRF); tam erişim yalnız `_trusted()` = 127.0.0.1 + `X-Token: API_TOKEN` (her açılışta yeni;
pencere `local_url()` = `#t=` ile açılır, JS sessionStorage'a alıp her isteğe ekler; Android'de `android_main.token()`).
Anahtarsız istek (başka yerel program, ağdaki telefon) yalnız `/`, `/api/info|books|languages|settings` (ipucusuz) ve
`/indir/*`, `/api/read/*` GET (kullanıcı kararı: ağ paylaşımı hep açık, anahtar yok; `start_server(port, lan=True)`
masaüstünde 0.0.0.0, Android 127.0.0.1). `/oauth2cb` yalnız 127.0.0.1'den anahtarsız (state ile doğrulanır).
Okuyucu: `reader.py` (EPUB içindekiler + tek bölüm, önbellek; `okuma.json` kaldığın yer) + `templates/reader.html`
(tam ekran, sayfa=CSS sütunları, geniş ekranda 2 sütun; tema/boyut/aralık/kenar/yazı tipi localStorage'da).
Drive: `drive.py` (PKCE + 127.0.0.1 dönüşlü masaüstü istemcisi, Android'de de aynı akış Chrome'da; `drive.file`;
klasör "WebNovel Downloader & Translator"; resumable yükleme, PATCH yerine POST + X-HTTP-Method-Override).
Yenileme anahtarı kasada `google_drive_refresh` (yoksa ayarlar.json `drive.refresh`; `drive` arayüze asla gitmez).
İstemci kimliği CI'da `GOOGLE_DESKTOP_CLIENT_ID/SECRET` gizlilerinden `novel_epub/_google.py`'ye yazılır (gitignore;
geliştirmede `NOVEL_EPUB_GOOGLE_ID/SECRET`). Biten iş otomatik yüklenir (`_run_job`, `drive.auto`). Yeni uçta
endpoint içi kontrol `_trusted()` olsun. `Fetcher` yalnız http/https ve yerel ağ dışı adresleri açar (`check_url`;
198.18/15 fake-ip serbest), Retry-After ≤120 sn, Durdur beklemeyi keser. `/api/keys`: biçimi tanınmayan anahtar
hiçbir sağlayıcıya gönderilmez (`UnknownFormat` → arayüz sağlayıcı seçtirir). Kitap klasörü `store.book_dirname`
(eski ad korunur; çakışma/kesik/Latin dışı başlıkta URL özeti eki). Yüklemeler içerik özetiyle adlanır, 7 günde silinir.
Aynı kitaba ikinci iş açılmaz (409 + süren işin id'si; `pipeline._ACTIVE_BOOKS`); sayfa yenilenince `/api/jobs` ile bağlanır. `templates/index.html`: sol menülü tek sayfa (İndir ve çevir, Kitaplık, Yapay zekâ,
  Site bul); açık mavi palet, sağ üstte tema (açık/koyu/sistem) ve arayüz dili (tr/en/de/es/ru; varsayılan cihaz dili;
  `templates/i18n.js`, `T()` ile; anahtarlar Türkçe metinler), geniş ekranda iki sütun, mobil uyumlu. Pencere açılışta
  büyütülür, boyutu `pencere.json`'da hatırlanır. README.md İngilizce (ana), README.tr.md Türkçe. `app.py` masaüstü penceresi + `--oz-test`. `history.py` PC tarayıcı geçmişi/yer işaretlerinden
  ve root'lu Android'den (adb + su) novel sitelerini bulma (yalnız yerel).

## Android uygulaması (android/, dal: `android` → main'e alınınca sürümlere APK eklenir)
- Chaquopy 17 (Python 3.12) + WebView: aynı Flask arayüzü telefonda 127.0.0.1'de (`novel_epub/android_main.py`
  `start/busy/status/output_path`), `WorkService.kt` ön plan hizmeti (specialUse; bildirimde ilerleme, iş sürerken
  uyanık kalma kilidi, boşta 10 dk sonra kapanır), `MainActivity.kt` (dosya seçme, kitabı İndirilenler/WebNovel'e kaydedip
  açma, tarayıcıdan "Paylaş" ile link → `#url=`). `web.ANDROID` (NOVEL_EPUB_ANDROID=1): klasör aç/Site bul gizli.
- Ağ: `net.py` — masaüstünde curl_cffi, Android'de HttpURLConnection, yoksa urllib. **Siteyi reddeden bağlantıyı
  telefonun tarayıcı motoruyla (WebView) yeniden denemek engellendi (erişim engelini aşmak sayılıyor); yapma.**
  Düz bağlantıyı reddeden siteler (ör. Royal Road 403) telefonda çalışmaz, bilgisayar uygulamasında kullanılır.
- CI: `android-apk.yml` (elle; denemeler mail atmasın diye `continue-on-error`) APK + emülatör testi
  (`.github/emulator-smoke.sh`: arayüz açılıyor mu; GitHub IP'sinden siteler Cloudflare engeline takılır, bilgi amaçlı).
  Sürüm hattındaki `android` işi APK'yı yalnız `ANDROID_KEYSTORE_B64` + `ANDROID_KEYSTORE_PASSWORD` gizli değerleri
  varsa yayımlar (yoksa atlar): Gradle imzasız derler (`ANDROID_UNSIGNED=1`), gizli değerler yalnız ayrı "İmzala"
  adımına (zipalign + apksigner, parola dosyadan) verilir; APK'nın SHA-256'sı sürüm notuna eklenir. Gizli değerlerden
  türeyen hiçbir şeyi (özet öneki, uzunluk) loga basma: depo herkese açık. Anahtarı kullanıcı GitHub'a ekler; oturum gizli değerlere yazamaz, anahtarı
  ekrana basma. Uygulama kimliği `io.github.n4cr0n.novelepub`, yalnız arm64.
- Bildirim yalnız iş sürerken (ön plan hizmetine iş başlayınca geçer, `MainActivity.onPause` → `syncNow`), iş bitince
  kalkar; uygulama kapalıyken bittiyse kapatılabilir "bitti" notu.
- Drive girişi Android'de de masaüstü istemcisiyle Chrome'da yapılır (gömülü WebView'de Google izin vermez); Google
  projesi "In production" olmalı yoksa giriş 7 günde düşer. Yedekten geri yükleme henüz yok.

## Yeni site eklerken
1. `novel_epub/sources/<site>.py`: `name`, `domains`; novel sayfası **ve** bölüm linkinden çalışsın; bölüm listesinin
   TAMAMI sırayla (sayfalı/ajax uçlarını bul); içerik seçicisi; `self.build_chapter(...)`.
2. `SOURCES`'a ekle. `tests/test_sources_sites.py`'ye uydurma ("Lorem") HTML ile ağsız test yaz (FakeFetcher deseni).
3. Canlı doğrulamada yalnız sayı yazdır (bölüm sayısı, ilk/son başlık, bir bölümün paragraf/karakter sayısı).
   **Bölüm metnini ekrana, teste ya da commit'e koyma** (telif).
4. Uygulamada "Siteyi test et" ile kullanıcıya da denet.

## Kararlar (kullanıcı)
- Ayrı depo; PC'de masaüstü uygulaması (pencere, konsol yok). Ad: "WebNovel Downloader & Translator".
- Yapay zekâ: Vercel AI SDK yerine LiteLLM seçildi, boyut için LiteLLM'in yerine aynı arayüzlü `llm.py` yazıldı. Kullanıcı yalnız anahtar yapıştırır; sağlayıcı ve
  modeller otomatik bulunur, kullanıcı işaretler, sıra otomatik en iyiden kötüye.
- Ücretsiz kota model başına (ör. gemini-3.8-flash günde 20 istek, 3.x Flash Lite 500). Önerilen zincir:
  `gemini-3.8-flash, gemini-3.6-flash, gemini-3-flash, gemini-2.5-flash, gemini-3.5-flash-lite, gemini-3.1-flash-lite`
  (adları Ayarlar → Listele doğrular; olmayan ad atlanır). Argon/Pro ücretsiz katmanda kapalı.
- Sıcaklık 0.7 (redaksiyon ≤0.5), düşünme "orta", redaksiyon varsayılan açık ve **tek geçiş** (2026-11-26 denemesi: aynı
  kalite, yarı istek; `Options.one_pass`, `Translator.self_edit` → SELF_EDIT_RULES çeviri istemine eklenir, ayrı edit_batch yok;
  CLI `--iki-gecis` eski düzen). Tek geçiş sayıları yazıyla yazabiliyor: sayı denetimi Türkçe yazılışı kabul eder (`tr_number_words`). Hata olunca durma; yalnız tüm modellerin
  günlük kotası bitince ya da anahtar geçersizse dur.
- Türkçe: anlatım -dı/-di, "-maktadır" yok; sen/siz tablosu ilk kayıtta sabit; "Book N Chapter M" → "Cilt N Bölüm M".
- Kod imzalama yok (Azure Artifact Signing Türkiye'den bireysel alınamıyor; SignPath için depo açık kaynak olmalı).
- Stellar Transformations için kullanıcının sözlüğü/talimatı uygulamada (Kitaplığım) duruyor.

## Açık işler
- Kullanıcının okuduğu siteler: telefon root'lu değil; Brave geçmişinde "chapter/novel/bölüm" aramasının ekran
  görüntülerinden ya da PC'deki "Bu PC'yi tara" sonucundan gelecek listeye göre site eklentileri eklenecek.
- Gerçek Gemini ile toplu çeviri/redaksiyon/hitap tablosunun kalitesi kullanıcıdan gelen örneklerle izlenmeli.
- novelbin canlı doğrulanmadı (sunucudan da 503). Desteklenmeyen (2026-11): novelfire (bölüm sayfası 403), scribblehub/
  novelupdates/ranobes/novelhall (Cloudflare), wtr-lab/wuxiaworld/webnovel (metin JS/şifreli API), lightnovelpub.vip,
  mtlnovels (JS). Bunların korumasını aşmaya çalışma.
- Sunucuda `denetle.sh <url> [ilk son]` bitmiş kitabı denetler (anahtarı kuyruk.sh'den okur, `denetim.log`);
  Cosmic'in denetim öncesi yedeği `yedek-cosmic-2026-11-19/`.
- Kullanıcının 8 GB Ubuntu sunucusunda `builds/novel-epub/kuyruk.sh` çeviri kuyruğu çalışıyor (kitaplar.txt; `tamam.py`
  bitmemiş ya da kaynak dilde paragraf kalmış bölümleri `ceviri_eski/`'ye alıp yeniden çevirtir; bitmeyince 1 saat bekler).
  Süreç öldürürken `pkill -f` kullanma (kendi kabuğunu da vurur), PID ver.
- Exe boyutu: Python + PyInstaller ile taban ~12–14 MB görünüyor; ≤10 MB için Rust/Tauri (+ wreq) yeniden yazımı tartışıldı.
