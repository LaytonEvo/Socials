# The bunker piece, half-rendered — and what stopped it, 2026-10-16

**Status:** incomplete. Two of four shots rendered, **$2.80 billed**, nothing assembled,
nothing disclosed, nothing signed. The render is blocked on credentials that no longer
exist in this container, not on anything in the code.

What follows is worth more than the piece would have been. Pre-flighting the run found
that `cost_ledger` had never held a row, and chasing two crashes found a leak that had
quietly filled the disk with 15GB of temporary files. Both are fixed. The piece is not.

## What was rendered

| take | face coverage | identity mean | identity min | head roll sd |
|---|---|---|---|---|
| setup_take_0 | 100% | 0.96090 | 0.94920 | 10.6° |
| setup_take_1 | 100% | 0.95230 | 0.92690 | 8.0° |
| setup_take_2 | 100% | 0.95720 | 0.94520 | 10.3° |
| address_take_0 | **30%** | 0.95210 | 0.94410 | 6.0° |
| address_take_1 | **20%** | 0.95820 | 0.95430 | 7.2° |
| address_take_2 | **10%** | 0.95470 | 0.95470 | 0.1° |

Threshold is 0.951 on the minimum frame, coverage floor 60%. Recomputed locally from the
surviving files on 2026-10-16, because the run's own logs were in a scratchpad that was
swept; these are measurements, not recollections.

**Not one take clears the bar.** Every one of the six falls below 0.951 on its weakest
frame. The gate's own words for the setup shot were "NONE passed outright; best of a bad
set", and it picked `setup_take_0` as the least bad.

Against the approved talking shot (`single-shot-2026-09-30`): 0.96250 mean, 0.95249 min,
0 frames below threshold, 4.11° roll, 100% coverage. The bunker setup takes are close on
the mean and fail on the minimum, and they are twice as unsteady.

### The address shot cannot be measured at all

Coverage of 30%, 20% and 10% against a 60% floor. The reason is in the brief: at address
she is looking down at the ball. A face that is pointed at the sand is not a face the
detector finds, so four frames in five have nothing to score.

This is a structural finding, not a bad draw. Any shot whose posture points the face at
the ground is unscoreable by this pipeline, and no number of takes fixes it. It belongs
next to the action battery's result that `read_green` produced no usable keyframe at all,
for the same reason. Either the address shot is framed so her face comes up, or it is
cut from the piece, or the identity gate is given a rule for shots where the face is
legitimately hidden — which is the `face_expected` flag the shot list already carries and
the gate does not yet use for coverage.

### The club is grounded in the sand

The address keyframe shows the clubhead resting in the bunker. That is a two-stroke
penalty and the most recognisable error in a bunker clip. The prompt said, in as many
words, "holding the clubhead just above the sand without touching it". She is also aimed
away from the green rather than at it.

Nothing in the pipeline measures either, so neither was caught. This is the same failure
as the swing-length work: the prompt is not the render, and only the render counts.
`acceptance.py` now names both in its REVIEW checklist rather than saying "check the
golf", because a human reviewer needs a list they can act on.

## Why the run stopped

Three separate failures, in order, none of them the model's fault:

1. **A crash mid-scoring**, when the disk filled. Three address takes had been generated
   and billed; none were in the ledger, because takes were recorded after their shot was
   scored rather than when the provider returned them. $1.20 billed, $0.00 recorded.
2. **The disk itself**, which was not full of renders. `sample_frames` called `mkdtemp`,
   returned the paths and trusted a caller to delete the directory. None did. 424 orphaned
   directories held **15GB**. I misdiagnosed this twice — first blaming the 1080p takes,
   then duplicated reference stills, deleting both before finding the real cause. One of
   those deletions took out the project's virtualenv, which was a symlink into the
   scratchpad.
3. **The container was recycled.** Postgres came back with no `persona_studio` database:
   schema, ledger and every `content_piece` gone. The scratchpad went with it, taking the
   S3 bucket name, its credentials and the C2PA development certificate. The rendered
   takes survived only because they are written into the repository tree.

`make_bunker` uploads every take to S3 before scoring it, and `app/storage` offers only
`S3Storage` and an in-memory backend for tests. Substituting the in-memory one would
discard the assets while reporting success, which is the exact class of false pass this
whole session was spent removing. So the run stops here until a human supplies the
bucket, or decides this spike may keep its assets in `spike/runs/` as every earlier spike
did.

## What was fixed

- **The ledger was empty.** Zero rows, ever, across three weeks of live spend, while
  CLAUDE.md requires one per paid call and the monthly ceiling is enforced against the
  table. Every run had been comparing its spend to zero. Now wired, with ADR 0020.
- **Takes record when billed, not when scored**, so a crash during scoring cannot lose a
  charge that has already been incurred.
- **`spend_for_piece` never counted keyframes**, though "keyframe" was always in the
  vocabulary constraint. On this piece that is $0.40 of $2.80.
- **`--skip-generate` would have double-billed** a reused take; it now completes the
  existing row instead, and a resumed run continues the same piece.
- **The 15GB leak**, now a context manager, with a regression test on the exception path
  that both live crashes took.
- **The test suite was reading the production database**, which is why five correct rows
  broke five tests. It now prefers `TEST_DATABASE_URL` and refuses a database with data
  in it. This also revealed `make check` had been silently skipping 76 persistence tests
  because `DATABASE_URL` was unset.

## Open, and needing a human

- **The ledger is not durable.** It lives in a container-local Postgres with no backup and
  was wiped twice in one day. ADR 0020 states the three options rather than picking one.
- **The ledger starts from a false zero.** Everything spent before 2026-10-15 exists only
  on fal's invoices. Backfilling from them is a decision, not a cleanup.
- **The address shot needs a call**: reframe, cut, or teach the gate about
  `face_expected`.
- **The grounded club** is unmeasured and will stay unmeasured. Clubheads are not pose
  landmarks, and a flaky detector that refuses good footage is a worse failure than a
  checklist a human reads.
