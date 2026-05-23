<!-- Drafts for godot-torrent. Push via store_edit_asset(publisher='jake-cattrall', slug='godot-torrent', description=SHORT, body=BODY). -->

## SHORT (description)

Full BitTorrent protocol support for Godot 4 via libtorrent — download, seed, magnet links, DHT, peer/piece priorities — straight from GDScript with native C++ performance.

## BODY (body_raw, markdown)

**Peer-to-peer file transfer, brought to Godot.**

Godot-Torrent is a [GDExtension](https://docs.godotengine.org/en/stable/tutorials/scripting/gdextension/index.html) that wraps the industry-standard [libtorrent](https://libtorrent.org/) C++ library. It gives Godot the same BitTorrent capabilities you'd find in a desktop torrent client — downloading, seeding, magnet links, DHT, fine-grained priorities and a live alerts system — all driven from GDScript with native performance.

### Features

- **Complete BitTorrent protocol** — full support for downloading and seeding.
- **Magnet links & DHT** — start a torrent with just a magnet URI; trackerless swarms work out of the box.
- **Session management** — fine-grained control over torrent sessions, listen ports, and config.
- **Real-time monitoring** — track progress, peers, upload/download rates, and statistics every tick.
- **Priority management** — choose which files and pieces matter most.
- **Comprehensive alerts** — libtorrent's event system surfaced as Godot-friendly dictionaries.
- **Production-ready error handling** — structured `TorrentError` codes plus a 5-level / 10-category logger.
- **Cross-platform** — native builds for **Linux, Windows and macOS** in every release.

### Quick start

```gdscript
var session := TorrentSession.new()
session.start_session()
session.start_dht()

var handle := session.add_magnet_uri(
    "magnet:?xt=urn:btih:...",
    "/path/to/downloads"
)

func update_progress():
    session.post_torrent_updates()
    for alert in session.get_alerts():
        if alert.has("torrent_status"):
            for s in alert["torrent_status"]:
                var pct := s.get("progress", 0.0) * 100.0
                var rate := s.get("download_rate", 0) / 1024.0 / 1024.0
                print("%.1f%% — %.2f MB/s" % [pct, rate])
```

### Core classes

- **`TorrentSession`** — session lifecycle and configuration (30+ methods).
- **`TorrentHandle`** — per-torrent control (30+ methods).
- **`TorrentInfo`** — torrent metadata and file information (15+ methods).
- **`TorrentStatus`** — live status tracking (25+ properties).
- **`PeerInfo`** — peer connection details (20+ methods).
- **`AlertManager`**, **`TorrentError`**, **`TorrentLogger`** — events, errors and logging utilities.

### Use cases

- **P2P content distribution** — ship game assets, updates and DLC without paying for hosting bandwidth.
- **Mod sharing** — let players exchange community content with a torrent under the hood.
- **Large patches & live-service updates** — keep download servers cheap by leveraging your active player base.
- **In-app content delivery** — backups, media, large bundles.

### Install

Releases ship prebuilt binaries for Linux, Windows and macOS — drop the `addons/godot-torrent` folder into your project and enable the plugin. Requires Godot **4.5+**.

### Source & community

- GitHub: [NodotProject/godot-torrent](https://github.com/NodotProject/godot-torrent)
- Discord: [discord.gg/Rx9CZX4sjG](https://discord.gg/Rx9CZX4sjG)

MIT licensed. Built on the excellent [libtorrent](https://libtorrent.org/). Brought to you with ❤️ by the [NodotProject](https://github.com/NodotProject).
