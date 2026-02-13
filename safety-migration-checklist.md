# Safety Migration Checklist

- [x] Add runtime safety profile settings (`safe` default, `throughput` opt-in).
- [x] Make status publishing durable by default (retry + buffered fallback, optional strict mode).
- [x] Set bounded Redis stream defaults for queue/status paths.
- [x] Wire profile behavior into Worker/queue initialization.
- [x] Add benchmark profile support (`throughput` and durability-oriented mode).
- [x] Add/update tests for profile behavior and status publish retry/buffer semantics.
- [x] Update docs for guarantees + profile behavior.
