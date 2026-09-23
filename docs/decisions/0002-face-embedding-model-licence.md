# ADR 0002 — Face-embedding model and licence route

- **Status:** **Superseded 2026-09-23 by [ADR 0004](0004-identity-scorer-dlib-resnet.md).** DINOv2 was accepted on 2026-09-22 and measured MARGINAL against a realistic control the next day; dlib measured EXCELLENT on the same data. The licence research below still stands and is why ADR 0004 carries an open condition; the *choice* it reached does not.
- **Date:** 2026-09-22 (research recorded); superseded sections dated where changed
- **Deciders:** Layton (owner), supervising engineer; touches counsel under D7
- **Relates to:** `BUILD_PLAN.md` Section 3 (stack), tasks 1.2 and 1.3; `docs/BUILD_ORDER.md` amendment A3

## Context

The identity scorer is the measuring instrument for the entire project. It gates every take (task 3.4), produces the evidence for the Phase 1 gate, and defines the threshold that auto-reject depends on. It cannot be chosen provisionally and swapped later without invalidating everything measured with it — a calibrated threshold is valid for exactly one model at one version (amendment A3, enforced by `CalibrationMismatch`).

`BUILD_PLAN.md` flags the problem in a single table cell:

> Face scoring | Face-embedding model (ArcFace-class) | **Check licence for commercial use** — some popular pretrained weights are non-commercial only

That undersells it in two ways.

### Finding 1 — two licences stack, and the second one is the trap

Every candidate has a **weights licence** and a **training-data licence**. The plan's note describes the first. The second is what actually bites, because the permissive file licence on a model does not cure the restrictions on the corpus it was trained on.

Checked 2026-09-22 against current sources (linked below). **Re-verify before relying on any row: these terms change, and a summary is not a licence.**

| Candidate | Weights licence | Training data | Commercially usable? |
|---|---|---|---|
| InsightFace `buffalo_l` (ArcFace) | Code MIT; **pretrained models non-commercial research only** | MS1M / Glint360K derivatives, research-only | **No** — but commercial licensing is offered |
| SFace (OpenCV Zoo) | Apache 2.0 on the model directory | CASIA-WebFace, **non-commercial research and educational use** | Contested |
| dlib `dlib_face_recognition_resnet_model_v1` | **Public domain**, explicit author statement | ~3M faces incl. FaceScrub and VGG; FaceScrub non-commercial | Contested, cleanest of the face-specific options |
| dlib `face_recognition_densenet_model_v1` | **MIT**, from the BAREL project — *not* covered by the dlib-models statement | Undocumented for the recognition stage | **Yes** on the grant; provenance unknown |
| DigiFace-1M (to train our own) | Dataset **non-commercial research** | Synthetic | **No** |
| DINOv2 | **Apache 2.0** (relicensed from CC-BY-NC) | LVD-142M | **Yes**, but not a face model |

Two specific traps worth recording because they are easy to walk into:

- **DINOv3 is not DINOv2.** DINOv3 ships under a bespoke "DINOv3 License", not Apache 2.0. Reaching for the newer model by reflex changes the licence position.
- **The dlib-models public-domain statement does not cover every file in that repository.** Its exact wording is *"This repository contains trained models created by me (Davis King)... anyone can do whatever they want with these model files as I've released them into the public domain."* That is scoped to its author's own models. `face_recognition_densenet_model_v1` is a third-party contribution from the [BAREL project](https://github.com/Cydral/BAREL), which licenses it MIT separately. Reading the blanket line and assuming it covers everything in the repo is the easy mistake — and in this case the answer happens to be fine, but by a different route than the one you checked.
- **Detection is a separate licence question from recognition.** The popular face detectors ship inside the same non-commercial packages as the recognisers. The harness uses YuNet (Apache 2.0, OpenCV Zoo) or dlib's classical HOG detector (Boost Software License, no learned weights from a scraped corpus) for exactly this reason.

### Finding 2 — face recognition invariance is the opposite of what we need

This is an unusual application. These models are trained to discriminate between *real* identities. We are measuring whether two synthetic renders depict the same invented character.

More pointedly: **ArcFace-class models are trained to be invariant to pose, lighting, expression, age, hairstyle and makeup.** Those are precisely the axes along which a persona drifts, and precisely what the condition matrix in task 1.6 varies on purpose. A recogniser that says "same person" when the persona reads five years older under golden hour is the recogniser working correctly and failing our job.

A general visual embedder has no such invariance trained into it. The cost is the mirror image — it also responds to background, clothing and framing, which the condition matrix varies too — so the face is cropped before embedding, with the margin configurable.

