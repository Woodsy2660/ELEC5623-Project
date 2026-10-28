"""The Vercel app is the same fixture API, under /api, plus the built UI."""

from pathlib import Path

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.store import reset_store


def test_hosted_serves_the_ui_and_prefixes_the_api(tmp_path: Path) -> None:
    reset_store()
    (tmp_path / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "mark.txt").write_text("logo", encoding="utf-8")

    hosted = create_app(api_prefix="/api", use_fixtures=True)
    hosted.frontend("/", directory=tmp_path, fallback="index.html", check_dir=False)
    client = TestClient(hosted)

    projects = client.get("/api/projects")
    assert projects.status_code == 200
    assert projects.json()

    page = client.get("/projects/D1/register", headers={"Accept": "text/html"})
    assert page.status_code == 200
    assert '<div id="root">' in page.text

    missed = client.get("/projects/D1/register", headers={"Accept": "application/json"})
    assert missed.status_code == 404

    still_api = client.get("/api/projects", headers={"Accept": "text/html"})
    assert still_api.status_code == 200
    assert still_api.headers["content-type"].startswith("application/json")

    asset = client.get("/assets/mark.txt")
    assert asset.status_code == 200
    assert asset.text == "logo"

    local = TestClient(create_app(use_fixtures=True))
    assert local.get("/projects").status_code == 200
    assert local.get("/api/projects").status_code == 404


def test_vercel_entrypoint_serves_the_prefixed_api() -> None:
    reset_store()
    from src.api.hosted import app as vercel_app

    client = TestClient(vercel_app)
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert response.json()
    assert client.get("/projects", headers={"Accept": "application/json"}).status_code == 404
