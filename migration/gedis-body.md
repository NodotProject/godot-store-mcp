<!-- Drafts for Gedis. Push via store_edit_asset(publisher='jake-cattrall', slug='gedis', description=SHORT, body=BODY). -->

## SHORT (description)

An in-memory, Redis-like datastore for Godot — strings, hashes, lists, sets, sorted sets, TTLs, and pub/sub, all in pure GDScript.

## BODY (body_raw, markdown)

**The Redis you know, right inside your Godot project.**

Gedis is a high-performance, in-memory key-value datastore for Godot, inspired by Redis and written in pure GDScript. No native dependencies, no servers to spin up — just `var gedis := Gedis.new()` and you have a battle-proven toolbox for managing game state, caches, queues, leaderboards and real-time events.

> *Redis-like? What's Redis?* → [Redis in 100 Seconds](https://www.youtube.com/watch?v=G1rOthIU-uo)

### Features

- **Values** — `set_value`, `get_value`, `incr`, `decr`, `mget`, `mset`. Perfect for counters, flags, and quick lookups.
- **Hashes** — `hset`, `hget`, `hgetall`, `hmget`, `hmset`, `hexists`. Store object-like structures without the ceremony.
- **Lists** — `lpush`, `rpush`, `lpop`, `blpop`, `ltrim`. Ordered collections you can use as queues or stacks.
- **Sets** — `sadd`, `srem`, `smembers`, `sunion`, `sinter`. Fast membership and set algebra.
- **Sorted sets** — `zadd`, `zrem`, `zrange`, `zscore`, `zrank`, `zcard`. Ideal for **leaderboards** and any "top N" feature.
- **Key expiry (TTL)** — `expire`, `ttl`. Sessions, cooldowns, temporary buffs — set it and forget it.
- **Pub/Sub** — `publish`, `subscribe`, `psubscribe`. A clean event bus for decoupling systems across your game.
- **Existence checks** — `lexists`, `sexists`, `zexists`, `hexists`. No more guessing what's at a key.
- **Built-in debugger** — peek at every key from the editor.

### Quick start

```gdscript
var gedis := Gedis.new()

gedis.set_value("score", 0)
gedis.incr("score", 10)

gedis.zadd("leaderboard", {"alice": 100, "bob": 80})
var top := gedis.zrange("leaderboard", 0, 10, true) # top players

gedis.expire("active_buff", 30) # auto-clear in 30 seconds
```

### Built with Gedis

- **[GedisQueue](https://github.com/NodotProject/GedisQueue)** — a powerful background-job queue for Godot, built on Gedis pub/sub.

### Why GDScript-only?

Because installation should be a single drop-in addon, not a compile step. Every command runs in-process — no networking, no serialisation overhead, no surprises across platforms.

### Documentation

Full API reference at [**nodotproject.github.io/Gedis**](https://nodotproject.github.io/Gedis/).

### Source & community

- GitHub: [NodotProject/Gedis](https://github.com/NodotProject/Gedis)
- Discord: [discord.gg/Rx9CZX4sjG](https://discord.gg/Rx9CZX4sjG)

MIT licensed. Built with ❤️ for Godot developers by the [NodotProject](https://github.com/NodotProject).
