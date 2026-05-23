<!-- Drafts for GedisQueue. Push via store_edit_asset(publisher='jake-cattrall', slug='gedis-queue', description=SHORT, body=BODY). -->

## SHORT (description)

A powerful background job queue for Godot, built on Gedis — track jobs through waiting / active / completed / failed states with custom processors, batching and lifecycle events.

## BODY (body_raw, markdown)

**Background work, queued and processed the way grown-up apps do it — natively in Godot.**

GedisQueue brings a proper job-queue system to Godot, modelled on industry-standard queues like Bull and Sidekiq, and powered by [**Gedis**](https://github.com/NodotProject/Gedis). Schedule asynchronous work — rewards, notifications, world-generation chunks, save flushes, analytics — and process it with a worker function you control.

### What it's good for

- **Player rewards & inventory drops** — defer them so the gameplay loop never stutters.
- **Background world or chunk generation** — feed jobs to a worker and let progress events drive your UI.
- **Networking & notifications** — queue retries with priority and retention limits.
- **Save throttling, telemetry, mod hooks** — any task you don't want blocking the main thread.

### Features

- **Job lifecycle management** — every job moves through `waiting`, `active`, `completed`, or `failed`. Query any state at any time with `get_jobs`.
- **Flexible job processors** — pass any GDScript callable. The processor receives the job and calls `job.complete(...)` or `job.fail(...)`.
- **Batch processing** — bump `worker.batch_size` to process N jobs concurrently when you've got the headroom.
- **Configurable retention** — keep the last 100 successes, all failures, or none — your call (`max_completed_jobs`, `max_failed_jobs`).
- **Pub/Sub lifecycle events** — `added`, `active`, `progress`, `completed`, `failed` broadcast via Gedis. Subscribe from anywhere in your project for live dashboards or game-side reactions.
- **Tooling** — works hand-in-hand with the Gedis debugger so you can watch queue depth and jobs in flight from the editor.
- **Signals on completion / failure** — wire jobs directly to gameplay code.

### Quick start

```gdscript
var gedis := Gedis.new()
var queue := GedisQueue.new()
add_child(gedis)
queue.setup(gedis)
add_child(queue)

# Add a job
queue.add("player_rewards", {
    "player_id": "player123",
    "items": ["gold_coins", "health_potion"],
    "quantity": [100, 2],
})

# Process jobs
var processor := func(job):
    var data = job.data
    var player := get_player(data.player_id)
    for i in data.items.size():
        player.inventory.add_item(data.items[i], data.quantity[i])
    job.complete("Reward granted")

var worker := queue.process("player_rewards", processor)
worker.batch_size = 10
```

### Live job events

```gdscript
gedis.psubscribe("gedis_queue:player_rewards:events:*", self)
pubsub_message.connect(func(pattern, channel, message):
    prints("event:", channel, message))
```

### Requires Gedis

GedisQueue sits on top of [Gedis](https://github.com/NodotProject/Gedis) — install it first, then drop GedisQueue in. Both are pure GDScript; no compile step on any platform.

### Documentation

Full guide at [**nodotproject.github.io/GedisQueue**](https://nodotproject.github.io/GedisQueue/).

### Source & community

- GitHub: [NodotProject/GedisQueue](https://github.com/NodotProject/GedisQueue)
- Discord: [discord.gg/Rx9CZX4sjG](https://discord.gg/Rx9CZX4sjG)

MIT licensed. Built with ❤️ for Godot developers by the [NodotProject](https://github.com/NodotProject).
