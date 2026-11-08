# Separating technical correctness from AI-search outcomes

Nothing in this repository shows that any feature improves visibility in ChatGPT, Google
AI Overviews, Perplexity or another answer engine. Unit tests and HTML fixtures prove
that a check reports what it says it reports. This document says what would be needed
to support an outcome claim.

## Claims in the catalog that concern outcomes

* Category L (F111-F120) measures observed outcomes (mention rate, citation frequency,
  ...). All are `planned`, blocked on live provider adapters (Stage 05) and data
  (Stage 06). No live adapter or provider data exists; only mock and fixture providers.
* Features whose rationale mentions retrieval or citation (for example F040, F078, F080,
  F091, F092, and the "cannot be cited" wording of F051/F068) are *hypotheses about
  mechanism*. They are marked `hypothesis` or `plausible mechanism` in the matrix and
  `AI-visibility outcome demonstrated: no`.
* The one external study consulted (S09) reports that the AI crawlers it measured did
  not execute JavaScript. That supports the *technical* motivation for F051/F108 (text
  absent from the initial HTML is invisible to such crawlers) at one point in time; it
  does not show a visibility effect of fixing it.

## What would support an outcome claim

For a feature X (say F051, text present in the initial HTML):

1. **Exact claim**: "adding server-rendered text to page P increases the share of
   benchmark answers that cite P by at least d".
2. **Outcome measure**: per query in a versioned query set (Stage 04), whether the
   answer mentions the brand, cites P, and in what position; repeated N times per query
   (answers are stochastic), recording provider, model, date, locale and settings.
3. **Design**: matched control and treatment pages (similar topic and baseline
   visibility) or a staggered rollout; treatment applied to some pages only; the same
   queries before and after; a no-change control group; randomised assignment where
   possible.
4. **Confounders recorded**: content edits, site-wide changes, provider model updates,
   news events, seasonality, indexing delays (allow time for recrawl), robots changes.
5. **Analysis**: difference in differences with intervals (Wilson/bootstrap); report
   effect sizes and uncertainty, not significance alone; pre-register the metric.
6. **Safety**: no experiment against a production site without the owner's explicit
   approval; no paid API use without existing authorization; no publishing or modifying
   a customer's site (project rule).

## Status

No data, adapter or authorization for such a study exists in this repository or this
session, so every outcome claim is **unvalidated** and the report disclaimer ("no change
is guaranteed to cause AI search engines to mention or cite the site") stays. Required
evidence is listed per feature in `required_follow_up` of the matrix.
