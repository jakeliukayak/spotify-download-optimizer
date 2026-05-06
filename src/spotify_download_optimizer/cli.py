from __future__ import annotations

from typing import Annotated

import httpx
import typer

from spotify_download_optimizer.auth import (
    AuthError,
    OAuthTokenProvider,
    TokenStore,
    client_id_from_env,
    redirect_uri_from_env,
    run_pkce_login,
)
from spotify_download_optimizer.client import SpotifyClient
from spotify_download_optimizer.models import OptimizationResult, RemovedPlaylistItem
from spotify_download_optimizer.optimizer import desired_playlist_uris, optimize_playlist

app = typer.Typer(help="Optimize Spotify playlists from limited recent listening history.")
auth_app = typer.Typer(help="Manage Spotify authentication.")
app.add_typer(auth_app, name="auth")


@auth_app.command("login")
def login() -> None:
    """Authenticate with Spotify using OAuth PKCE."""
    try:
        token = run_pkce_login(
            client_id=client_id_from_env(),
            redirect_uri=redirect_uri_from_env(),
            token_store=TokenStore(),
        )
    except AuthError as exc:
        _fail(str(exc))
    typer.echo(f"Spotify authentication saved. Token scopes: {token.scope}")


@app.command("optimize")
def optimize(
    playlist_id: Annotated[
        str,
        typer.Option("--playlist-id", help="Spotify playlist ID to update in place."),
    ],
    threshold: Annotated[
        int,
        typer.Option("--threshold", min=1, help="Keep/add tracks with this many recent plays."),
    ] = 2,
    recent_limit: Annotated[
        int,
        typer.Option("--recent-limit", min=1, max=50, help="Number of recent plays to inspect."),
    ] = 50,
    apply_changes: Annotated[
        bool,
        typer.Option("--apply", help="Actually replace playlist contents. Defaults to dry-run."),
    ] = False,
) -> None:
    """Keep/add tracks played at least the threshold in limited recent history."""
    try:
        provider = OAuthTokenProvider(client_id=client_id_from_env(), token_store=TokenStore())
        with SpotifyClient(provider) as client:
            recent_tracks = client.get_recently_played_tracks(limit=recent_limit)
            playlist_items = client.get_playlist_items(playlist_id)
            result = optimize_playlist(playlist_items, recent_tracks, threshold=threshold)
            _print_result(
                result=result,
                total_items=len(playlist_items),
                apply_changes=apply_changes,
            )
            if apply_changes:
                client.replace_playlist_items(playlist_id, desired_playlist_uris(result))
                typer.echo("Applied playlist update.")
            else:
                typer.echo("Dry run only. Re-run with --apply to update the playlist.")
    except (AuthError, httpx.HTTPError, ValueError) as exc:
        _fail(str(exc))


def main() -> None:
    app()


def _print_result(result: OptimizationResult, total_items: int, apply_changes: bool) -> None:
    mode = "apply" if apply_changes else "dry-run"
    typer.echo(f"Mode: {mode}")
    typer.echo(f"Playlist items: {total_items}")
    typer.echo(f"Recent plays inspected: {result.recent_play_count}")
    typer.echo(f"Qualifying recent tracks: {result.qualifying_recent_count}")
    typer.echo(f"Kept: {len(result.kept)} (required plays: >= {result.required_play_count})")
    typer.echo(f"Added: {len(result.added)}")
    typer.echo(f"Removed: {len(result.removed)}")
    typer.echo(f"Unmatched/non-track: {len(result.unmatched_or_non_track)}")

    if result.added:
        typer.echo("")
        typer.echo("Adds:")
        typer.echo("plays | track")
        typer.echo("------+------------------------------")
        for added in result.added[:20]:
            typer.echo(f"{result.threshold:>5}+ | {_truncate(added.display_name)}")
        remaining_added = len(result.added) - 20
        if remaining_added > 0:
            typer.echo(f"... and {remaining_added} more")

    if result.removed:
        typer.echo("")
        typer.echo("Removals:")
        typer.echo("pos | plays | reason          | track")
        typer.echo("----+-------+-----------------+------------------------------")
        for removed in result.removed[:20]:
            typer.echo(_format_removed_item(removed))
        remaining = len(result.removed) - 20
        if remaining > 0:
            typer.echo(f"... and {remaining} more")


def _format_removed_item(removed: RemovedPlaylistItem) -> str:
    position = removed.item.position + 1
    return (
        f"{position:>3} | {removed.play_count:>5} | "
        f"{removed.reason:<15} | {_truncate(removed.item.display_name)}"
    )


def _truncate(value: str, max_length: int = 56) -> str:
    if len(value) > max_length:
        return f"{value[: max_length - 3]}..."
    return value


def _fail(message: str) -> None:
    typer.secho(message, err=True, fg=typer.colors.RED)
    raise typer.Exit(1)
