from __future__ import annotations

import json

import httpx

from spotify_download_optimizer.client import API_BASE_URL, SpotifyClient


class FakeTokenProvider:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def get_access_token(self, force_refresh: bool = False) -> str:
        self.calls.append(force_refresh)
        return "refreshed-token" if force_refresh else "initial-token"


def test_get_playlist_items_paginates_and_parses_items():
    provider = FakeTokenProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer initial-token"
        offset = request.url.params.get("offset")
        if offset == "0":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "is_local": False,
                            "track": {
                                "uri": "spotify:track:a",
                                "name": "A",
                                "type": "track",
                                "artists": [{"name": "Artist A"}],
                            },
                        }
                    ],
                    "next": f"{API_BASE_URL}/playlists/pl/items?offset=50",
                    "total": 2,
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "is_local": False,
                        "track": {
                            "uri": "spotify:track:b",
                            "name": "B",
                            "type": "track",
                            "artists": [{"name": "Artist B"}],
                        },
                    }
                ],
                "next": None,
                "total": 2,
            },
        )

    client = SpotifyClient(
        provider,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    items = client.get_playlist_items("pl")

    assert [item.uri for item in items] == ["spotify:track:a", "spotify:track:b"]
    assert [item.position for item in items] == [0, 1]


def test_get_recently_played_tracks_parses_limited_history():
    provider = FakeTokenProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/me/player/recently-played"
        assert request.url.params["limit"] == "50"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "played_at": "2026-05-06T12:00:00Z",
                        "track": {
                            "uri": "spotify:track:a",
                            "name": "A",
                            "type": "track",
                            "is_local": False,
                            "artists": [{"name": "Artist A"}],
                        },
                    },
                    {
                        "played_at": "2026-05-06T11:55:00Z",
                        "track": {
                            "uri": "spotify:episode:ep",
                            "name": "Episode",
                            "type": "episode",
                            "is_local": False,
                            "artists": [],
                        },
                    },
                ]
            },
        )

    client = SpotifyClient(
        provider,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    tracks = client.get_recently_played_tracks(limit=50)

    assert [track.uri for track in tracks] == ["spotify:track:a", "spotify:episode:ep"]
    assert tracks[0].display_name == "A - Artist A"
    assert tracks[0].played_at == "2026-05-06T12:00:00Z"
    assert tracks[1].is_spotify_track is False


def test_request_refreshes_token_once_after_401():
    provider = FakeTokenProvider()
    responses = iter(
        [
            httpx.Response(401, json={"error": {"message": "expired"}}),
            httpx.Response(200, json={"items": [], "next": None, "total": 0}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    client = SpotifyClient(
        provider,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.get_playlist_items("pl") == ()
    assert provider.calls == [False, True]


def test_request_retries_429_using_retry_after():
    provider = FakeTokenProvider()
    sleeps: list[float] = []
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "0.5"}, json={}),
            httpx.Response(200, json={"items": [], "next": None, "total": 0}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    client = SpotifyClient(
        provider,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    assert client.get_playlist_items("pl") == ()
    assert sleeps == [0.5]


def test_replace_playlist_items_replaces_then_appends_chunks():
    provider = FakeTokenProvider()
    seen: list[tuple[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen.append((request.method, body["uris"]))
        return httpx.Response(200, json={"snapshot_id": "snapshot"})

    client = SpotifyClient(
        provider,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    uris = [f"spotify:track:{index}" for index in range(205)]

    client.replace_playlist_items("pl", uris)

    assert [(method, len(chunk)) for method, chunk in seen] == [
        ("PUT", 100),
        ("POST", 100),
        ("POST", 5),
    ]
    assert seen[0][1][0] == "spotify:track:0"
    assert seen[-1][1][-1] == "spotify:track:204"
