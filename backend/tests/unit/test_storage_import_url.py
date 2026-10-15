"""Storage import-url refuses internal addresses before any fetch (ROADMAP P1r-2)."""

import httpx
import pytest
from fastapi import HTTPException

from lokilinux.api.v1.routers.storage import import_object_from_url
from lokilinux.schemas.storage import ImportUrlRequest


@pytest.fixture
def no_fetch(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("import-url fetched a URL the SSRF guard should refuse")

    monkeypatch.setattr(httpx, "AsyncClient", refuse)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::ffff:127.0.0.1]/",
        "file:///etc/passwd",
    ],
)
async def test_internal_url_refused_before_fetch(url, no_fetch):
    body = ImportUrlRequest(url=url, category="compliance.report")

    with pytest.raises(HTTPException) as exc:
        await import_object_from_url(body, db=None, storage=None, current_user={"username": "op"})

    assert exc.value.status_code == 422
    assert "url refused" in exc.value.detail
