"""Testlerdeki Flask istemcisi uygulama penceresi gibi davranır: erişim anahtarını (X-Token) kendiliğinden ekler.
Anahtarsız isteği sınamak için headers={"X-Token": ""} verilir."""
from flask.testing import FlaskClient

from novel_epub import web


class _WindowClient(FlaskClient):
    def open(self, *args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("X-Token", web.API_TOKEN)
        kwargs["headers"] = headers
        return super().open(*args, **kwargs)


web.app.test_client_class = _WindowClient
