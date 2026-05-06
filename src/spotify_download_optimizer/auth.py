from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from platformdirs import user_config_path

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = (
    "playlist-read-private",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-read-recently-played",
)


class AuthError(RuntimeError):
    """Raised when authentication cannot be completed."""


@dataclass(frozen=True)
class TokenData:
    access_token: str
    refresh_token: str | None
    expires_at: float
    scope: str
    token_type: str = "Bearer"

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - 60

    @classmethod
    def from_oauth_response(
        cls, data: dict[str, Any], existing_refresh_token: str | None = None
    ) -> TokenData:
        access_token = _required_str(data, "access_token")
        expires_in = int(data.get("expires_in", 3600))
        refresh_token = _optional_str(data.get("refresh_token")) or existing_refresh_token
        scope = _optional_str(data.get("scope")) or " ".join(SCOPES)
        token_type = _optional_str(data.get("token_type")) or "Bearer"
        return cls(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + expires_in,
            scope=scope,
            token_type=token_type,
        )

    @classmethod
    def from_cache(cls, data: dict[str, Any]) -> TokenData:
        return cls(
            access_token=_required_str(data, "access_token"),
            refresh_token=_optional_str(data.get("refresh_token")),
            expires_at=float(data["expires_at"]),
            scope=_optional_str(data.get("scope")) or "",
            token_type=_optional_str(data.get("token_type")) or "Bearer",
        )

    def to_cache(self) -> dict[str, str | float | None]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
            "token_type": self.token_type,
        }


@dataclass
class CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    result: ClassVar[CallbackResult]
    expected_path: ClassVar[str]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != self.expected_path:
            self.send_response(404)
            self.end_headers()
            return

        query = parse_qs(parsed.query)
        self.result.code = _first_query_value(query, "code")
        self.result.state = _first_query_value(query, "state")
        self.result.error = _first_query_value(query, "error")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        message = (
            "Spotify authentication finished. You can close this tab.\n"
            if self.result.code
            else "Spotify authentication did not return an authorization code.\n"
        )
        self.wfile.write(message.encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        return


class TokenStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_token_cache_path()

    def load(self) -> TokenData:
        if not self.path.exists():
            raise AuthError(
                "No Spotify token cache found. Run `spotify-download-optimizer auth login` first."
            )
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise AuthError(f"Could not read Spotify token cache: {exc}") from exc
        if not isinstance(data, dict):
            raise AuthError("Spotify token cache is not a JSON object.")
        return TokenData.from_cache(data)

    def save(self, token: TokenData) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, stat.S_IRWXU)
        encoded = json.dumps(token.to_cache(), indent=2, sort_keys=True).encode("utf-8")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "wb") as file:
            file.write(encoded)
            file.write(b"\n")
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)


class OAuthTokenProvider:
    def __init__(
        self,
        client_id: str,
        token_store: TokenStore | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.client_id = client_id
        self.token_store = token_store or TokenStore()
        self.http_client = http_client

    def get_access_token(self, force_refresh: bool = False) -> str:
        token = self.token_store.load()
        if force_refresh or token.is_expired:
            token = refresh_access_token(
                client_id=self.client_id,
                refresh_token=token.refresh_token,
                existing_token=token,
                token_store=self.token_store,
                http_client=self.http_client,
            )
        return token.access_token


def default_token_cache_path() -> Path:
    configured = os.environ.get("SPOTIFY_TOKEN_CACHE")
    if configured:
        return Path(configured).expanduser()
    return user_config_path("spotify-download-optimizer", appauthor=False) / "tokens.json"


def client_id_from_env() -> str:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    if not client_id:
        raise AuthError("SPOTIFY_CLIENT_ID must be set.")
    return client_id


def redirect_uri_from_env() -> str:
    return os.environ.get("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT_URI)


def run_pkce_login(
    client_id: str,
    redirect_uri: str,
    token_store: TokenStore | None = None,
    http_client: httpx.Client | None = None,
) -> TokenData:
    verifier = generate_code_verifier()
    challenge = code_challenge(verifier)
    state = secrets.token_urlsafe(24)
    authorization_url = build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge_value=challenge,
        state=state,
    )

    result = wait_for_callback(redirect_uri, authorization_url)
    if result.error:
        raise AuthError(f"Spotify authorization failed: {result.error}")
    if result.state != state:
        raise AuthError("Spotify authorization state did not match.")
    if not result.code:
        raise AuthError("Spotify authorization did not return a code.")

    token = exchange_code_for_token(
        client_id=client_id,
        code=result.code,
        redirect_uri=redirect_uri,
        code_verifier=verifier,
        http_client=http_client,
    )
    (token_store or TokenStore()).save(token)
    return token


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    code_challenge_value: str,
    state: str,
) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "code_challenge_method": "S256",
        "code_challenge": code_challenge_value,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def wait_for_callback(redirect_uri: str, authorization_url: str) -> CallbackResult:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise AuthError("SPOTIFY_REDIRECT_URI must be a local http URL for CLI login.")
    host = parsed.hostname
    port = parsed.port
    if port is None:
        raise AuthError("SPOTIFY_REDIRECT_URI must include a port for CLI login.")

    result = CallbackResult()
    OAuthCallbackHandler.result = result
    OAuthCallbackHandler.expected_path = parsed.path or "/"

    print("Open this URL to authorize Spotify access:")
    print(authorization_url)
    webbrowser.open(authorization_url)

    with HTTPServer((host, port), OAuthCallbackHandler) as server:
        server.handle_request()
    return result


def exchange_code_for_token(
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    http_client: httpx.Client | None = None,
) -> TokenData:
    close_client = http_client is None
    client = http_client or httpx.Client(timeout=20)
    try:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise AuthError(f"Could not exchange Spotify authorization code: {exc}") from exc
    finally:
        if close_client:
            client.close()
    if not isinstance(data, dict):
        raise AuthError("Spotify token response was not a JSON object.")
    return TokenData.from_oauth_response(data)


def refresh_access_token(
    client_id: str,
    refresh_token: str | None,
    existing_token: TokenData,
    token_store: TokenStore,
    http_client: httpx.Client | None = None,
) -> TokenData:
    if not refresh_token:
        raise AuthError("Spotify token cache does not contain a refresh token. Log in again.")
    close_client = http_client is None
    client = http_client or httpx.Client(timeout=20)
    try:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise AuthError(f"Could not refresh Spotify access token: {exc}") from exc
    finally:
        if close_client:
            client.close()
    if not isinstance(data, dict):
        raise AuthError("Spotify refresh response was not a JSON object.")
    token = TokenData.from_oauth_response(data, existing_refresh_token=existing_token.refresh_token)
    token_store.save(token)
    return token


def generate_code_verifier(length: int = 64) -> str:
    return secrets.token_urlsafe(length)[:128]


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise AuthError(f"Spotify token response is missing `{key}`.")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]
