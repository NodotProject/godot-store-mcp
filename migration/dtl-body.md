<!-- Drafts for DTL (Dungeon Template Library). Push via store_edit_asset(publisher='jake-cattrall', slug='dtl', description=SHORT, body=BODY). -->

## SHORT (description)

Procedurally generate 2D maps in Godot — islands, mazes, roguelike dungeons and more — through a fast C++ GDExtension wrapping the well-known Dungeon Template Library.

## BODY (body_raw, markdown)

**Procedural worlds in one line of GDScript.**

DTL for Godot is a [GDExtension](https://docs.godotengine.org/en/stable/tutorials/scripting/gdextension/index.html) that wraps the battle-tested C++ [Dungeon Template Library](https://github.com/AsPJT/DungeonTemplateLibrary). It exposes a single, friendly `DTL` class with **15+ algorithms** for generating maps you can drop straight into a `TileMap`, height-map, or any 2D grid your game needs.

![DTL generators](https://raw.githubusercontent.com/AsPJT/DungeonPicture/master/Picture/Logo/logo_color800_2.gif)

### What you get

- **Roguelike dungeons** — `RogueLike` and `SimpleRogueLike` produce classic rooms-and-corridors layouts with configurable room sizes, corridor lengths, and density.
- **Mazes** — `MazeBar`, `MazeDig` and `ClusteringMaze` for blocky grids, organic tunnels, and cave-like labyrinths.
- **Islands** — `PerlinIsland`, `PerlinLoopIsland`, `PerlinSolitaryIsland`, `FractalIsland`, `FractalLoopIsland`, `SimpleVoronoiIsland`, `DiamondSquareAverageIsland`, `DiamondSquareAverageCornerIsland`, and `CellularAutomatonIsland`/`CellularAutomatonMixIsland` for everything from rough coastlines to smooth height-maps.
- **Native C++ performance** — generation runs at full speed, even for large maps, without ever leaving the engine.
- **Single, simple API** — every method returns a 1D `[width × height]` array you can iterate however you like.

### Quick start

```gdscript
extends Node

func _ready() -> void:
    var dtl := DTL.new()
    var dungeon := dtl.SimpleRogueLike(
        64, 64,
        3, 4,      # divisions
        5, 6,      # room x range
        7, 8       # room y range
    )

    for y in range(64):
        for x in range(64):
            $TileMap.set_cell(0, Vector2i(x, y), dungeon[y * 64 + x])
```

Pick a different generator — `dtl.PerlinSolitaryIsland(...)`, `dtl.MazeDig(...)`, `dtl.RogueLike(...)` — and the rest of your code stays exactly the same.

### Install

Drop the addon into your project, enable it under **Project → Project Settings → Plugins**, and you're done. Works with Godot 4.3 and up.

### Source & contributing

Pull requests, new generators, and examples are very welcome — see the [GitHub repository](https://github.com/krazyjakee/DungeonTemplateLibrary-Godot).

MIT licensed.
