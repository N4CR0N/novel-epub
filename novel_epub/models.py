from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ChapterRef:
    index: int  # 1'den başlayan sıra (sitedeki sıra)
    title: str
    url: str


@dataclass
class Chapter:
    index: int
    title: str
    url: str
    paragraphs: list[str]
    next_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Chapter":
        return cls(**{k: d.get(k) for k in ("index", "title", "url", "paragraphs", "next_url")})

    @property
    def char_count(self) -> int:
        return sum(len(p) for p in self.paragraphs)


@dataclass
class Novel:
    url: str
    title: str
    source: str
    author: str = ""
    description: str = ""
    cover_url: str = ""
    genres: str = ""
    chapters: list[ChapterRef] = field(default_factory=list)
    # Bölüm listesi yoksa (genel kaynak), ilk bölümden "sonraki" bağlantılarıyla gezilir.
    follow_next: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Novel":
        d = dict(d)
        d["chapters"] = [ChapterRef(**c) for c in d.get("chapters", [])]
        return cls(**d)
