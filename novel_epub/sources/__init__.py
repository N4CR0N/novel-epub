from ..fetcher import Fetcher
from .base import Source
from .freewebnovel import FreeWebNovel
from .generic import Generic
from .novelbin import NovelBin
from .novelfull import NovelFull
from .royalroad import RoyalRoad

SOURCES: list[type[Source]] = [FreeWebNovel, NovelBin, NovelFull, RoyalRoad]


def source_for(url: str, fetcher: Fetcher) -> Source:
    for cls in SOURCES:
        if cls.matches(url):
            return cls(fetcher)
    return Generic(fetcher)
