"""Source boundaries and editable asset serving must survive repository relocation."""

from pathlib import Path

import httpx

from department_studio.api import create_app
from department_studio.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_backend_and_frontend_have_separate_source_roots():
    assert (ROOT / "backend/src/department_studio/api.py").is_file()
    assert not (ROOT / "src/department_studio").exists()
    assert not (ROOT / "backend/src/department_studio/static").exists()
    for name in ("index.html", "app.js", "style.css"):
        assert (ROOT / "frontend" / name).is_file()


async def test_source_ui_is_served_outside_repository_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(Settings(pi_executable="/bin/true", data_dir=tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
    ) as client:
        routes = (("/", "index.html"), ("/app.js", "app.js"), ("/style.css", "style.css"))
        for route, name in routes:
            response = await client.get(route)
            assert response.status_code == 200
            assert response.content == (ROOT / "frontend" / name).read_bytes()
