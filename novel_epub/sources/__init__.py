from ..fetcher import Fetcher
from .base import Source
from .freewebnovel import FreeWebNovel
from .generic import Generic
from .kakuyomu import Kakuyomu
from .novelbin import NovelBin
from .novelbuddy import NovelBuddy
from .novelfull import NovelFull
from .readwn import ReadWN
from .royalroad import RoyalRoad
from .syosetu import Syosetu
from .wattpad import Wattpad

SOURCES: list[type[Source]] = [FreeWebNovel, NovelBin, NovelFull, RoyalRoad, ReadWN, NovelBuddy, Wattpad, Syosetu,
                               Kakuyomu]


def source_for(url: str, fetcher: Fetcher) -> Source:
    for cls in SOURCES:
        if cls.matches(url):
            return cls(fetcher)
    return Generic(fetcher)
