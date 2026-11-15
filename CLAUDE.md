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
- Testler: `.venv\Scripts\python -m pytest -q` (ağsız; şu an 80 test; `tests/conftest.py` istemciye erişim anahtarını ekler). Her değişiklikte çalıştır, kırmızıyla push etme.
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
  atılır), `generic` (içindekiler bağlantıları ya da "Sonraki" ile gezme). Kayıt: `sources/__init__.py` → `SOURCES`.
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
`/indir/*` GET; ağdan gelen ancak "telefondan indirme" (`lan_share`, varsayılan kapalı; `/api/lan`) açıkken.
`start_server(port, lan)` kapalıyken 127.0.0.1'e, açıkken 0.0.0.0'a bağlar (değişince yeniden başlar). Yeni uçta
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
- Sırada: Google Drive (giriş, uygulama klasörü, otomatik yükleme, kitaplık yedeği; `drive.file` kapsamı, Google
  projesi "In production" olmalı yoksa giriş 7 günde düşer). Kullanıcının Google Cloud projesi gerekiyor.

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
- Sıcaklık 0.7 (redaksiyon ≤0.5), düşünme "orta", redaksiyon varsayılan açık. Hata olunca durma; yalnız tüm modellerin
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
- Kullanıcının 8 GB Ubuntu sunucusunda `builds/novel-epub/kuyruk.sh` çeviri kuyruğu çalışıyor (kitaplar.txt; `tamam.py`
  bitmemiş ya da kaynak dilde paragraf kalmış bölümleri `ceviri_eski/`'ye alıp yeniden çevirtir; bitmeyince 1 saat bekler).
  Süreç öldürürken `pkill -f` kullanma (kendi kabuğunu da vurur), PID ver.
- Exe boyutu: Python + PyInstaller ile taban ~12–14 MB görünüyor; ≤10 MB için Rust/Tauri (+ wreq) yeniden yazımı tartışıldı.
