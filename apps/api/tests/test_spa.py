"""SPA fallback must serve index.html for client routes in production."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_deep_links_return_the_shell(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>ShadeQueue</title>", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    (assets / "app.js").write_text("window.shadequeue=1", encoding="utf-8")
    monkeypatch.setattr("app.main.WEB_DIST_DIR", dist)

    with TestClient(create_app()) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "ShadeQueue" in home.text

        deep = client.get("/scenarios/new")
        assert deep.status_code == 200
        assert "ShadeQueue" in deep.text
        assert deep.headers["content-type"].startswith("text/html")

        portfolio = client.get("/portfolios/abc")
        assert portfolio.status_code == 200
        assert "ShadeQueue" in portfolio.text

        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "shadequeue" in asset.text

        missing_api = client.get("/api/definitely-missing")
        assert missing_api.status_code == 404
        assert missing_api.json()["detail"] == "Not Found"
