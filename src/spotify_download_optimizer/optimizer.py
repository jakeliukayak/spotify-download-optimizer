from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from spotify_download_optimizer.models import (
    OptimizationResult,
    PlaylistItem,
    RecentTrack,
    RemovedPlaylistItem,
)


def optimize_playlist(
    playlist_items: Sequence[PlaylistItem],
    recent_tracks: Sequence[RecentTrack],
    *,
    threshold: int = 2,
) -> OptimizationResult:
    play_counts = count_recent_tracks(recent_tracks)
    qualifying_tracks = unique_qualifying_recent_tracks(recent_tracks, play_counts, threshold)
    qualifying_uris = {track.uri for track in qualifying_tracks if track.uri is not None}

    kept: list[PlaylistItem] = []
    removed: list[RemovedPlaylistItem] = []
    unmatched_or_non_track: list[RemovedPlaylistItem] = []
    kept_uris_seen: set[str] = set()

    for item in playlist_items:
        play_count = play_counts.get(item.uri or "", 0)
        if item.is_spotify_track and item.uri in qualifying_uris:
            kept.append(item)
            kept_uris_seen.add(item.uri or "")
            continue

        reason = removal_reason(item=item, play_count=play_count, threshold=threshold)
        removed_item = RemovedPlaylistItem(item=item, play_count=play_count, reason=reason)
        removed.append(removed_item)
        if reason in {"missing-uri", "non-track", "not-in-history"}:
            unmatched_or_non_track.append(removed_item)

    added = tuple(
        track
        for track in qualifying_tracks
        if track.uri is not None and track.uri not in kept_uris_seen
    )

    return OptimizationResult(
        kept=tuple(kept),
        added=added,
        removed=tuple(removed),
        unmatched_or_non_track=tuple(unmatched_or_non_track),
        recent_play_count=len(recent_tracks),
        qualifying_recent_count=len(qualifying_tracks),
        threshold=threshold,
    )


def desired_playlist_uris(result: OptimizationResult) -> tuple[str, ...]:
    uris: list[str] = []
    for item in result.kept:
        if item.uri is not None:
            uris.append(item.uri)
    for added_item in result.added:
        if added_item.uri is not None:
            uris.append(added_item.uri)
    return tuple(uris)


def removal_reason(item: PlaylistItem, play_count: int, threshold: int) -> str:
    if item.uri is None:
        return "missing-uri"
    if not item.is_spotify_track:
        return "non-track"
    if play_count == 0:
        return "not-in-history"
    if play_count < threshold:
        return "below-threshold"
    return "unknown"


def count_recent_tracks(recent_tracks: Sequence[RecentTrack]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for track in recent_tracks:
        if track.is_spotify_track and track.uri is not None:
            counts[track.uri] += 1
    return counts


def unique_qualifying_recent_tracks(
    recent_tracks: Sequence[RecentTrack],
    play_counts: Counter[str],
    threshold: int,
) -> tuple[RecentTrack, ...]:
    seen: set[str] = set()
    qualifying: list[RecentTrack] = []
    for track in recent_tracks:
        if (
            track.is_spotify_track
            and track.uri is not None
            and track.uri not in seen
            and play_counts[track.uri] >= threshold
        ):
            qualifying.append(track)
            seen.add(track.uri)
    return tuple(qualifying)
