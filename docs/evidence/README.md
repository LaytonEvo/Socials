# Evidence promoted out of `spike/runs/`

`spike/runs/` is gitignored on the grounds that media and logs are evidence,
not source. That is right for clips, frames and run logs: they are large, and
`fetch`/re-run reproduces them.

**It is wrong for the rating sheets.** A rating is the only column in a run
directory that cannot be regenerated — it is a human having watched four
seconds of video and formed a judgement. Everything else in there falls out of
re-scoring; that does not.

The spike runs in an ephemeral container. Until 2026-09-28 the owner's
judgements existed only there, one reclaim away from being lost, while the
clips that produced them were reproducible for a few dollars.

So rating sheets are promoted here, the same way `gate-a.md` is promoted to
`docs/reports/`. Copy the sheet after any run that adds owner ratings:

    cp spike/runs/<run>/battery_ratings.csv docs/evidence/

| File | What it holds |
|---|---|
| `battery_ratings.csv` | S0.7 golf battery: every clip generated, its automated verdict, and the owner's rating where one was given |
