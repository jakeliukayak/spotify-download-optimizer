# Spotify Download Optimizer

A Python CLI that updates an existing Spotify playlist from Spotify's limited recent listening
history. It keeps existing playlist tracks and adds missing recent tracks when they appear at
least twice in the recent-history API response.

The tool does not download music or audio files. However, after each optimizer run, the Spotify
app can automatically update offline downloads for the modified playlist.

This is especially useful when a user needs to pre-download music for offline listening on a device with limited storage space.

## Setup

Create a Spotify developer app and add the redirect URI you plan to use. The default is:

```text
http://127.0.0.1:8888/callback
```

Set the client ID:

```sh
export SPOTIFY_CLIENT_ID="your-client-id"
```

## Usage

Authenticate once:

```sh
uv run spotify-download-optimizer auth login
```

Preview an optimization:

```sh
uv run spotify-download-optimizer optimize \
  --playlist-id 37i9dQZF1DXcBWIGoYBM5M # from shareable link: https://open.spotify.com/playlist/playlist-id?si=xxx
```

Apply the playlist update:

```sh
uv run spotify-download-optimizer optimize \
  --playlist-id 37i9dQZF1DXcBWIGoYBM5M \
  --apply
```
