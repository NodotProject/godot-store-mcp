<!-- Drafts for godot-livekit. Push via store_edit_asset(publisher='jake-cattrall', slug='godot-livekit', description=SHORT, body=BODY). -->

## SHORT (description)

Real-time voice, video, screen-sharing and data channels in Godot 4.5 via the official LiveKit C++ SDK — a true native GDExtension for Linux, macOS and Windows.

## BODY (body_raw, markdown)

**Drop production-grade WebRTC into your Godot game.**

Godot-LiveKit is a [GDExtension](https://docs.godotengine.org/en/stable/tutorials/scripting/gdextension/index.html) that integrates the official [LiveKit C++ SDK](https://github.com/livekit/client-sdk-cpp) with Godot 4.5. It gives you everything you need to build real-time voice chat, video calls, screen sharing and arbitrary data channels — directly in GDScript or C#, with no custom engine builds and no painful build times.

### What you get

- **Real-time voice, video, and data** — connect to any LiveKit server (cloud or self-hosted) and join rooms in a handful of lines.
- **Full track support** — publish and subscribe to audio/video tracks, with local sources for capturing audio and video from inside Godot.
- **Native screen capture** — capture monitors or individual windows on **macOS, Windows and Linux** via the built-in `LiveKitScreenCapture` class. Perfect for streaming, co-op pair-programming games, or in-game broadcasting.
- **Data channels** — send and receive arbitrary messages with reliable or unreliable delivery — built-in alternative to ENet for game state, chat, or signalling.
- **RPC support** — call remote procedures between participants without writing your own protocol.
- **End-to-end encryption (E2EE)** — secure media with configurable encryption, key management, and per-participant frame cryptors.
- **Connection statistics** — full WebRTC stats (inbound/outbound RTP, codecs, transport, candidate pairs) for debugging and adaptive quality.
- **Cross-platform** — prebuilt binaries for Linux, macOS (Universal) and Windows in every release.
- **Fast builds** — uses prebuilt `godot-cpp` and LiveKit C++ binaries, so compile times are measured in seconds, not hours.

### Quick start

```gdscript
extends Node

var room: LiveKitRoom

func _ready():
    room = LiveKitRoom.new()
    room.connected.connect(_on_connected)
    room.participant_connected.connect(_on_participant_connected)
    room.track_subscribed.connect(_on_track_subscribed)
    room.data_received.connect(_on_data_received)
    room.connect_to_room("wss://your-server.url", "your-token", {})

func _on_connected():
    print("Connected as: ", room.get_local_participant().get_identity())

func _on_participant_connected(participant):
    print("Joined: ", participant.get_identity())

func _on_track_subscribed(track, publication, participant):
    print("Subscribed: ", track.get_name())

func _on_data_received(data, participant, kind, topic):
    print("Data: ", data.get_string_from_utf8())
```

Rooms, video streams and screen captures are **auto-polled every frame** by default — no `_process()` boilerplate. Flip `auto_poll = false` if you'd rather drive it yourself.

### Screen sharing in 4 lines

```gdscript
var capture := LiveKitScreenCapture.create()
capture.frame_received.connect(_on_frame)
capture.start()
```

### Use cases

- **Voice chat for multiplayer games** — works on Linux, macOS, Windows.
- **Pair-programming / collab tools built in Godot** — screen sharing comes built-in.
- **Co-op streaming or watch-parties** — push your gameplay as a LiveKit track.
- **Telepresence, virtual events, in-game livestreams** — anywhere WebRTC fits.

### Install

Releases ship prebuilt `.so` / `.dylib` / `.dll` binaries — drop `addons/godot-livekit` into your project, enable the plugin, and connect.

### Source

- GitHub: [NodotProject/godot-livekit](https://github.com/NodotProject/godot-livekit)

MIT licensed. The LiveKit C++ SDK is Apache 2.0. Built with ❤️ for Godot developers by the [NodotProject](https://github.com/NodotProject).
