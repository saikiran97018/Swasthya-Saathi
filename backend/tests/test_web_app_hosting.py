"""One server for the whole product: the API plus the built web app (used by the Docker / Render deployment)."""
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fakes import FakeBhashini, FakeLLM, fake_tools_client

P = "/api/v1"


def build(tmp_path, with_index=True):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-1a2b3c.js").write_text("console.log('app')")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    if with_index:
        (tmp_path / "index.html").write_text("<!doctype html><title>Swasthya Saathi</title><div id=root></div>")
    secret = tmp_path.parent / "outside-secret.txt"
    secret.write_text("TOP SECRET")
    app = create_app(
        Settings(_env_file=None, bhashini_user_id="u", bhashini_ulca_api_key="k", reminder_poll_seconds=0, static_dir=str(tmp_path)),
        llm_client=FakeLLM().client(), bhashini_client=FakeBhashini().client(), tools_client=fake_tools_client(),
    )
    return TestClient(app)


def test_pages_files_and_api_all_come_from_one_server(tmp_path):
    with build(tmp_path) as c:
        home = c.get("/")
        assert home.status_code == 200 and "Swasthya Saathi" in home.text and home.headers["cache-control"] == "no-cache"
        for page in ("/sos", "/call", "/chat/123", "/settings/language"):  # client-side routes: a refresh must still open the app
            assert c.get(page).text == home.text, page
        js = c.get("/assets/app-1a2b3c.js")
        assert js.status_code == 200 and "immutable" in js.headers["cache-control"]  # hashed build files can be cached for a year
        assert c.get("/favicon.svg").text == "<svg/>"
        assert c.get(f"{P}/health").json()["status"] == "ok"  # the API still wins over the catch-all
        assert c.get("/docs").status_code == 200


def test_unknown_api_address_is_a_json_404_not_the_web_page(tmp_path):
    with build(tmp_path) as c:
        r = c.get(f"{P}/nothing-here")
        assert r.status_code == 404 and r.json()["error"]["code"] == "route_not_found"
        assert c.get("/api/v1").status_code == 404


def test_files_outside_the_web_folder_are_never_served(tmp_path):
    with build(tmp_path) as c:
        for sneaky in ("../outside-secret.txt", "..%2Foutside-secret.txt", "%2e%2e/outside-secret.txt", "assets/../../outside-secret.txt"):
            r = c.get("/" + sneaky)
            assert "TOP SECRET" not in r.text, sneaky


def test_without_a_built_app_nothing_is_mounted(tmp_path):
    with build(tmp_path, with_index=False) as c:
        assert c.get("/").status_code == 404 and c.get(f"{P}/health").status_code == 200


def test_render_public_address_is_used_for_live_calls(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://swasthya-saathi.onrender.com/")
    assert Settings(_env_file=None).agora_public_url == "https://swasthya-saathi.onrender.com"
    assert Settings(_env_file=None, agora_public_url="https://mine.example.com").agora_public_url == "https://mine.example.com"  # an explicit value wins
