"""Link → bölüm listesi → indirme + denetim → (isteğe bağlı) çeviri → tek kitap (varsayılan EPUB)."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .cleaner import check_book, check_chapter, clean_output_paragraphs, clean_paragraphs
from .exporters import FORMATS, export, normalize
from .fetcher import Fetcher
from .models import Chapter, ChapterRef, Novel
from .sources import source_for
from .store import BookStore, slugify
from .translator import LANGUAGES


class Cancelled(Exception):
    pass


@dataclass
class Options:
    url: str
    start: int | None = None  # 1'den başlayan bölüm sırası (dahil)
    end: int | None = None
    translate: bool = False
    api_key: str = ""  # eski: tek Gemini anahtarı
    keys: dict = field(default_factory=dict)  # sağlayıcı → anahtar (providers.PROVIDERS id'leri)
    model: str = ""  # LiteLLM adları, virgülle, en iyiden en kötüye
    lang: str = "tr"  # hedef dil kodu (translator.LANGUAGES)
    file: str = ""  # doluysa site yerine bu dosyadan (EPUB/PDF/DOCX/TXT/HTML) okunur
    delay: float = 0.7
    workers: int = 3
    batch: int = 0  # tek Gemini isteğinde en fazla kaç bölüm (0 = bölüm uzunluğuna göre otomatik)
    edit: bool = True  # redaksiyon: taslak çeviriyi bir editör gözüyle düzelt
    one_pass: bool = True  # redaksiyon çeviriyle aynı istekte (tek geçiş; ayrı istek yok, ~1,5 kat hızlı)
    thinking: str = "medium"  # düşünme seviyesi: low / medium / high
    temperature: float = 0.7
    review_after: int = 0  # yeni kitapta bu kadar bölüm çevrilince dur (sözlüğü gözden geçirmek için)
    max_follow: int = 3000  # genel kaynakta "Sonraki" ile en fazla kaç bölüm gezilsin
    library: Path = Path("kutuphane")
    output: Path = Path("cikti")
    fmt: str = "epub"  # çıktı biçimi: epub / docx / html / txt / md (exporters.FORMATS)
    audit: bool = False  # önceden çevrilmiş bölümleri de kalite denetiminden geçir ("Çeviriyi denetle ve düzelt")


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


_ACTIVE_BOOKS: set[str] = set()  # şu an işlenen kitap klasörleri (aynı kitaba iki iş aynı anda yazmasın)
_ACTIVE_LOCK = threading.Lock()


class Job:
    def __init__(self, opts: Options, on_log: Callable[[str], None] | None = None):
        self.opts = opts
        self.p = Progress()
        self.cancel_event = threading.Event()
        self._on_log = on_log
        self._claimed: str | None = None

    def _claim(self, store: BookStore) -> None:
        key = f"{store.dir.resolve()}|{self.opts.lang}"
        with _ACTIVE_LOCK:
            if key in _ACTIVE_BOOKS:
                raise RuntimeError("Bu kitap başka bir işte zaten işleniyor; o bitince yeniden başlat.")
            _ACTIVE_BOOKS.add(key)
            self._claimed = key

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
        finally:
            if self._claimed:
                with _ACTIVE_LOCK:
                    _ACTIVE_BOOKS.discard(self._claimed)
        return None

    def _run(self) -> Path:
        o = self.opts
        fetcher = Fetcher(delay=o.delay, stop=self.cancel_event)
        cover = None
        if o.file:
            from .files import load_file

            self.p.phase = "dosya okunuyor"
            self.log(f"Kaynak: dosya · {Path(o.file).name}")
            novel, all_chapters, cover = load_file(o.file)
            self.p.title = novel.title
            store = BookStore(o.library, novel, lang=o.lang)
            self._claim(store)
            self.log(f"{novel.title} — {len(all_chapters)} bölüm ayrıldı")
            chapters = all_chapters[(o.start or 1) - 1: o.end or None]
            if not chapters:
                raise ValueError("Seçilen aralıkta bölüm yok")
            for ch in chapters:
                store.save_raw(ch)
        else:
            source = source_for(o.url, fetcher)
            self.p.phase = "bölüm listesi alınıyor"
            self.log(f"Kaynak: {source.name} · {o.url}")
            novel = source.novel(o.url)
            self.p.title = novel.title
            store = BookStore(o.library, novel, lang=o.lang)
            self._claim(store)

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
        fmt = normalize(o.fmt)
        self.p.phase = f"{FORMATS[fmt][0]} yazılıyor"
        for ch in chapters:  # çeviride kalmış "… sonu" notları, tek nokta satırları, filigranlar
            ch.paragraphs = clean_output_paragraphs(ch.paragraphs)
        if cover is None and novel.cover_url:
            try:
                cover = fetcher.content(novel.cover_url, referer=novel.url)
            except Exception as e:
                self.log(f"Kapak alınamadı: {e}")
        first, last = chapters[0].index, chapters[-1].index
        rng = f"{first}-{last}"
        suffix = o.lang if o.translate else "orijinal"
        stem = store.dir.name.removeprefix(f"{novel.source}-") or slugify(novel.title)
        base = Path(o.output) / f"{stem}_{rng}_{suffix}"
        lang_label = LANGUAGES.get(o.lang, LANGUAGES["tr"])[1]
        out = export(fmt, novel, chapters, base, language=o.lang if o.translate else "en", cover=cover,
                     subtitle=f"Bölüm {rng}" + (f" · {lang_label}" if o.translate else ""))
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
            if ch:  # önbellekteki eski indirmeler de güncel temizleyiciden geçsin (ör. süslü filigranlar)
                ch.paragraphs = clean_paragraphs(ch.paragraphs, ch.title)
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
                    self.log(f"  ! {ref.index}. bölüm alınamadı, kitapta boş sayfa olarak kalacak")
                    result[ref.index] = Chapter(ref.index, ref.title, ref.url, [])
        return [result[r.index] for r in refs]

    def _crawl_next(self, source, novel: Novel, store: BookStore) -> list[Chapter]:
        self.p.phase = "bölümler gezilerek indiriliyor"
        o = self.opts
        chapters: list[Chapter] = []
        url, idx, seen = (novel.chapters[0].url if novel.chapters else novel.url), 1, set()
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

    def _glossary_audit(self, tr, audit_fn, source: dict, results: dict, glossary: dict, store: BookStore) -> None:
        """En sık terimleri en iyi modele denetletir, düzeltmeleri sözlüğe ve çevrilmiş bölümlere işler."""
        import dataclasses
        import re

        from . import quality

        items = quality.glossary_audit_items(source, results, glossary)
        if not items:
            return
        self.log(f"Sözlük denetimi: en sık {len(items)} terim gözden geçiriliyor ({tr.model})")
        fixes, remove = audit_fn(items)
        lang = self.opts.lang
        plain = {i: quality.plain_text(source[i]) for i in results if i in source}
        done: dict[str, list[str]] = {}
        changed: dict[int, Chapter] = {}
        # Uzun biçimler önce: "Tribün Emin" → "Felaket Yücesi", sonra "Tribün" → "Felaket".
        for src_term, (new, wrong) in sorted(fixes.items(), key=lambda kv: -len(glossary.get(kv[0], ""))):
            old = glossary.get(src_term, "")
            rx = re.compile(r"(?<![\w])" + re.escape(src_term) + r"(?![\w])")
            per = {i: quality.count_term(plain[i], src_term) for i in sorted(results) if results[i] is not source[i]}
            idx = [i for i, c in per.items() if c]
            n_src = sum(per[i] for i in idx)
            total = 0
            for form in dict.fromkeys([old, *wrong]):
                # Yeni karşılığın içinde geçen biçim ("Felaket" → "Felaket Yücesi") ya da kısa/sık kelime metinde
                # değiştirilmez (yanlış yerleri de bozar); yalnız sözlük güncellenir.
                if len(form) < 4 or form.lower() in new.lower():
                    continue
                hits = sum(len(re.findall(r"(?<![\w])" + re.escape(form), " ".join((changed.get(i) or results[i]).paragraphs)))
                           for i in idx)
                if hits > 2 * n_src + 5:
                    self.log(f"  {src_term}: '{form}' metinde kaynaktan çok daha sık ({hits}>{n_src}); metne dokunulmadı")
                    continue
                for i in idx:
                    ch = changed.get(i) or results[i]
                    paras, k = [], 0
                    for p in ch.paragraphs:
                        p2, c = quality.replace_term(p, form, new, lang)
                        paras.append(p2)
                        k += c
                    title, c = quality.replace_term(ch.title, form, new, lang)
                    if k + c:
                        changed[i] = dataclasses.replace(ch, title=title, paragraphs=paras)
                        total += k + c
            glossary[src_term] = new
            for key, val in list(glossary.items()):  # türetilmiş kayıtlar: "Sixth Tribulation": "Altıncı Tribün"
                if key != src_term and rx.search(key) and old and len(old) >= 4 and old.lower() not in new.lower():
                    glossary[key] = quality.replace_term(val, old, new, lang)[0]
            done[src_term] = [old, new, total, wrong]
        for k in remove:
            glossary.pop(k, None)
        for i, ch in changed.items():
            store.save_tr(ch)
            results[i] = ch
        store.save_glossary(glossary)
        store.save_glossary_audit({"version": quality.GLOSSARY_AUDIT_VERSION, "model": tr.model, "fixes": done,
                                   "removed": remove})
        if done or remove:
            self.log(f"Sözlük denetimi: {len(done)} terim düzeltildi ({len(changed)} bölümde), {len(remove)} kayıt kaldırıldı: "
                     + ", ".join(f"{k}: {v[0]}→{v[1]} ({v[2]})" for k, v in list(done.items())[:12]))
        else:
            self.log("Sözlük denetimi: düzeltilecek terim yok ✓")

    def _translate(self, chapters: list[Chapter], store: BookStore) -> list[Chapter]:
        from . import quality
        from . import translator as _t
        from .translator import (LOOKAHEAD_PARAGRAPHS, FatalError, QuotaExhausted, TranslationError,
                                 untranslated_paragraphs, untranslated_suspects)

        o = self.opts
        keys = dict(o.keys) or ({"gemini": o.api_key} if o.api_key else {})
        tr = _t.GeminiTranslator(keys, o.model, o.lang, log=self.log, thinking_level=o.thinking)

        def wait(seconds: float) -> None:  # "Durdur" bekleme sırasında da çalışsın
            if self.cancel_event.wait(seconds):
                raise Cancelled()

        tr.sleep = wait
        tr.memory = store.load_memory()
        tr.temperature = o.temperature
        tr.self_edit = o.edit and o.one_pass
        tr.book_notes = store.load_notes()
        if tr.book_notes:
            self.log(f"Kitaba özel çeviri talimatı kullanılıyor ({len(tr.book_notes)} karakter)")
        self.p.phase = f"çevriliyor ({tr.model})"
        self.p.total = len(chapters)
        glossary = store.load_glossary()
        source = {c.index: c for c in chapters}
        # Kitap başında toplu sözlük (bir kez): adlar ilk bölümden itibaren hep aynı çevrilsin. En iyi modelle;
        # kota yoksa sonraki çalıştırmada denenir.
        build = getattr(tr, "build_glossary", None)
        if build and not store.load_prepass() and any(store.load_tr(c.index) is None for c in chapters):
            self.p.phase = f"sözlük kuruluyor ({tr.model})"
            try:
                built = build(chapters, glossary)
            except QuotaExhausted as e:
                self.log(f"Toplu sözlük ertelendi: {e}")
                built = None
            if built is not None:
                bad = quality.suspicious_glossary(built, quality.source_vocab(chapters))
                if bad:
                    built.update(tr.fix_glossary(bad, quality.source_vocab(chapters)))
                glossary.update(built)
                store.save_glossary(glossary)
                store.save_prepass({"model": tr.model, "terms": len(built), "version": 1})
                self.log(f"Toplu sözlük: {len(built)} terim eklendi"
                         + (f" ({', '.join(f'{k}→{v}' for k, v in list(built.items())[:6])}…)" if built else ""))
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
        if o.edit and o.one_pass:
            self.log("Redaksiyon açık (tek geçiş): her paket aynı istekte hem çevrilip hem editör gözüyle düzeltilecek")
        elif o.edit:
            self.log("Redaksiyon turu açık: her paket çevrildikten sonra bir kez de editör gözüyle düzeltilecek (2× istek)")

        def context_before(index: int) -> list[str]:
            prev = results.get(index - 1)
            return prev.paragraphs[-4:] if prev else []

        def lookahead_after(index: int) -> list[str]:
            nxt = source.get(index + 1)
            return nxt.paragraphs[:LOOKAHEAD_PARAGRAPHS] if nxt else []

        vocab = quality.source_vocab(chapters)

        def save_state(new_terms: dict) -> None:
            store.save_memory(tr.memory)
            if new_terms:
                glossary.update(new_terms)
                bad = quality.suspicious_glossary(new_terms, vocab)
                if bad:  # yeni terimin karşılığında İngilizce kelime kalmışsa hemen düzelt (sonraki bölümler doğru alsın)
                    try:
                        glossary.update(tr.fix_glossary(bad, vocab))
                    except TranslationError:
                        pass
                store.save_glossary(glossary)
                self.log(f"  sözlüğe eklendi: {', '.join(f'{k}→{glossary.get(k, v)}' for k, v in list(new_terms.items())[:6])}")

        def review(indices: list[int], size: int = 8) -> None:
            """Kalite denetimi: başlık/seviye kalıbı, kaynak dilde kalmış kelime, sözlük, eski kelime, eksik çeviri."""
            idx = [i for i in indices if i in results and results[i] is not source[i]]
            for j in range(0, len(idx), size):
                part = idx[j:j + size]
                checked = tr.review([(source[i], results[i]) for i in part], glossary, vocab)
                for c in checked:
                    c, n = quality.drop_repeats(source[c.index], c)  # tekrar paragraf kaydedilmeden atılır
                    if n:
                        self.log(f"  {c.index}. bölümde {n} tekrarlanmış paragraf atıldı")
                    store.save_tr(c)
                    results[c.index] = c
                if getattr(tr, "review_stop", None):
                    raise tr.review_stop

        def edit(drafts: list[Chapter]) -> None:
            """Taslakları redakte eder; kota hatası yukarı çıkar, diğer hatada taslak kalır."""
            self.p.phase = f"redaksiyon ({tr.model})"
            edited = tr.edit_batch([source[d.index] for d in drafts], drafts, glossary, context_before(drafts[0].index))
            for e in edited:
                if e.edited:
                    store.save_tr(e)
                    results[e.index] = e
            n = sum(e.edited for e in edited)
            self.log(f"  redakte edildi: {n}/{len(drafts)} bölüm")

        stop_reason = ""
        # 0) Önceki çevirilerde kaynak dilde kalmış paragraflar (kesinti, kesik/kopya yanıt): yalnız onları onar.
        to_repair = [i for i, d in sorted(results.items()) if d is not source[i]
                     and untranslated_paragraphs(source[i].paragraphs, d.paragraphs, o.lang)]
        if to_repair:
            self.log(f"{len(to_repair)} bölümde çevrilmeden kalmış paragraf bulundu, onarılıyor: {to_repair[:20]}")
        for idx in to_repair:
            self._check_cancel()
            try:
                fixed = tr.repair(source[idx], results[idx], glossary)
            except QuotaExhausted as e:
                stop_reason = str(e)
                break
            if fixed is not results[idx]:
                store.save_tr(fixed)
                results[idx] = fixed

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

        # 1b) "Çeviriyi denetle ve düzelt": sözlükte İngilizce kalmış karşılıklar, ağdalı dille redakte edilmiş
        #     bölümler (baştan redaksiyon) ve tüm bölümlerde paragraf düzeyinde denetim.
        if o.audit and not stop_reason:
            try:
                names = quality.restore_names(glossary, (tr.memory or {}).get("characters", {}))
                if names:
                    glossary.update(names)
                    store.save_glossary(glossary)
                    self.log(f"Sözlükte çevrilmiş {len(names)} kişi adı geri alındı: {', '.join(list(names)[:8])}")
                fixed_terms = tr.fix_glossary(glossary, vocab)
                if fixed_terms:
                    glossary.update(fixed_terms)
                    store.save_glossary(glossary)
                    self.log(f"Sözlükte {len(fixed_terms)} karşılık düzeltildi: "
                             + ", ".join(f"{k}→{v}" for k, v in list(fixed_terms.items())[:8]))
                todo = [i for i, d in sorted(results.items()) if d is not source[i] and d.checked < quality.QUALITY_VERSION]
                # Kaynağın %12'den fazlası çevrilmemişse (bölüm sonu ya da ortası atlanmış) bölüm baştan çevrilir.
                redo = [i for i in todo if quality.missing_share(source[i], results[i]) > 0.12]
                if redo:
                    self.log(f"Denetim: {len(redo)} bölümün önemli bir kısmı çevrilmemiş, baştan çevrilecek: {redo[:20]}")
                    for i in redo:
                        store.drop_tr(i)  # eski çeviri yedeğe (Kitaplık → Eskiye dön)
                        results.pop(i, None)
                        pending.append(source[i])
                    pending.sort(key=lambda c: c.index)
                    todo = [i for i in todo if i not in redo]
                heavy = [source[i] for i in todo if quality.archaic_density(results[i]) > 4]
                self.log(f"Denetim: {len(todo)} bölüm denetlenecek" + (f"; {len(heavy)} bölüm eski/ağdalı dille yazılmış, baştan redakte edilecek: {[c.index for c in heavy][:20]}" if heavy else ""))
                k = 0
                while k < len(heavy):
                    self._check_cancel()
                    group = tr.plan_batch(heavy[k:], o.batch)
                    k += len(group)
                    edit([results[c.index] for c in group])
                self.p.phase = f"denetleniyor ({tr.model})"
                self.p.total, self.p.done = len(todo), 0
                for j in range(0, len(todo), 30):  # 30 bölümün sorunlu paragrafları 40'arlı isteklerle
                    self._check_cancel()
                    review(todo[j:j + 30], 30)
                    self.p.done = min(len(todo), j + 30)
                self.p.total, self.p.done = len(chapters), len(results)
            except QuotaExhausted as e:
                stop_reason = str(e)

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
                outs, new_terms = tr.translate_batch(group, glossary, context_before(group[0].index),
                                                     lookahead_after(group[-1].index))
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
                if tr.self_edit:
                    done.edited = True  # tek geçişte redaksiyon çeviriyle birlikte yapıldı
                store.save_tr(done)
                results[done.index] = done
                self.p.done += 1
                translated_now += 1
                sus = untranslated_suspects(source[done.index].paragraphs, done.paragraphs, glossary) if o.lang != "en" else []
                self.log(f"  çevrildi {self.p.done}/{self.p.total}: {done.title}"
                         + (f"  (İngilizce kalmış olabilir: {', '.join(sus[:8])}{' → redaksiyonda düzeltilecek' if o.edit else ''})" if sus else ""))
            save_state(new_terms)
            missed = [c.index for c in group if c.index not in got]
            failed.extend(missed)
            if outs and o.edit and not tr.self_edit:
                try:
                    edit(outs)
                except QuotaExhausted as e:
                    stop_reason = str(e)  # taslaklar kayıtlı; redaksiyon sonraki çalıştırmada
                except FatalError:
                    raise
            if outs and not stop_reason:
                try:
                    review([d.index for d in outs], max(8, len(outs)))  # paket tek denetim isteğinde
                except QuotaExhausted as e:
                    stop_reason = str(e)  # denetim sonraki "denetle" çalıştırmasında
            streak = streak + 1 if missed and not outs else 0
            if streak >= 3:
                self.log("  Art arda 3 istek başarısız; 5 dk bekleyip devam ediliyor")
                wait(300)
                streak = 0

        # 3) Bu çalıştırmada çevrilemeyen bölümler: kota varken tek tek bir kez daha dene.
        retry = [n for n in dict.fromkeys(failed) if n not in results]
        if retry and not stop_reason and not self.p.notice:
            self.log(f"Çevrilemeyen {len(retry)} bölüm tek tek yeniden deneniyor: {retry[:20]}")
        for n in (retry if not stop_reason and not self.p.notice else []):
            self._check_cancel()
            try:
                done, new_terms = tr.translate_chapter(source[n], glossary, context_before(n), lookahead_after(n))
            except QuotaExhausted as e:
                stop_reason = str(e)
                break
            except FatalError:
                raise
            except TranslationError as e:
                self.log(f"  {n}. bölüm yine çevrilemedi ({e})")
                continue
            if tr.self_edit:
                done.edited = True
            store.save_tr(done)
            results[n] = done
            self.p.done += 1
            save_state(new_terms)
            self.log(f"  çevrildi (ikinci deneme) {n}: {done.title}")
            if o.edit and not tr.self_edit:
                try:
                    edit([done])
                except QuotaExhausted as e:
                    stop_reason = str(e)
                    break

        if stop_reason:
            if not results:
                raise QuotaExhausted(stop_reason)
            # Tüm modellerin kotası bitti: çevrilenlerle kısmi kitap çıkar; tekrar başlatınca kaldığı yerden sürer.
            self.log(f"Çeviri durdu: {stop_reason}")
            self.p.error = f"Kısmi: {len(results)} bölüm çevrili ({stop_reason})"

        # Sözlük denetimi: kitap bitince (ya da "denetle"de) en iyi model en sık terimleri gözden geçirir; yanlış
        # karşılıklar bütün çevrilmiş bölümlerde çekim ekiyle uyumlu biçimde değiştirilir.
        from .quality import GLOSSARY_AUDIT_VERSION
        complete = all(i in results and results[i] is not source[i] for i in source if source[i].paragraphs)
        audit_fn = getattr(tr, "audit_glossary", None)
        if audit_fn and o.lang != "en" and not stop_reason and not self.p.notice and glossary and (
                o.audit or (complete and store.load_glossary_audit().get("version") != GLOSSARY_AUDIT_VERSION)):
            self.p.phase = f"sözlük denetleniyor ({tr.model})"
            if not getattr(tr, "audit_ready", lambda: True)():
                self.log("Sözlük denetimi ertelendi: en iyi modelin kotası dolu, sonraki çalıştırmada yapılacak")
                audit_fn = None
            try:
                if audit_fn:
                    self._glossary_audit(tr, audit_fn, source, results, glossary, store)
            except QuotaExhausted as e:
                self.log(f"Sözlük denetimi ertelendi: {e}")

        # Art arda iki kez yazılmış paragraflar ve bölüm sonuna eklenmiş sonraki bölüm başı (modelsiz, kesin kural).
        removed = 0
        for i in sorted(results):
            d = results[i]
            if d is source[i]:
                continue
            fixed, n = quality.drop_repeats(source[i], d)
            if i + 1 in source:
                fixed, m = quality.drop_next_chapter_copy(source[i], fixed, source[i + 1])
                n += m
            nxt = results.get(i + 1)
            if nxt is not None and nxt is not source.get(i + 1):
                fixed, m = quality.drop_boundary_repeat(source[i], fixed, source[i + 1], nxt)
                n += m
            if n:
                store.save_tr(fixed)
                results[i] = fixed
                removed += n
        if removed:
            self.log(f"Tekrar temizliği: {removed} tekrarlanmış paragraf atıldı")

        # Kitap, çevrilmiş son bölüme kadar gider; arada çevrilemeyenler orijinal metniyle kalır.
        last = max(results, default=0)
        out = [results.get(ch.index) or Chapter(ch.index, f"[Çevrilemedi] {ch.title}", ch.url, ch.paragraphs)
               for ch in chapters if ch.index <= last]
        failed = [n for n in failed if n <= last and n not in results]
        if failed:
            self.p.report["cevrilemeyen"] = failed
            self.p.notice = (self.p.notice + " " if self.p.notice else "") + (
                f"{len(failed)} bölüm çevrilemedi ve kitapta orijinal metniyle duruyor. Aynı linkle tekrar Başlat'a "
                "basınca yalnız bunlar denenir.")
            self.log(f"{len(failed)} bölüm çevrilemedi, kitapta orijinal metniyle duruyor: {failed[:30]}. "
                     "Aynı linkle tekrar başlatınca yalnız bunlar ve kalanlar denenir.")
        if self.p.error:
            self.log(f"{len(out)} bölümlük kısmi kitap hazırlanıyor. Kota yenilenince aynı linkle başlat, kaldığı yerden sürer.")
        self.log(f"Terim sözlüğü: {store.glossary_path} · hikâye hafızası: {store.memory_path}")
        return out
