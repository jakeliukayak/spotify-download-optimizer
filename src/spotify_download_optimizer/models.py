from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TrackRef:
    uri: str | None
    name: str
    artists: tuple[str, ...]
    item_type: str | None
    is_local: bool

    @property
    def is_spotify_track(self) -> bool:
        return (
            self.uri is not None
            and self.uri.startswith("spotify:track:")
            and self.item_type == "track"
            and not self.is_local
        )

    @property
    def display_name(self) -> str:
        artist_text = ", ".join(self.artists)
        if artist_text:
            return f"{self.name} - {artist_text}"
        return self.name


@dataclass(frozen=True)
class PlaylistItem(TrackRef):
    position: int


@dataclass(frozen=True)
class RecentTrack(TrackRef):
    position: int
    played_at: str | None


@dataclass(frozen=True)
class RemovedPlaylistItem:
    item: PlaylistItem
    play_count: int
    reason: str


@dataclass(frozen=True)
class OptimizationResult:
    kept: tuple[PlaylistItem, ...]
    added: tuple[RecentTrack, ...]
    removed: tuple[RemovedPlaylistItem, ...]
    unmatched_or_non_track: tuple[RemovedPlaylistItem, ...]
    recent_play_count: int
    qualifying_recent_count: int
    threshold: int

    @property
    def required_play_count(self) -> int:
        return self.threshold


def playlist_item_from_api(raw: dict[str, Any], position: int) -> PlaylistItem:
    media = _media_from_playlist_item(raw)
    uri = _optional_str(media.get("uri")) if media else None
    name = _optional_str(media.get("name")) if media else None
    item_type = _optional_str(media.get("type")) if media else None
    artists = _artists_from_media(media)
    return PlaylistItem(
        uri=uri,
        name=name or "(unknown)",
        artists=artists,
        item_type=item_type,
        is_local=bool(raw.get("is_local")),
        position=position,
    )


def recent_track_from_api(raw: dict[str, Any], position: int) -> RecentTrack:
    media = _media_from_playlist_item(raw)
    uri = _optional_str(media.get("uri")) if media else None
    name = _optional_str(media.get("name")) if media else None
    item_type = _optional_str(media.get("type")) if media else None
    artists = _artists_from_media(media)
    is_local = bool(media.get("is_local")) if media else False
    played_at = _optional_str(raw.get("played_at"))
    return RecentTrack(
        uri=uri,
        name=name or "(unknown)",
        artists=artists,
        item_type=item_type,
        is_local=is_local,
        position=position,
        played_at=played_at,
    )


def _media_from_playlist_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    item = raw.get("track") or raw.get("item")
    if isinstance(item, dict):
        return item
    return None


def _artists_from_media(media: dict[str, Any] | None) -> tuple[str, ...]:
    if not media:
        return ()
    raw_artists = media.get("artists")
    if not isinstance(raw_artists, list):
        return ()
    names: list[str] = []
    for raw_artist in raw_artists:
        if isinstance(raw_artist, dict):
            name = _optional_str(raw_artist.get("name"))
            if name:
                names.append(name)
    return tuple(names)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
