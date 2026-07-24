# The Offset, in Plain English (with a worked example)

This explains the single most important piece of the two-tier model — the
**per-beach offset** — from scratch, with numbers. If you read only one section,
read the worked example.

---

## 1. The one idea

Every risk prediction can be split into two parts:

> **today's risk = this beach's normal level + how far today deviates from that beach's normal**

- **The level** ("how dirty is Pinewood Cove *usually*?") we already know — it's
  the beach's historical exceedance rate. It's the same every day and we never
  have to guess it.
- **The deviation** ("is *today* worse or better than normal for Pinewood?") is
  the hard part, the part that actually needs a model, and the only part worth
  spending the model's effort on.

The **offset** is how we hand the model the level for free, so 100% of its
learning goes into the deviation.

---

## 2. The equation

Models like XGBoost work in **log-odds** (also called "logit" or "margin"), not
raw percentages, because log-odds add up cleanly. Two conversions are all you need:

- `logit(p) = ln(p / (1 - p))` — turn a probability into log-odds
- `sigmoid(m) = 1 / (1 + e^(-m))` — turn log-odds back into a probability

The offset model computes:

```
risk_logodds = beach_baseline  +  today_deviation
                   ▲                    ▲
          fixed, given for free    the model's ONLY job
          (the "offset"/base_margin)   (the trees learn this)
```

`beach_baseline` is the beach's historical rate expressed as log-odds. In
XGBoost this fixed starting value is called **`base_margin`** — the prediction
the trees start from before they add anything. The trees can then only *add*
corrections on top, so they are structurally forced to learn deviations.

---

## 3. The worked example  ← the important part

Two beaches:

| beach | historically exceeds | baseline as log-odds `logit(p)` |
|---|---|---|
| **Pinewood Cove** (chronically dirty) | 60% of days | `logit(0.60) = +0.41` |
| **Cliffside** (chronically clean) | 5% of days | `logit(0.05) = −2.94` |

Now suppose the model (the tree part) has learned exactly **one** thing from the
weather data — a single deviation rule:

> heavy rain today → **+1.5** log-odds  ·  a dry day → **−0.5** log-odds

Watch what happens when we apply that **same** rule on top of each beach's offset:

| beach | weather | `baseline + deviation` | = log-odds | → probability `sigmoid()` | band |
|---|---|---|---|---|---|
| Pinewood | rainy | `+0.41 + 1.5` | `+1.91` | **0.87** | Very High |
| Pinewood | dry | `+0.41 − 0.5` | `−0.09` | **0.48** | High |
| Cliffside | rainy | `−2.94 + 1.5` | `−1.44` | **0.19** | Moderate |
| Cliffside | dry | `−2.94 − 0.5` | `−3.44` | **0.03** | Low |

Look at what the model achieved with **one** learned rule:

- **The rain rule is universal.** "+1.5 for rain" is the *same* number at both
  beaches. The model never had to learn a separate rain effect per beach — it
  learned rain *once*, and the offset placed it at the right absolute height.
- **Same weather, different verdict.** A rainy day is "Very High" at Pinewood
  (0.87) but only "Moderate" at Cliffside (0.19) — correctly, because Pinewood
  starts dirtier. The *offset* produced that difference, not the model.
- **Rain still matters at the clean beach.** Cliffside goes 0.03 → 0.19 on rain,
  a 6× jump. The model can flag a bad day even at a usually-clean beach.
- **A dirty beach stays elevated on a good day.** Pinewood dry is still 0.48 —
  it doesn't get declared "safe" just because it didn't rain.

That is the entire point: **the model only had to learn "rain adds 1.5." The
offset did the rest.**

---

## 4. What the deployed model does instead — and why it breaks

The current shipped model has **no offset**. It must output the *full* log-odds
(the `+1.91`, the `−1.44`) straight from the features. To do that it has to
internally figure out, from the data, both:

1. **which beach this is** (is the baseline +0.41 or −2.94?), and
2. the rain effect on top.

Two things go wrong:

