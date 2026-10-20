from ..fetcher import Fetcher
from .base import Source
from .freewebnovel import FreeWebNovel
from .generic import Generic
from .novelbin import NovelBin

SOURCES: list[type[Source]] = [FreeWebNovel, NovelBin]


def source_for(url: str, fetcher: Fetcher) -> Source:
    for cls in SOURCES:
        if cls.matches(url):
            return cls(fetcher)
    return Generic(fetcher)
