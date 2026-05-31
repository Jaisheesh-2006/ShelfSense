# tracker service

**Responsibility:** Assign stable IDs across frames (multi-object tracking) and map each
tracked position to a store zone using the floor plan.

- **Consumes:** `detection.created` events.
- **Produces:** `track.updated` events (see [../../docs/wiki/EVENT_SCHEMA.md](../../docs/wiki/EVENT_SCHEMA.md)).
- **Tech:** Python, a modern tracker (ByteTrack/OC-SORT/DeepSORT — see DECISIONS PD-2).

> Scaffold only. Implementation pending plan approval — see [../../docs/wiki/TASKS.md](../../docs/wiki/TASKS.md).
