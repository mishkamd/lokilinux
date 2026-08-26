"""install_command platform URL resolution for POST /agent/enrollment-token.

Precedence: DB setting agent.platform_url (UI "Configure URLs") > env
PLATFORM_URL. The response carries url_source ("db" | "env") so the frontend
knows whether to show the backend command as-is or rebuild it from the live
browser origin.
"""

import pytest


async def _set_db_platform_url(db_session, url):
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from lokilinux.models.audit import Setting

    await db_session.execute(
        pg_insert(Setting)
        .values(key="agent.platform_url", value=url, value_type="string")
        .on_conflict_do_update(index_elements=["key"], set_={"value": url})
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_install_command_uses_env_url_by_default(client):
    from lokilinux.config import get_settings

    resp = await client.post("/api/v1/agent/enrollment-token", json={})
    assert resp.status_code == 200
    body = resp.json()

    expected = get_settings().platform_url.rstrip("/")
    assert body["url_source"] == "env"
    assert body["install_command"].startswith(f"curl -fsSL {expected}/api/v1/agent/install.sh")
    assert f"--url={expected}" in body["install_command"]
    assert f"--token={body['token']}" in body["install_command"]


@pytest.mark.asyncio
async def test_install_command_prefers_db_override(client, db_session):
    await _set_db_platform_url(db_session, "http://ops.example.com:3000/")
    resp = await client.post("/api/v1/agent/enrollment-token", json={})
    assert resp.status_code == 200
    body = resp.json()

    assert body["url_source"] == "db"
    # trailing slash stripped, DB URL wins over env default
    assert body["install_command"].startswith("curl -fsSL http://ops.example.com:3000/api/v1/agent/install.sh")
    assert "--url=http://ops.example.com:3000" in body["install_command"]