### Finding 3 — the master set is itself synthetic

Similarity measured within the master set partly reflects the consistency of the image generator rather than identity as such. This does not invalidate the method, but the threshold must be read as "consistent with our generator's rendering of this look", not as an identity guarantee.

### Finding 4 — the control set is the legal exposure, not the persona

The persona is synthetic, so its embeddings are probably not biometric data of an identifiable natural person. But a control set of **real** different faces (LFW and similar) is biometric data of real people, processed specifically for biometric comparison — GDPR Art. 9 special-category data, and a question entirely separate from the model licence.

Generating the control set synthetically — distinct looks from the same image model — removes that processing altogether, and is arguably the better test anyway: the relevant negative case is not "a random real person" but "another synthetic face this generator could produce". `cli.py make-fixtures` already works this way.

**This belongs in the D7 counsel scope and is not currently in it.**

## Options

**(a) Permissively-licensed open weights, self-hosted.** Free, no per-call cost, embeddings stay in our infrastructure, reproducible for provenance years out. The constraint is that the strongest weights are not the permissive ones.

**(b) Commercial licence for a high-performing weight set.** InsightFace offers commercial licensing for its open-sourced recognition models. Best accuracy, clean legal position, still self-hosted. Costs money and takes procurement time.

**(c) Hosted face-comparison API.** No weights to host, fast to start. Against: per-call cost across thousands of frames at 2 fps is likely the dominant line item; a hard external dependency for a core QA function; provider terms around face data may restrict this use; several do not return embeddings at all, which breaks the stored-embedding design in Section 4 *and* the calibration in task 1.3.

**(d) Train or fine-tune our own.** Disproportionate, and it reintroduces dataset licensing rather than removing it — the obvious synthetic corpus (DigiFace-1M) is itself non-commercial.

## Decision

**DINOv2 (option a), decided by the owner on 2026-09-22.** Recorded in
`config/spike.yaml` as `embedder.backend: dinov2`.

Apache 2.0 covers both the embedder (`facebook/dinov2-base`) and its face
detector (YuNet, OpenCV Zoo). Commercial use is explicitly granted for both,
with no third-party asterisk and no undocumented training corpus behind the
grant — which is what separates it from the dlib options rather than raw
benchmark accuracy.

The substantive reason is Finding 2, not the licence: a general visual embedder
has no trained-in invariance to the axes this project needs to measure.

**The dlib route stays wired up and is not deleted.** If DINOv2 turns out not to
separate the distributions, `face_recognition_densenet_model_v1` (MIT, via
BAREL) is the fallback and the bake-off compares them in one command. Option
(b), a paid commercial licence, remains the funded fallback beyond that.

### Original proposal, retained for the record

**Bake off two free, self-hosted candidates inside Spike 0, and keep (b) as the funded fallback.**

Both are wired up in `scripts/spike/embedders.py` and registered, so each is one command:

```bash
python -m scripts.spike.cli bake-off --backends dlib dinov2
```

- **`dlib`** — a genuine face recognition model. Two variants exist and they fill the same slot, so pick one:
  - `dlib_face_recognition_resnet_model_v1`, 128-d, 99.38% LFW. Public-domain weights per the author's statement; the FaceScrub contamination upstream is a counsel question.
  - `face_recognition_densenet_model_v1`, 96.1% LFW. MIT from BAREL — a cleaner grant, because it is explicit and comes from the model's actual author rather than resting on a blanket line that does not reach it. But less accurate, and its recognition training set is undocumented, so the provenance question is not removed, only reshaped.
- **`dinov2`** — Apache 2.0 general visual embedder on a cropped face, 768-d. Not a face recogniser, deliberately, per Finding 2.

The bake-off calibrates both on the same master and control sets and ranks on distribution overlap, then on true-positive rate — the candidate that separates, and among those the one that discards fewest good takes. It refuses to let a stub backend win, because a stub posts a perfect score on fixtures it was never going to fail.

Choose on measured separation against **our** data, not on published benchmarks: those measure real-identity recognition, which is not the task.

## Still required, now that the model is chosen

1. **A machine that can run it.** `huggingface.co` must be reachable from
   wherever this executes — that is where `facebook/dinov2-base` downloads from.
   Not verified in this repository's environment, where both `huggingface.co`
   and `dlib.net` are blocked by the container's egress allowlist.
2. Set `embedder.backends.dinov2.detector_model` to the local path of the YuNet
   ONNX file once that machine exists. `fetch-models --backend dinov2` gets it.
3. Calibrate, then check the worst-frame contact sheet before trusting the
   threshold. A scorer that agrees with the statistics and disagrees with your
   eye is still the wrong scorer.
