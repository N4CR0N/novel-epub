try:  # derleme hattı _surum.py'yi yazar (ör. "1.1.2"); kaynak koddan çalışırken "dev"
    from ._surum import SURUM as __version__
except ImportError:
    __version__ = "dev"
