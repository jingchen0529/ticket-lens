from fastapi.testclient import TestClient
from app.main import app
from app.core.cities import PRESET_CITIES

client = TestClient(app)


def test_facets_and_cities_endpoint(tmp_path, monkeypatch):
    test_db = tmp_path / "test_daxi.sqlite3"
    from app.core.config import load_config
    cfg = load_config()
    cfg.storage.db_path = str(test_db)
    monkeypatch.setattr("app.routers.shows.load_config", lambda: cfg)

    # 1. 验证 GET /api/facets 返回包含 380+ 城市的完整结构
    res_facets = client.get("/api/facets")
    assert res_facets.status_code == 200
    facets_data = res_facets.json()
    assert "city" in facets_data
    assert len(facets_data["city"]) >= len(PRESET_CITIES)
    assert "北京" in facets_data["city"]
    assert "和田" in facets_data["city"]
    assert "悉尼" in facets_data["city"]

    # 2. 验证 GET /api/cities 返回数据库城市列表
    res_cities = client.get("/api/cities")
    assert res_cities.status_code == 200
    cities_data = res_cities.json()
    assert isinstance(cities_data, list)
    assert len(cities_data) >= len(PRESET_CITIES)
    assert "成都" in cities_data
