from src.integrations.mt5_session import (
    account_matches,
    load_mt5_credentials,
    server_candidates,
)


class _FakeAccount:
    def __init__(self, login: int):
        self.login = login


def test_server_candidates_keeps_host_port_then_strips_port(monkeypatch):
    assert server_candidates("3.11.134.149:443") == ["3.11.134.149:443", "3.11.134.149"]


def test_account_matches():
    assert account_matches(_FakeAccount(10438), 10438)
    assert not account_matches(_FakeAccount(10438), 99999)
    assert not account_matches(None, 10438)


def test_load_mt5_credentials(monkeypatch):
    monkeypatch.setenv("MT5_LOGIN", "10438")
    monkeypatch.setenv("MT5_PASSWORD", "%Brn783W8V")
    monkeypatch.setenv("MT5_SERVER", "3.11.134.149:443")
    creds = load_mt5_credentials()
    assert creds.login == 10438
    assert creds.password == "%Brn783W8V"
    assert creds.server == "3.11.134.149:443"