- **The level drowns out the deviation.** The two beaches' baselines differ by
  `0.41 − (−2.94) = 3.35` log-odds, while the rain deviation is only ~2. So most
  of the "error" the model chases is about getting the *beach* right, and it
  barely tunes the rain effect. It becomes a beach-identity lookup table.
- **It figures out "which beach" from stale features.** The signal it uses to
  identify the beach is the *lagged lab history* (the 30-day geomean of recent
  samples). On a fresh sample-day that's current. But the product serves
  **between** samples, where that history is 1–4 weeks stale. When it goes stale
  the model loses its read on which beach it's looking at, falls back toward a
  low baseline, and **under-warns** — it calls a dirty beach "safe."

The offset removes both failures at once: the baseline is supplied fresh and
exactly correct **every day** (a beach's historical rate doesn't go stale), so
the model never has to recover it from decaying features, and all of its learned
capacity is spent on the deviation — which comes from today's weather and is
fresh every single day.

---

## 5. Why an offset, and not just another input feature

Natural question: why not just add `beach_baseline` as one more **column** in the
feature table and let the model use it? We tested exactly that. It's **0.05 AUCPR
worse** (0.61 vs 0.67). Here's why:

- **As a feature**, the tree is *free* to use the baseline — it can split on it
  coarsely, combine it oddly with other features, or under-weight it. It
  approximates the level, spending tree capacity re-deriving something we already
  knew *exactly*. Nothing forces it to stop modelling the level and move on to
  deviations.
- **As `base_margin` (the offset)**, the baseline is added **exactly and for
  free** — zero tree capacity spent — and the trees can *only* add corrections on
  top. They are structurally unable to earn credit for the level, so every split
  they make is about deviation. That's the 0.05 AUCPR, and it's why the offset is
  worth the extra plumbing (the model has to be handed `beach_id` at predict time
  to look up the right baseline).

This is the same trick as an **`offset` term in a GLM / Poisson regression** — a
known additive term the fitted coefficients are not allowed to touch.

---

## 6. The shrinkage wrinkle (small but real)

We don't use a beach's *raw* historical rate as its baseline, because a beach with
only a handful of samples would get an overconfident number. Example: a beach with
3 samples, all clean, has a raw rate of 0/3 = 0%, whose `logit` is minus infinity —
absurd ("this beach can *never* exceed").

Instead we **shrink toward the global rate**, as if we'd also seen a few phantom
samples at the ~17% average:

```
baseline_rate = (exceedances + 4 × global_rate) / (samples + 4)
```

For that 3-sample beach: `(0 + 4×0.17) / (3 + 4) = 0.097` → a sane "probably
cleaner than average, but we're not certain." A beach with 500 samples barely
moves (the 4 phantom samples are a rounding error), so well-measured beaches keep
their real rate and thin ones borrow from the average. (`prior_strength = 4` is
the "4 phantom samples" knob.)

---

## 7. Why this is *the* fix for the staleness problem

Tie it back to the audit (`model_truth.md`): the deployed model scores well on
fresh sample-days but collapses on the stale between-sample days it actually
serves, because its skill was borrowed from the recent-lab-history feature that
goes stale.

The offset severs that dependency:

- **What we always know (the level)** is supplied fresh and exact every day.
- **What we must predict (the deviation)** comes from weather/streamflow/waves,
  which update daily and never go stale.

Neither half depends on a stale lab-history feature, so the model degrades
gracefully instead of defaulting to "safe." In the censored/served-regime test,
this moved served AUCPR **0.535 → 0.667**, Brier **0.119 → 0.086**, and the
under-warning bias **−0.10 → −0.03** (adding the staleness augmentation on top
closes that last bit to ≈ 0).

---

### TL;DR

The offset splits the prediction into **"how dirty is this beach normally"**
(known, always fresh, handed to the model for free) and **"how bad is today
versus that"** (the only thing the model learns, from fresh weather). The
deployed model tangled the two together and lost both when the lab-history signal
went stale. Untangling them is the offset.
