"""Kitap başına yerel önbellek: yarıda kalan indirme/çeviri kaldığı yerden sürer."""
from __future__ import annotations

import json
import re
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
    def __init__(self, root: Path, novel: Novel | None = None, dirname: str | None = None):
        self.dir = Path(root) / (dirname or f"{novel.source}-{slugify(novel.title)}")
        (self.dir / "ham").mkdir(parents=True, exist_ok=True)
        (self.dir / "ceviri").mkdir(parents=True, exist_ok=True)
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
        p = self._p("ceviri", index)
        return Chapter.from_dict(json.loads(p.read_text("utf-8"))) if p.exists() else None

    def save_tr(self, ch: Chapter) -> None:
        _write_json(self._p("ceviri", ch.index), ch.to_dict())

    # Terim sözlüğü: kaynak terim -> Türkçe karşılık. Elle düzenlenebilir (sozluk.json).
    @property
    def glossary_path(self) -> Path:
        return self.dir / "sozluk.json"

    def load_glossary(self) -> dict[str, str]:
        p = self.glossary_path
        return json.loads(p.read_text("utf-8")) if p.exists() else {}

    def save_glossary(self, g: dict[str, str]) -> None:
        _write_json(self.glossary_path, dict(sorted(g.items(), key=lambda kv: kv[0].lower())))

    # Hikâye hafızası: kısa özet + karakter notları; her istekte modele gider, her yanıtla güncellenir.
    @property
    def memory_path(self) -> Path:
        return self.dir / "hafiza.json"

    def load_memory(self) -> dict:
        p = self.memory_path
        m = json.loads(p.read_text("utf-8")) if p.exists() else {}
        return {"summary": m.get("summary", ""), "characters": dict(m.get("characters", {}))}

    def save_memory(self, m: dict) -> None:
        _write_json(self.memory_path, m)

    def drop_tr(self, index: int) -> bool:
        p = self._p("ceviri", index)
        if p.exists():
            p.unlink()
            return True
        return False

    def counts(self) -> dict:
        tr = list((self.dir / "ceviri").glob("*.json"))
        edited = sum(1 for p in tr if '"edited": true' in p.read_text("utf-8"))
        return {"ham": len(list((self.dir / "ham").glob("*.json"))), "ceviri": len(tr), "redakte": edited}
