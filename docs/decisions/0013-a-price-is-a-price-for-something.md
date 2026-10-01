# ADR 0013 — A price is a price *for* a particular request

- **Status**: accepted
- **Date**: 2026-10-01
- **Relates to**: CLAUDE.md non-negotiable rule 1 (never hardcode prices; `verified_on`)

## Context

Reading turbo's official model page while sizing the owner's brief:

| | launch discount | from 2026-10-01 |
|---|---|---|
| 480p | $0.0125/s | $0.025/s |
| **768p** | **$0.02/s** | **$0.04/s** |
| 1080p | $0.04/s | $0.08/s |

> "The discount ends September 30."

`video.golf` carried `price_usd_per_second: 0.0125` with `verified_on: 2026-09-25` while
sending `resolution: 768P`. That figure is the **480p launch-discount** rate. So the cost
guard understated video by 60% from the day it was written, and by **3.2×** from today,
when the discount lapsed.

The slot was not unverified. It had a `verified_on` date, a price, and a long comment
explaining the pricing. The comment was simply about a different resolution than the one
the request sends, and nothing could notice.

## What this cost

| | as costed | actual |
|---|---|---|
| one single-shot run | $1.0352 | **$1.5852** |
| the 5-run pass-rate battery | $5.18 | **$7.93** |

Every cost figure reported before today is understated by this factor on its video line,
including the invalidated cost model in `docs/reports/pass-rate-2026-10-01.md`.

## Decision

`ProviderSlot.price_basis` records the request fields a price is quoted *for*, and a
`model_validator` refuses to load a config whose `price_basis` disagrees with its
`request.base`. A price that describes a different request than the one we send is now a
load-time error rather than a comment nobody checks.

```yaml
price_usd_per_second: 0.04
verified_on: 2026-10-01
price_basis:
  resolution: 768P      # must equal request.base.resolution or the config will not load
```

Validated rather than commented, because the comment that should have caught this was
already there and said the price was verified.

## Two capability corrections found in the same read

The slot's recorded capabilities were also wrong, both from the live OpenAPI schema:

- **`durations_s: [5]`** — actually `minimum 5, maximum 15`, integer. The note said
  "integer, minimum 5" and was read as "only 5", which is why the owner's brief was first
  costed as three 5-second clips when his 6/3/2/4 timings were mostly achievable. Only the
  4-second shot is impossible.
- **The output canvas follows `image_url`.** The keyframe decides the aspect ratio, so 9:16
  output needs a 9:16 keyframe and no other change. Text-to-video defaults to 16:9.
- **`resolution` accepts `1080P`** — "1080P latent refinement from a native 768P source".
  1080 needs no separate upscaler, only a flag and the matching price.

## Consequences

- Capabilities read off a schema are now written down with the date they were read, in the
  same place as the price. Both were wrong in the same slot for the same reason: they were
  summarised from memory of the documentation rather than from the documentation.
- The brief at 768P costs about **$3.35 an attempt**, or roughly **$20 a finished piece** at
  the measured 1-in-6 hit rate. At 1080P it is **$5.91** and **$35**.
- `price_basis` is empty on slots that bill one way regardless of the request, which is
  most of them. It is not ceremony to be filled in everywhere.
