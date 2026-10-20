"""Link → bölüm listesi → indirme + denetim → (isteğe bağlı) çeviri → tek EPUB."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .cleaner import check_book, check_chapter
from .epub_builder import build_epub
from .fetcher import Fetcher
from .models import Chapter, ChapterRef, Novel
from .sources import source_for
from .store import BookStore, slugify


class Cancelled(Exception):
    pass


@dataclass
class Options:
    url: str
    start: int | None = None  # 1'den başlayan bölüm sırası (dahil)
    end: int | None = None
    translate: bool = False
    api_key: str = ""
    model: str = ""
    target: str = "Türkçe"
    delay: float = 0.7
    workers: int = 3
    batch: int = 3  # tek Gemini isteğinde en fazla kaç bölüm
    max_follow: int = 3000  # genel kaynakta "Sonraki" ile en fazla kaç bölüm gezilsin
    library: Path = Path("kutuphane")
    output: Path = Path("cikti")


@dataclass
class Progress:
    phase: str = "hazırlanıyor"
    done: int = 0
    total: int = 0
    title: str = ""
    result: str = ""
    error: str = ""
    report: dict = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)


class Job:
    def __init__(self, opts: Options, on_log: Callable[[str], None] | None = None):
        self.opts = opts
        self.p = Progress()
        self.cancel_event = threading.Event()
        self._on_log = on_log

    # --- yardımcılar ---
    def log(self, msg: str) -> None:
        self.p.logs.append(msg)
        del self.p.logs[:-300]
        if self._on_log:
            self._on_log(msg)

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()

    def cancel(self) -> None:
        self.cancel_event.set()

    # --- akış ---
    def run(self) -> Path | None:
        try:
            out = self._run()
            self.p.phase = "bitti"
            return out
        except Cancelled:
            self.p.phase = "iptal edildi"
            self.log("İptal edildi. İnen bölümler önbellekte; tekrar başlatınca kaldığı yerden sürer.")
        except Exception as e:  # arayüze hata olarak dön
            self.p.phase = "hata"
            self.p.error = str(e)
            self.log(f"HATA: {e}")
        return None

    def _run(self) -> Path:
        o = self.opts
        fetcher = Fetcher(delay=o.delay)
        source = source_for(o.url, fetcher)
        self.p.phase = "bölüm listesi alınıyor"
        self.log(f"Kaynak: {source.name} · {o.url}")
        novel = source.novel(o.url)
        self.p.title = novel.title
        store = BookStore(o.library, novel)

        if novel.follow_next:
            self.log("Bölüm listesi bulunamadı; bu sayfadan 'Sonraki' bağlantılarıyla ilerlenecek.")
            chapters = self._crawl_next(source, novel, store)
        else:
            self.log(f"{novel.title} — {len(novel.chapters)} bölüm bulundu ({novel.author})")
            refs = novel.chapters[(o.start or 1) - 1: o.end or None]
            if not refs:
                raise ValueError("Seçilen aralıkta bölüm yok")
            chapters = self._download(source, refs, store)

        report = check_book(chapters)
        self.p.report = {
            "sorunlu": {str(k): v for k, v in report["sorunlu"].items()},
            "kopya": report["kopya"],
            "eksik_numaralar": report["eksik_numaralar"],
        }
        self._log_report(report)

        if o.translate:
            chapters = self._translate(chapters, store)

        self._check_cancel()
        self.p.phase = "EPUB yazılıyor"
        cover = None
        if novel.cover_url:
            try:
                cover = fetcher.content(novel.cover_url, referer=novel.url)
            except Exception as e:
                self.log(f"Kapak alınamadı: {e}")
        first, last = chapters[0].index, chapters[-1].index
        rng = f"{first}-{last}"
        suffix = "tr" if o.translate else "orijinal"
        out = Path(o.output) / f"{slugify(novel.title)}_{rng}_{suffix}.epub"
        build_epub(novel, chapters, out, language="tr" if o.translate else "en", cover=cover,
                   subtitle=f"Bölüm {rng}" + (" · Türkçe" if o.translate else ""))
        self.p.result = str(out)
        self.log(f"Hazır: {out}")
        return out

    def _download(self, source, refs: list[ChapterRef], store: BookStore) -> list[Chapter]:
        self.p.phase = "bölümler indiriliyor"
        self.p.total, self.p.done = len(refs), 0
        result: dict[int, Chapter] = {}
        todo = []
        for r in refs:
            ch = store.load_raw(r.index)
            if ch and not check_chapter(ch):
                result[r.index] = ch
                self.p.done += 1
            else:
                todo.append(r)
        if self.p.done:
            self.log(f"{self.p.done} bölüm önbellekten geldi, {len(todo)} bölüm indirilecek")

        def fetch(ref: ChapterRef) -> Chapter:
            self._check_cancel()
            return source.chapter(ref)

        for round_no in (1, 2):  # 2. tur: sorunlu bölümleri bir kez daha dene
            failed: list[ChapterRef] = []
            with ThreadPoolExecutor(max_workers=max(1, self.opts.workers)) as ex:
                futs = {ex.submit(fetch, r): r for r in todo}
                for fut in as_completed(futs):
                    ref = futs[fut]
                    try:
                        ch = fut.result()
                    except Cancelled:
                        ex.shutdown(cancel_futures=True)
                        raise
                    except Exception as e:
                        self.log(f"  ✗ {ref.index}. {ref.title}: {e}")
                        failed.append(ref)
                        continue
                    issues = check_chapter(ch)
                    if issues and round_no == 1:
                        failed.append(ref)
                        continue
                    store.save_raw(ch)
                    result[ref.index] = ch
                    self.p.done += 1
                    if self.p.done % 25 == 0 or self.p.done == self.p.total:
                        self.log(f"  {self.p.done}/{self.p.total} bölüm indi")
            if not failed:
                break
            if round_no == 1:
                self.log(f"{len(failed)} bölüm sorunlu, yavaşça yeniden deneniyor…")
                source.f.delay = max(source.f.delay, 2.0)
                todo = failed
            else:
                for ref in failed:
                    self.log(f"  ! {ref.index}. bölüm alınamadı, EPUB'da boş sayfa olarak kalacak")
                    result[ref.index] = Chapter(ref.index, ref.title, ref.url, [])
        return [result[r.index] for r in refs]

    def _crawl_next(self, source, novel: Novel, store: BookStore) -> list[Chapter]:
        self.p.phase = "bölümler gezilerek indiriliyor"
        o = self.opts
        chapters: list[Chapter] = []
        url, idx, seen = novel.url, 1, set()
        start, end = o.start or 1, min(o.end or o.max_follow, o.max_follow)
        self.p.total = end - start + 1
        while url and url not in seen and idx <= end:
            self._check_cancel()
            seen.add(url)
            ch = store.load_raw(idx)
            if not ch or ch.url != url:
                ch = source.chapter(ChapterRef(idx, f"Bölüm {idx}", url))
                store.save_raw(ch)
            if idx >= start:
                chapters.append(ch)
                self.p.done += 1
            url, idx = ch.next_url, idx + 1
        if not chapters:
            raise ValueError("Hiç bölüm alınamadı")
        self.log(f"{len(chapters)} bölüm gezildi")
        return chapters

    def _log_report(self, report: dict) -> None:
        if report["sorunlu"]:
            self.log(f"Denetim: {len(report['sorunlu'])} sorunlu bölüm: " +
                     ", ".join(f"{k} ({'; '.join(v)})" for k, v in list(report["sorunlu"].items())[:15]))
        if report["kopya"]:
            self.log(f"Denetim: aynı içerikli bölümler: {report['kopya'][:10]}")
        if report["eksik_numaralar"]:
            self.log(f"Denetim: listede olmayan bölüm numaraları: {report['eksik_numaralar'][:20]}")
        if not any(report.values()):
            self.log("Denetim: tüm bölümler sağlam görünüyor ✓")

    def _translate(self, chapters: list[Chapter], store: BookStore) -> list[Chapter]:
        from .translator import GeminiTranslator, TranslationError

        o = self.opts
        tr = GeminiTranslator(o.api_key, o.model, o.target, log=self.log)
        self.p.phase = f"çevriliyor ({tr.model})"
        self.p.total = len(chapters)
        glossary = store.load_glossary()
        results: dict[int, Chapter] = {}
        pending: list[Chapter] = []
        for ch in chapters:
            done = store.load_tr(ch.index)
            if done is not None or not ch.paragraphs:
                results[ch.index] = done or ch
            else:
                pending.append(ch)
        self.p.done = len(results)
        if results:
            self.log(f"{len(results)} bölüm önceden çevrilmiş, {len(pending)} bölüm kaldı")

        def context_before(index: int) -> list[str]:
            prev = results.get(index - 1)
            return prev.paragraphs[-4:] if prev else []

        i = 0
        while i < len(pending):
            self._check_cancel()
            # Ardışık bölümleri karakter sınırı içinde tek istekte topla.
            group, size = [pending[i]], pending[i].char_count
            limit = tr.batch_limit(pending[i])
            for ch in pending[i + 1: i + max(1, o.batch)]:
                if ch.index != group[-1].index + 1 or size + ch.char_count > limit:
                    break
                group.append(ch)
                size += ch.char_count
            try:
                outs, new_terms = tr.translate_batch(group, glossary, context_before(group[0].index))
            except TranslationError as e:
                if not results:
                    raise
                # Kota/hata: o ana kadar çevrilenlerle kısmi EPUB çıkar; tekrar başlatınca kaldığı yerden sürer.
                self.log(f"Çeviri {group[0].index}. bölümde durdu: {e}")
                self.p.error = f"Kısmi: {len(results)} bölüm çevrili ({e})"
                break
            for done in outs:
                store.save_tr(done)
                results[done.index] = done
                self.p.done += 1
                self.log(f"  çevrildi {self.p.done}/{self.p.total}: {done.title}")
            if new_terms:
                glossary.update(new_terms)
                store.save_glossary(glossary)
                self.log(f"  sözlüğe eklendi: {', '.join(f'{k}→{v}' for k, v in list(new_terms.items())[:6])}")
            self.p.phase = f"çevriliyor ({tr.model})"
            i += len(group)

        # Kısmi durumda EPUB, baştan kesintisiz çevrilmiş bölümlerle sınırlı kalır.
        out: list[Chapter] = []
        for ch in chapters:
            if ch.index not in results:
                break
            out.append(results[ch.index])
        if self.p.error:
            self.log(f"{len(out)} bölümlük kısmi EPUB hazırlanıyor. Kota yenilenince aynı linkle başlat, kaldığı yerden sürer.")
        self.log(f"Terim sözlüğü: {store.glossary_path} (elle düzeltip yeniden çevirebilirsin)")
        return out
