
# Measured identity-preserving video pipeline

## Part 8 — Identity-first workflow development

**Directory anchor:** `D:\AI\ComfyUI_portable\workshop\`

For consenting subjects or synthetic characters, the next development sequence should be:

```text
Reference pack
    ↓
Identity-conditioned starting frame
    ↓
Model-specific image-to-video adapter
    ↓
Face tracking + identity + motion audit
    ↓
Targeted retry
    ↓
Upscale / interpolation
    ↓
Final audit → promotion
```

### 8.1 — Make templates executable shot specifications

Your 54 presets already handle rotation. Their next upgrade should describe **what a shot must accomplish and what makes it fail**.

Include:

| Component | Required information |
| --- | --- |
| Framing | Shot size, subject placement, face visibility |
| Camera | Movement type, direction, intensity |
| Performance | Action beats, expression, gaze |
| Identity | Explicit subject IDs and reference assets |
| Constraints | Occlusion limits, supported subject count |
| Acceptance | Identity, temporal stability, action adherence |
| Recovery | Specific changes permitted on retry |

Start with a compact benchmark set:

- Static close-up with expression change.
- Talking portrait.
- Slow camera push-in.
- Walking medium shot.
- Three-quarter head turn.
- Hand briefly crossing the face.
- Two-person conversation.
- Lighting change without a scene cut.

**These expose real identity weaknesses much faster than testing dozens of elaborate scenes.**

### 8.2 — Separate starting-frame quality from temporal retention

These are different engineering problems.

> **Starting frame**

- Use clean, sharp references with useful facial detail.
- Keep identity references separate from wardrobe and scene references.
- Where the installed model supports it, test reference-image or identity conditioning.
- Approve the composed frame before spending compute on video.

> **Temporal retention**

- Use the approved frame as the video input.
- Start with short shots and moderate movement.
- Use additional temporal identity conditioning only where genuinely supported by the selected architecture.
- Test reference-conditioned generation against an identity-LoRA variant rather than assuming the LoRA improves results.

**An identity adapter for one image model is not automatically compatible with a video model.** Your compatibility matrix should record tested combinations, not inferred compatibility.

### 8.3 — Audit trajectories, not one attractive frame

Extend `audit_batch.py` to evaluate each subject across time.

| Signal | What it detects |
| --- | --- |
| Reference-to-frame face similarity | Identity drift |
| Lower-percentile identity similarity | Brief but severe failures hidden by averages |
| Face detection coverage | Missing or unmeasurable face intervals |
| Track continuity | Subject swaps or broken associations |
| Pose-aware landmark consistency | Unexplained facial deformation |
| Motion-compensated face-region consistency | Flicker and texture instability |
| Action adherence | A stable face that ignores the template |

Important safeguards:

- **Calibrate similarity thresholds** against labeled same-person and different-person examples; there is no universal reliable cutoff.
- Score similarity on suitable visible frames; report coverage separately.
- Distinguish an intentional occlusion from a failed detection.
- In multi-person shots, associate detections with subject tracks before scoring.
- Keep human review for close calls and final benchmark comparisons.

Face embeddings are useful measurements, not proof that a clip looks correct.

### 8.4 — Retry the failed dimension

Do not simply reroll every failed clip.

| Failure | Controlled retry |
| --- | --- |
| Identity drifts during turns | Reduce turn amplitude; test better angled references |
| Face distorts during fast motion | Reduce action speed or shot duration |
| Subjects exchange identities | Strengthen spatial separation; test supported per-subject conditioning |
| Identity is stable but motion is weak | Increase motion incrementally |
| Face flickers after enhancement | Reduce or remove restoration; audit native output |
| Outfit changes | Improve starting-frame wardrobe consistency and simplify action |

**Face restoration and face replacement should not be the primary retention strategy.** They can conceal generation problems while adding temporal artifacts.

### 8.5 — Benchmark quality against cost

For your RTX 5090, compare candidates on the same reference packs and shot specifications. Log actual peak VRAM and runtime rather than promising that a model will fit based on parameter count.

Record:

```text
model/checkpoint hash
workflow + custom-node versions
reference and preset hashes
LoRA hashes + strengths
seed and sampler settings
native resolution / frame count / FPS
peak VRAM / generation time
per-subject audit results
human preference result
retry count
```

Run multiple seeds per benchmark condition. Keep your existing B/A/S tiers as **requested output targets**; the adapter must resolve them to each model’s supported dimensions and frame-count rules.

Track **cost per accepted clip**, not just seconds per generation.

### 8.6 — Implement in this order

1. **`workflow_adapter.py`** — map queued preset snapshots to validated, installed ComfyUI workflows; reject unsupported features.
2. **`reference_registry.py`** — version subject references, permissions, and identity assets.
3. **`audit_identity.py`** — detection, tracking, per-subject scoring, coverage, and review outputs.
4. **`benchmark_runner.py`** — controlled model/conditioning/template comparisons.
5. **`retry_policy.py`** — bounded, failure-specific retries with full provenance.
6. **Promotion gate** — require both identity and motion quality before accepting the render.

**The highest-value next step is the workflow adapter plus an eight-shot identity benchmark.** Share one working ComfyUI **API-format workflow JSON** and its checkpoint/custom-node versions; that lets us build against real node contracts rather than inventing a plausible but unusable graph.
