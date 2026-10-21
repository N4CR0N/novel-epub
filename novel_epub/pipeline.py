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
    batch: int = 0  # tek Gemini isteğinde en fazla kaç bölüm (0 = bölüm uzunluğuna göre otomatik)
    edit: bool = True  # redaksiyon turu: taslak çeviriyi bir editör gibi ikinci kez düzelt (2× istek)
    thinking: str = "medium"  # düşünme seviyesi: low / medium / high
    review_after: int = 0  # yeni kitapta bu kadar bölüm çevrilince dur (sözlüğü gözden geçirmek için)
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
    notice: str = ""
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
        from .translator import FatalError, GeminiTranslator, QuotaExhausted, TranslationError

        o = self.opts
        tr = GeminiTranslator(o.api_key, o.model, o.target, log=self.log, thinking_level=o.thinking)

        def wait(seconds: float) -> None:  # "Durdur" bekleme sırasında da çalışsın
            if self.cancel_event.wait(seconds):
                raise Cancelled()

        tr.sleep = wait
        tr.memory = store.load_memory()
        self.p.phase = f"çevriliyor ({tr.model})"
        self.p.total = len(chapters)
        glossary = store.load_glossary()
        source = {c.index: c for c in chapters}
        results: dict[int, Chapter] = {}
        pending: list[Chapter] = []
        for ch in chapters:
            done = store.load_tr(ch.index)
            if done is not None or not ch.paragraphs:
                results[ch.index] = done or ch
            else:
                pending.append(ch)
        fresh_book = not any(store.load_tr(c.index) for c in chapters[:50])
        to_edit = [source[i] for i, d in results.items() if o.edit and source[i].paragraphs and not d.edited]
        self.p.done = len(results)
        if results:
            self.log(f"{len(results)} bölüm önceden çevrilmiş, {len(pending)} bölüm kaldı"
                     + (f"; {len(to_edit)} çeviri redaksiyon bekliyor" if to_edit else ""))
        if o.edit:
            self.log("Redaksiyon turu açık: her paket çevrildikten sonra bir kez de editör gözüyle düzeltilecek (2× istek)")

        def context_before(index: int) -> list[str]:
            prev = results.get(index - 1)
            return prev.paragraphs[-4:] if prev else []

        def save_state(new_terms: dict) -> None:
            store.save_memory(tr.memory)
            if new_terms:
                glossary.update(new_terms)
                store.save_glossary(glossary)
                self.log(f"  sözlüğe eklendi: {', '.join(f'{k}→{v}' for k, v in list(new_terms.items())[:6])}")

        def edit(drafts: list[Chapter]) -> None:
            """Taslakları redakte eder; kota hatası yukarı çıkar, diğer hatada taslak kalır."""
            self.p.phase = f"redaksiyon ({tr.model})"
            edited = tr.edit_batch([source[d.index] for d in drafts], drafts, glossary)
            for e in edited:
                if e.edited:
                    store.save_tr(e)
                    results[e.index] = e
            n = sum(e.edited for e in edited)
            self.log(f"  redakte edildi: {n}/{len(drafts)} bölüm")

        stop_reason = ""
        # 1) Önceden çevrilmiş ama redakte edilmemiş bölümler (ör. redaksiyon sonradan açıldıysa).
        j = 0
        while j < len(to_edit) and not stop_reason:
            self._check_cancel()
            group = tr.plan_batch(to_edit[j:], o.batch)
            j += len(group)
            try:
                edit([results[c.index] for c in group])
            except QuotaExhausted as e:
                stop_reason = str(e)
            except FatalError:
                raise

        # 2) Çevrilmemiş bölümler: çevir (+ redakte et).
        failed: list[int] = []
        streak = 0
        translated_now = 0
        i = 0
        while i < len(pending) and not stop_reason:
            self._check_cancel()
            if o.review_after and fresh_book and translated_now >= o.review_after:
                self.p.notice = (f"İlk {translated_now} bölüm çevrildi ve durdu: sözlüğü (Kitaplığım → Sözlük) gözden geçir, "
                                 "gerekirse bu bölümleri yeniden çevirt, sonra aynı linkle başlat.")
                self.log(self.p.notice)
                break
            # Ardışık bölümleri, tahmini çıktı token'ı bütçeye sığana kadar tek istekte topla.
            group = tr.plan_batch(pending[i:], o.batch)
            i += len(group)
            self.p.phase = f"çevriliyor ({tr.model})"
            try:
                outs, new_terms = tr.translate_batch(group, glossary, context_before(group[0].index))
            except QuotaExhausted as e:
                stop_reason = str(e)
                break
            except FatalError:
                raise
            except TranslationError as e:
                # Bu grup olmadı: atla, sonrakilerle devam et (tekrar başlatınca yeniden denenir).
                outs, new_terms = [], {}
                self.log(f"  {group[0].index}–{group[-1].index}. bölümler çevrilemedi ({e}); sonrakilere geçiliyor")
            got = {d.index for d in outs}
            for done in outs:
                store.save_tr(done)
                results[done.index] = done
                self.p.done += 1
                translated_now += 1
                self.log(f"  çevrildi {self.p.done}/{self.p.total}: {done.title}")
            save_state(new_terms)
            missed = [c.index for c in group if c.index not in got]
            failed.extend(missed)
            if outs and o.edit:
                try:
                    edit(outs)
                except QuotaExhausted as e:
                    stop_reason = str(e)  # taslaklar kayıtlı; redaksiyon sonraki çalıştırmada
                except FatalError:
                    raise
            streak = streak + 1 if missed and not outs else 0
            if streak >= 3:
                self.log("  Art arda 3 istek başarısız; 5 dk bekleyip devam ediliyor")
                wait(300)
                streak = 0

        if stop_reason:
            if not results:
                raise QuotaExhausted(stop_reason)
            # Tüm modellerin kotası bitti: çevrilenlerle kısmi EPUB çıkar; tekrar başlatınca kaldığı yerden sürer.
            self.log(f"Çeviri durdu: {stop_reason}")
            self.p.error = f"Kısmi: {len(results)} bölüm çevrili ({stop_reason})"

        # EPUB, çevrilmiş son bölüme kadar gider; arada çevrilemeyenler orijinal metniyle kalır.
        last = max(results, default=0)
        out = [results.get(ch.index) or Chapter(ch.index, f"[Çevrilemedi] {ch.title}", ch.url, ch.paragraphs)
               for ch in chapters if ch.index <= last]
        failed = [n for n in failed if n <= last and n not in results]
        if failed:
            self.p.report["cevrilemeyen"] = failed
            self.log(f"{len(failed)} bölüm çevrilemedi, EPUB'da orijinal metniyle duruyor: {failed[:30]}. "
                     "Aynı linkle tekrar başlatınca yalnız bunlar ve kalanlar denenir.")
        if self.p.error:
            self.log(f"{len(out)} bölümlük kısmi EPUB hazırlanıyor. Kota yenilenince aynı linkle başlat, kaldığı yerden sürer.")
        self.log(f"Terim sözlüğü: {store.glossary_path} · hikâye hafızası: {store.memory_path}")
        return out
