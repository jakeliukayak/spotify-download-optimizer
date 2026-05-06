from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Protocol

import httpx

from spotify_download_optimizer.models import (
    PlaylistItem,
    RecentTrack,
    playlist_item_from_api,
    recent_track_from_api,
)

API_BASE_URL = "https://api.spotify.com/v1"
CHUNK_SIZE = 100


class AccessTokenProvider(Protocol):
    def get_access_token(self, force_refresh: bool = False) -> str:
        """Return a usable Spotify access token."""


class SpotifyClient:
    def __init__(
        self,
        token_provider: AccessTokenProvider,
        *,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_rate_limit_retries: int = 3,
    ) -> None:
        self.token_provider = token_provider
        self.http_client = http_client or httpx.Client(timeout=30)
        self._owns_http_client = http_client is None
        self.sleep = sleep
        self.max_rate_limit_retries = max_rate_limit_retries

    def close(self) -> None:
        if self._owns_http_client:
            self.http_client.close()

    def __enter__(self) -> SpotifyClient:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def get_playlist_items(self, playlist_id: str) -> tuple[PlaylistItem, ...]:
        limit = 50
        offset = 0
        items: list[PlaylistItem] = []

        while True:
            response = self._request(
                "GET",
                f"/playlists/{playlist_id}/items",
                params={
                    "limit": limit,
                    "offset": offset,
                    "additional_types": "track,episode",
                    "fields": (
                        "items(is_local,track(uri,name,type,artists(name)),"
                        "item(uri,name,type,artists(name))),next,total"
                    ),
                },
            )
            payload = _json_object(response)
            raw_items = payload.get("items")
            if not isinstance(raw_items, list):
                raise ValueError("Spotify playlist response did not include an items list.")

            for raw_item in raw_items:
                if isinstance(raw_item, dict):
                    items.append(playlist_item_from_api(raw_item, position=len(items)))

            next_url = payload.get("next")
            if not next_url:
                break
            offset += limit

        return tuple(items)

    def get_recently_played_tracks(self, *, limit: int = 50) -> tuple[RecentTrack, ...]:
        response = self._request(
            "GET",
            "/me/player/recently-played",
            params={"limit": limit},
        )
        payload = _json_object(response)
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("Spotify recently played response did not include an items list.")

        tracks: list[RecentTrack] = []
        for raw_item in raw_items:
            if isinstance(raw_item, dict):
                tracks.append(recent_track_from_api(raw_item, position=len(tracks)))
        return tuple(tracks)

    def replace_playlist_items(self, playlist_id: str, uris: Sequence[str]) -> None:
        chunks = tuple(_chunked(uris, CHUNK_SIZE))
        first_chunk = chunks[0] if chunks else ()
        self._request("PUT", f"/playlists/{playlist_id}/items", json={"uris": list(first_chunk)})
        for chunk in chunks[1:]:
            self._request("POST", f"/playlists/{playlist_id}/items", json={"uris": list(chunk)})

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        rate_limit_retries = 0
        force_refresh = False

        while True:
            token = self.token_provider.get_access_token(force_refresh=force_refresh)
            headers = dict(kwargs.pop("headers", {}))
            headers["Authorization"] = f"Bearer {token}"
            response = self.http_client.request(
                method,
                f"{API_BASE_URL}{path}",
                headers=headers,
                **kwargs,
            )

            if response.status_code == 401 and not force_refresh:
                force_refresh = True
                continue

            if response.status_code == 429 and rate_limit_retries < self.max_rate_limit_retries:
                rate_limit_retries += 1
                retry_after = _retry_after_seconds(response)
                self.sleep(retry_after)
                continue

            response.raise_for_status()
            return response


def _chunked(values: Sequence[str], size: int) -> Iterable[tuple[str, ...]]:
    for index in range(0, len(values), size):
        yield tuple(values[index : index + size])


def _retry_after_seconds(response: httpx.Response) -> float:
    value = response.headers.get("Retry-After")
    if value is None:
        return 1.0
    try:
        return max(float(value), 0.0)
    except ValueError:
        return 1.0


def _json_object(response: httpx.Response) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Spotify response was not a JSON object.")
    return payload
