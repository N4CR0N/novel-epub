# WebNovel Downloader & Translator

**English** · [Türkçe](README.tr.md)

Give it a web novel link or a file: it fetches the full chapter list, downloads and checks every chapter, optionally
translates them into literary prose with AI (Turkish and 17 other languages), and packs everything into **one EPUB**
for any e-book reader (Moon+ Reader, ReadEra, Apple Books, Google Play Books…). Word, HTML, TXT or Markdown
output can be chosen next to the target language.

## Install (Windows)

1. Download **[WebNovelDownloaderTranslator.exe](https://github.com/N4CR0N/novel-epub/releases/latest/download/WebNovelDownloaderTranslator.exe)** (latest release). Every version is listed on the
   [Releases](https://github.com/N4CR0N/novel-epub/releases) page; the version number is shown under the app name.
2. Double-click it. No installation; it opens in its own window.
   - It is unsigned, so Windows may say "Windows protected your PC": **More info → Run anyway**.
   - If the firewall asks, allow **Private networks** (for downloading to your phone).
3. Open the **AI** tab, paste an API key and press **Add**. The provider and the models you can use are detected
   automatically; tick the ones you want.

Data (library, EPUBs, settings) lives in **Documents\WebNovel Downloader & Translator** (an existing
**Documents\Novel EPUB** folder from the old version is used as is). If a `kutuphane` folder sits next to the exe,
that folder is used instead (portable mode). The log file is `uygulama.log` in the data folder.

Every push to `main` builds the exe on GitHub Actions (Windows), runs the tests and a windowless self-test, and
publishes it to Releases (`.github/workflows/windows-uygulama.yml`).

### From source

1. Install [Python 3.10+](https://www.python.org/downloads/) ("Add python.exe to PATH").
2. Run `gelistir.bat` (opens in a window) or `baslat.bat` (opens in the browser).

## Use

- **Download & translate:** paste a link (novel page or any chapter), optionally a chapter range, then **Start**.
  "Test site" tries the chapter list and the first chapter first.
- Progress and the log update live; the finished EPUB appears under "Ready books".
- **Phone:** with the PC and phone on the same Wi‑Fi, open the `http://192.168.x.x:5000` address shown in the app on
  your phone and tap an EPUB to download it.
- **Interface:** theme (light / dark / system) and interface language (Türkçe, English, Deutsch, Español, Русский)
  in the top-right corner; the device language is preselected. The window opens maximized the first time and then
  remembers its size.

Command line:

```
set GEMINI_API_KEY=...            (or OPENAI_API_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, OPENROUTER_API_KEY…)
python -m novel_epub https://freewebnovel.com/novel/stellar-transformations --cevir --dil en ^
       --model "gemini/gemini-3.8-flash, gemini/gemini-3.1-flash-lite"
```

Without a key/model the app's saved settings are used.

## AI providers

Translation uses the app's own lightweight client (`novel_epub/llm.py`: OpenAI-compatible endpoint + Gemini +
Claude, no extra packages). Keys are recognised by their format (otherwise the providers' model-list endpoints are
tried in turn):

| Provider | Key | Note |
|---|---|---|
| Google Gemini | `AIza…`, `AQ.…` | Free tier available (aistudio.google.com/apikey) |
| OpenAI | `sk-proj-…`, `sk-…` | |
| Anthropic Claude | `sk-ant-…` | |
| DeepSeek | `sk-` + 32 hex | |
| OpenRouter | `sk-or-…` | Hundreds of models with one key |
| Groq, xAI, Cerebras, Fireworks, Together, Mistral | their own formats | |
| Ollama (this PC) | `ollama` or `http://…:11434` | No key, local models |

Selected models are ordered **best to worst** automatically (from the version and class in the model name:
pro/opus > sonnet/flash > mini/lite). A model that runs out of quota is skipped; **after an hour the best ones are
tried again**. A provider whose key is invalid is dropped from the chain. If every model is exhausted, a partial EPUB
is written with what has been translated; start again with the same link and it continues where it stopped.

## Sources and languages

- **Dedicated support:** freewebnovel.com, libread.com, novelbin, the NovelFull family (novelfull.com,
  readnovelfull.com, allnovelfull.net / novgo.net, novelfull.net), Royal Road, FanMTL / ReadWN / WuxiaBox, NovelBuddy
  (walked from chapter 1 via "next"), Wattpad (public API; paid parts only as far as the preview). Other sites go
  through the generic reader.
- **Not supported:** sites with strict bot protection or encrypted/JS-loaded text (novelfire, scribblehub,
  novelupdates, ranobes, wtr-lab, wuxiaworld, webnovel). For those, save an EPUB with the
  [WebToEpub](https://github.com/dteviot/WebToEpub) browser extension and translate it from the **File** tab.
- **Files:** EPUB, PDF (with text), Word (.docx), TXT/MD, HTML. Chapters come from the file's own structure or from
  "Chapter / Bölüm / 第…章" headings, otherwise ~3000-word parts. Output is always EPUB.
- **Source language:** any (English, Chinese, Japanese, Korean…); the model detects it.
- **Target language:** Türkçe, English, Deutsch, Français, Español, Italiano, Português, Nederlands, Polski, Русский,
  Українська, Azərbaycan dili, العربية, فارسی, Bahasa Indonesia, 日本語, 简体中文, 한국어. Turkish-specific rules
  (past-tense narration, sen/siz, "Cilt N Bölüm M") apply only to Turkish.
- **Find sites:** counts novel addresses per site from this PC's Brave/Chrome/Edge history and bookmarks (read
  locally only); a rooted Android phone's history can be read over USB.

## What it does

| Stage | Details |
|---|---|
| Chapter list | Site-specific endpoints (freewebnovel `?ajax=chapters`, novelbin `/ajax/chapter-archive`, FanMTL `fy.php` pages, Wattpad API); elsewhere the links on the page or following "Next". |
| Download | Browser impersonation (`curl_cffi`), a delay between requests + 3 parallel workers, retries with back-off. |
| Cleanup | Ads, watermarks (including fancy Unicode), "Translated by", "End of …" notes and duplicate paragraphs are removed. |
| Checks | Empty/short chapters, block pages, duplicates and numbering gaps are reported; problem chapters are re-downloaded. |
| Translation | Chapters are batched by length (several per request) with JSON-schema answers; a per-book **glossary**, **story memory** (summary, character notes, a fixed formal/informal address table) and the start of the next chapter go along as context. |
| Gap repair | Paragraphs left in the source language (cut-off or copied answers, interruptions) are detected and only those are retranslated; older translations are scanned on every run and failed chapters are retried one by one at the end. If editing makes a chapter worse, the draft is kept. |
| Editing pass | Optional second pass: meaning, fluency, forms of address and spelling, like an editor. |
| Resume | Every downloaded/translated chapter is cached in `kutuphane/`; a new run only does what is missing. |
| Output | EPUB by default (cover, colophon, table of contents, readable CSS; EPUB 3 + NCX). Next to the target language you can switch to Word (DOCX), a single HTML file, TXT or Markdown (remembered). Written to `cikti/`. |

## Tips

- **Fix terms:** Library → Glossary. Mark badly translated chapters with "Mark for retranslation" (the old
  translation is backed up; "Restore previous" brings it back), then press Start with the same link.
- **Free Gemini quota** is counted per model and per request and resets daily (midnight Pacific time). Selecting
  several models and keeping the editing pass on keeps quality; turn editing off to halve the requests.
- **Details:** thinking level (medium recommended), temperature (0.6–0.8), max chapters per request (0 = auto).

For personal reading; respect the sites' terms and the authors' and translators' work.

## Privacy and security

- API keys are stored in the Windows Credential Manager (only if that is unavailable, in `ayarlar.json` inside your
  data folder). They never go into logs or EPUBs, and the interface only ever shows the last four characters.
- The local server is reachable from your Wi-Fi so that your phone can download finished books. Other devices can
  **only** see the book list and download EPUBs; settings, keys, the library and starting jobs work from this
  computer only. Requests from other websites (CSRF) and DNS-rebinding requests are rejected.
- Nothing is sent anywhere except the novel sites you open and the AI provider you choose.
- Found a security problem? Please open a [private security advisory](https://github.com/N4CR0N/novel-epub/security/advisories/new).

## Development

```
pip install -r requirements.txt pytest
python -m pytest -q
```

Contributions are welcome. To add a site, write a `Source` subclass in `novel_epub/sources/` (`novel()` and `chapter()`), add it to `SOURCES` in
`sources/__init__.py`, and add an offline test with made-up HTML to `tests/test_sources_sites.py`.

## License

[MIT](LICENSE)
