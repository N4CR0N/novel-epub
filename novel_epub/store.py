"""Kitap başına yerel önbellek: yarıda kalan indirme/çeviri kaldığı yerden sürer."""
from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path

from .models import Chapter, Novel


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:60] or "kitap"


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


class BookStore:
    def __init__(self, root: Path, novel: Novel | None = None, dirname: str | None = None, lang: str = "tr"):
        self.dir = Path(root) / (dirname or f"{novel.source}-{slugify(novel.title)}")
        # Hedef dil başına ayrı çeviri/sözlük/hafıza; Türkçe eski dosya adlarını korur (geriye uyumlu).
        self.lang = lang
        self.sfx = "" if lang == "tr" else f"-{lang}"
        self.tr_kind = f"ceviri{self.sfx}"
        (self.dir / "ham").mkdir(parents=True, exist_ok=True)
        (self.dir / self.tr_kind).mkdir(parents=True, exist_ok=True)
        if novel is not None:
            _write_json(self.dir / "kitap.json", novel.to_dict())

    def _p(self, kind: str, index: int) -> Path:
        return self.dir / kind / f"{index:05d}.json"

    def has_raw(self, index: int) -> bool:
        return self._p("ham", index).exists()

    def load_raw(self, index: int) -> Chapter | None:
        p = self._p("ham", index)
        return Chapter.from_dict(json.loads(p.read_text("utf-8"))) if p.exists() else None

    def save_raw(self, ch: Chapter) -> None:
        _write_json(self._p("ham", ch.index), ch.to_dict())

    def drop_raw(self, index: int) -> None:
        self._p("ham", index).unlink(missing_ok=True)

    def load_tr(self, index: int) -> Chapter | None:
        p = self._p(self.tr_kind, index)
        return Chapter.from_dict(json.loads(p.read_text("utf-8"))) if p.exists() else None

    def save_tr(self, ch: Chapter) -> None:
        _write_json(self._p(self.tr_kind, ch.index), ch.to_dict())

    # Terim sözlüğü: kaynak terim -> Türkçe karşılık. Elle düzenlenebilir (sozluk.json).
    @property
    def glossary_path(self) -> Path:
        return self.dir / f"sozluk{self.sfx}.json"

    def load_glossary(self) -> dict[str, str]:
        p = self.glossary_path
        return json.loads(p.read_text("utf-8")) if p.exists() else {}

    def save_glossary(self, g: dict[str, str]) -> None:
        _write_json(self.glossary_path, dict(sorted(g.items(), key=lambda kv: kv[0].lower())))

    # Hikâye hafızası: kısa özet + karakter notları; her istekte modele gider, her yanıtla güncellenir.
    @property
    def memory_path(self) -> Path:
        return self.dir / f"hafiza{self.sfx}.json"

    def load_memory(self) -> dict:
        p = self.memory_path
        m = json.loads(p.read_text("utf-8")) if p.exists() else {}
        return {"summary": m.get("summary", ""), "characters": dict(m.get("characters", {})),
                "address": dict(m.get("address", {}))}

    def save_memory(self, m: dict) -> None:
        _write_json(self.memory_path, m)

    # Yeniden çevirmede eski çeviri silinmez, ceviri_eski/ altına zaman damgasıyla taşınır.
    def _backups(self, index: int) -> list[Path]:
        return sorted((self.dir / f"ceviri_eski{self.sfx}").glob(f"{index:05d}_*.json"))

    def drop_tr(self, index: int) -> bool:
        """Çeviriyi yedeğe taşır; sonraki çalıştırmada bölüm yeniden çevrilir."""
        p = self._p(self.tr_kind, index)
        if not p.exists():
            return False
        bak = self.dir / f"ceviri_eski{self.sfx}"
        bak.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        n = 0
        while (bak / f"{index:05d}_{stamp}_{n}.json").exists():
            n += 1
        p.replace(bak / f"{index:05d}_{stamp}_{n}.json")
        return True

    def restore_tr(self, index: int) -> bool:
        """En son yedeği geri getirir; o an duran çeviri varsa o da yedeğe geçer (yer değiştirir)."""
        backups = self._backups(index)
        if not backups:
            return False
        latest = backups[-1]
        tmp = latest.with_suffix(".geri")
        latest.replace(tmp)
        self.drop_tr(index)
        tmp.replace(self._p(self.tr_kind, index))
        return True

    def backup_count(self) -> int:
        d = self.dir / f"ceviri_eski{self.sfx}"
        return len({p.name[:5] for p in d.glob("*.json")}) if d.exists() else 0

    # Kitaba özel çeviri talimatı (üslup, hitaplar, zaman kipi…): sistem talimatına eklenir.
    @property
    def notes_path(self) -> Path:
        return self.dir / f"talimat{self.sfx}.txt"

    def load_notes(self) -> str:
        return self.notes_path.read_text("utf-8").strip() if self.notes_path.exists() else ""

    def save_notes(self, text: str) -> None:
        self.notes_path.write_text(text.strip() + "\n", encoding="utf-8")

    def counts(self) -> dict:
        tr = list((self.dir / self.tr_kind).glob("*.json"))
        edited = sum(1 for p in tr if '"edited": true' in p.read_text("utf-8"))
        return {"ham": len(list((self.dir / "ham").glob("*.json"))), "ceviri": len(tr), "redakte": edited,
                "yedek": self.backup_count()}