4. Put Finding 4 (control-set biometric data) into the D7 counsel scope. Still
   outstanding.

### Superseded checklist

1. Fetch the model files listed in `config/spike.yaml` under `embedder.backends`, **read the actual current licence text for each**, and record it verbatim with the date read. Nothing is downloaded automatically: pulling in weights is a licence decision, not a cache miss.
2. Run the bake-off. Record both calibrations and the winner in this ADR.
3. Pin the chosen model, version, embedding dimension and licence in config. A change to any of them forces re-calibration (amendment A3, enforced in code).
4. Check the worst-frame contact sheet before accepting the winner. A scorer that agrees with the statistics and disagrees with your eye is still the wrong scorer.
5. If the outcome is (b) or (c), raise it under the CLAUDE.md rule requiring approval before adding a paid service. The bake-off numbers are the justification for that spend, which is a better position to buy from than guessing up front.
6. Put Finding 4 (control-set biometric data) into the D7 counsel scope.

## Consequences

Spike 0 is unblocked on the scorer. The remaining gate is somewhere to run it, not a decision.

If neither free candidate separates adequately, that is not a dead end but a decision point with evidence attached: either buy a commercial licence, or accept that automated identity scoring is **advisory rather than gating** — in which case the human review load in Phase 3 rises substantially and task 3.4's auto-reject design needs rework before it is built. The harness reports this outcome explicitly rather than quietly picking the least-bad number.

## Sources

Checked 2026-09-22. All are primary except where noted.

- InsightFace pretrained model licensing — [issue #2022](https://github.com/deepinsight/insightface/issues/2022), [python-package README](https://github.com/deepinsight/insightface/blob/master/python-package/README.md)
- SFace model licence — [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface)
- CASIA-WebFace terms — [release agreement (PDF)](http://www.cbsr.ia.ac.cn/english/casia-webFace/casia-webfAce_AgreEmeNtS.pdf)
- dlib model licence and training data — [dlib-models README](https://github.com/davisking/dlib-models/blob/master/README.md)
- DigiFace-1M licence — [microsoft/DigiFace1M](https://github.com/microsoft/DigiFace1M/blob/main/README.md)
- DINOv2 commercial relicensing — [Meta AI blog](https://ai.meta.com/blog/dinov2-facet-computer-vision-fairness-evaluation/)
- DINOv3 licence — [facebookresearch/dinov3](https://github.com/facebookresearch/dinov3)
- BAREL (densenet variant) licence — [Cydral/BAREL](https://github.com/Cydral/BAREL)

## Log

**2026-09-22** — Owner supplied two Apache 2.0 licence files and the
`face_recognition_densenet_model_v1` weights. Apache 2.0 confirms commercial use
for the DINOv2 route (model and detector). The densenet is a *different file*
from the one this ADR originally named, which turned out to be worth catching:
it is not covered by the dlib-models public-domain statement, and is MIT via
BAREL instead. Still **open** — awaiting the owner's explicit go-ahead on which
route to record, and which project each Apache file belongs to.

**2026-09-22 (later)** — Owner chose DINOv2. Recorded in config. The DINOv2
model call itself remains **unverified**: `huggingface.co` is blocked from this
repository's build environment, so the weights could not be downloaded to test
against. The YuNet detector IS verified — it downloads, its digest matches, and
it loads and runs. First person to run this on a connected machine is the first
to exercise the embedder.

**2026-09-23 (evening)** — First real calibration, `docs/reports/calibration-2026-09-23.md`.

Against a control of young women of the same type, DINOv2 reads MARGINAL:
overlap 0.297, AUC 0.894, and only 66% of the persona's own images clear the
threshold. Against the same data dlib reads EXCELLENT: overlap 0.000, AUC
1.000, 100%.

**Finding 2 above is wrong, or at least incomplete.** The argument was that a
face recogniser's invariance to pose, light and hair makes it blind to the axes
a persona drifts along, so a general visual embedder would serve better. But a
realistic control set shares the master set's styling — same lighting, same
treatment, similar hair — and a general embedder scores that as similarity. The
face recogniser's invariance is what forces it onto facial geometry.

The original argument is not refuted, only out-scoped: it was about detecting
*drift in her*, and this measurement was about telling her from *other people*.
Both matter, and the two models appear to have opposite blind spots. The drift
half cannot be measured until Phase 1 produces video.

This ADR should be revised to dlib as primary once the licence question is
settled — the ResNet's public-domain statement carries the FaceScrub caveat,
and the MIT-licensed DenseNet variant should be measured before choosing.
