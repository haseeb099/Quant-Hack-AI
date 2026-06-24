from src.integrations.mt5_config import read_mt5_profile, server_candidates_from_profile
from src.integrations.mt5_session import _strip_env_quotes, load_mt5_credentials, server_candidates


def test_server_candidates_from_profile(monkeypatch):
    monkeypatch.setenv("MT5_SERVER", "3.11.134.149:443")

    def fake_profile():
        return {"server": "FTWorldwide-MainTrade"}

    monkeypatch.setattr(
        "src.integrations.mt5_config.read_mt5_profile",
        fake_profile,
    )
    assert server_candidates_from_profile("3.11.134.149:443") == [
        "3.11.134.149:443",
        "3.11.134.149",
        "FTWorldwide-MainTrade",
    ]


def test_strip_env_quotes():
    assert _strip_env_quotes('"%Brn783W8V"') == "%Brn783W8V"
    assert _strip_env_quotes("FTWorldwide-MainTrade") == "FTWorldwide-MainTrade"


def test_load_mt5_credentials_strips_password_quotes(monkeypatch):
    monkeypatch.setenv("MT5_LOGIN", "10438")
    monkeypatch.setenv("MT5_PASSWORD", '"secret"')
    monkeypatch.setenv("MT5_SERVER", "FTWorldwide-MainTrade")
    creds = load_mt5_credentials()
    assert creds.password == "secret"


def test_read_mt5_profile_shape():
    profile = read_mt5_profile()
    assert set(profile) >= {
        "login",
        "server",
        "api_enabled",
        "algo_enabled",
        "dll_import_enabled",
        "path",
    }
