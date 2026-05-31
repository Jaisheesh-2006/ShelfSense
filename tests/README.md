# tests

Pytest suites for ShelfSense.

- **Unit tests** per service (detector, tracker, analytics, api).
- **Contract tests** validating events against [../docs/wiki/EVENT_SCHEMA.md](../docs/wiki/EVENT_SCHEMA.md) (shared Pydantic models).
- **Integration test** exercising a thin end-to-end pipeline slice.

Run: `pytest` from the project root (once dependencies are defined).

> Scaffold only. See [../docs/wiki/TASKS.md](../docs/wiki/TASKS.md).
