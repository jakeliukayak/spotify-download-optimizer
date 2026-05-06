from __future__ import annotations

from spotify_download_optimizer.models import PlaylistItem, RecentTrack
from spotify_download_optimizer.optimizer import desired_playlist_uris, optimize_playlist


def test_recent_tracks_are_kept_or_added_when_count_is_at_least_two():
    items = (
        playlist_item(0, "spotify:track:keep-a", "Keep A"),
        playlist_item(1, "spotify:track:single", "Single"),
        playlist_item(2, "spotify:episode:ep", "Episode", item_type="episode"),
        playlist_item(3, None, "Local", is_local=True),
        playlist_item(4, "spotify:track:keep-a", "Keep A"),
        playlist_item(5, "spotify:track:missing", "Missing"),
    )
    recent_tracks = (
        recent_track(0, "spotify:track:add-me", "Add Me"),
        recent_track(1, "spotify:track:keep-a", "Keep A"),
        recent_track(2, "spotify:track:add-me", "Add Me"),
        recent_track(3, "spotify:track:keep-a", "Keep A"),
        recent_track(4, "spotify:track:single", "Single"),
        recent_track(5, "spotify:episode:ep", "Episode", item_type="episode"),
    )

    result = optimize_playlist(items, recent_tracks, threshold=2)

    assert desired_playlist_uris(result) == (
        "spotify:track:keep-a",
        "spotify:track:keep-a",
        "spotify:track:add-me",
    )
    assert [track.uri for track in result.added] == ["spotify:track:add-me"]
    assert [removed.reason for removed in result.removed] == [
        "below-threshold",
        "non-track",
        "missing-uri",
        "not-in-history",
    ]
    assert len(result.unmatched_or_non_track) == 3
    assert result.required_play_count == 2
    assert result.recent_play_count == 6
    assert result.qualifying_recent_count == 2


def test_at_threshold_qualifies():
    item = playlist_item(0, "spotify:track:x", "Track")
    recent_tracks = (
        recent_track(0, "spotify:track:x", "Track"),
        recent_track(1, "spotify:track:x", "Track"),
    )

    result = optimize_playlist((item,), recent_tracks, threshold=2)

    assert desired_playlist_uris(result) == ("spotify:track:x",)


def playlist_item(
    position: int,
    uri: str | None,
    name: str,
    *,
    item_type: str = "track",
    is_local: bool = False,
) -> PlaylistItem:
    return PlaylistItem(
        uri=uri,
        name=name,
        artists=("Artist",),
        item_type=item_type,
        is_local=is_local,
        position=position,
    )


def recent_track(
    position: int,
    uri: str | None,
    name: str,
    *,
    item_type: str = "track",
    is_local: bool = False,
) -> RecentTrack:
    return RecentTrack(
        uri=uri,
        name=name,
        artists=("Artist",),
        item_type=item_type,
        is_local=is_local,
        position=position,
        played_at=None,
    )
