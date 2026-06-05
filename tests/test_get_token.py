from arrows.auth import get_token


class DummyResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_get_token_uses_password_grant_and_does_not_open_browser(monkeypatch, capsys):
    called = {}

    def fake_post(url, data=None, **kwargs):
        called["url"] = url
        called["data"] = data
        return DummyResponse(200, {"access_token": "abc123"})

    def fake_open(url):
        raise AssertionError("Browser should not be opened when using password grant")

    monkeypatch.setattr(get_token.requests, "post", fake_post)
    monkeypatch.setattr(get_token.webbrowser, "open", fake_open)

    get_token.get_token(dev=False, username="test-user", password="secret")
    captured = capsys.readouterr()

    assert "Attempting password grant login" in captured.out
    assert "Access Token: abc123" in captured.out
    assert called["data"]["grant_type"] == "password"
    assert called["data"]["username"] == "test-user"
    assert called["data"]["password"] == "secret"


def test_get_token_invalid_credentials_does_not_fallback_to_browser(monkeypatch):
    def fake_post(url, data=None, **kwargs):
        return DummyResponse(
            400,
            {"error": "invalid_grant", "error_description": "Invalid user credentials"},
        )

    monkeypatch.setattr(get_token.requests, "post", fake_post)

    try:
        get_token.get_token(dev=False, username="test-user", password="badpass")
    except RuntimeError as exc:
        assert "Password grant failed" in str(exc)
        assert "invalid_grant" in str(exc)
        assert "Invalid user credentials" in str(exc)
