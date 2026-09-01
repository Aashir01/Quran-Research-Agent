# The commons

A place to share research, ask questions and challenge claims — built on top of
the workspace rather than beside it, so a post can carry evidence instead of
only prose.

## One asymmetry runs through the whole design

A **vote** is a popularity signal. **Attached findings, verified citations and
hypothesis verdicts** are evidence signals. The feed may sort by the first. It
may never let the first overwrite the second.

Concretely: a post attaching a hypothesis that the corpus **refuted** displays
`REFUTED` in red, with its violation count, directly above the upvote score —
however popular the post is, however confidently it is written. That inversion
is the reason this layer was built on the workspace at all.

## What can be posted

Anything: a question, an insight, a finding, a hypothesis, a correction. Posts
that attach a workspace object (a `Finding`, a `Hypothesis` run, or an anchored
`Note`) are badged `evidence attached` and render that object's real state.

You may attach **your own** hypotheses and notes, or any finding a reviewer has
**approved**. Without that rule a post could borrow the authority of someone
else's verified work, which is the one thing the badge is supposed to mean.

## Scripture is rendered from the database, never typed

The rule that governs agent output governs the comment box too. A post body is
a template:

```
The pairing is explicit: {{ayah:2:45}}
```

The placeholder is resolved against the corpus at write time and its citation
stored. Raw Arabic that arrived through no placeholder and appears in no corpus
row is a **write-time rejection**, not a warning.

This is not pedantry. A feed over a religious corpus is exactly where a
fabricated verse would enter, and it would then carry the site's authority and
be screenshotted forever.

**Refusal is only half the job.** When the guard fires, the server looks the
passage up and hands back the reference:

| What you pasted | What happens |
|---|---|
| A real ayah, as raw text | Refused — *"that is 2:45, use `{{ayah:2:45}}`"*, with a one-click swap |
| A fabricated ayah | Refused, and **no** suggestion comes back. That silence is the finding: the text is in no ayah. |
| Urdu or English prose | Accepted. Word-by-word classification separates Nastaliq prose from Qur'anic Arabic. |
| A single Arabic word inline (`صبر`) | Accepted. Three consecutive plain-Arabic words is the threshold for a quotation attempt. |

The lookup slides a shrinking window so it still finds the ayah when the
orthography differs or only half a verse was pasted. Both ends are capped
(`MAX_SPAN_WORDS`, `MAX_LOOKUPS`) — a suggestion is a courtesy, and a courtesy
is not worth a denial of service.

## Voting

**Upvote only. There is no downvote.**

A downvote on a scholarly claim is a popularity verdict wearing the costume of a
correctness verdict, and on this corpus it would bury well-evidenced minority
positions. Disagreement belongs in a comment or a `correction` post, where it
has to be argued and can itself be checked.

You cannot upvote your own post. The feed sorts by `new`, `useful`
(popularity), `evidence` (checkability) or `discussed` — and reports
`exhaustive: false` on every page, like every other ranked surface in the app.
Recency always breaks ties, so an old post cannot sit at the top of "useful"
forever on a handful of early votes.

## Moderation

Posting is immediate; the safety net is after the fact.

- Anyone can flag: fabricated scripture, misattribution, off-topic, abuse, other.
- **Four independent open flags hide a post automatically**, pending review —
  the only thing between a bad post and an unattended weekend.
- Reviewers can `hide`, `remove` or `restore`. **A reason is mandatory and is
  stored on the row.** A removal nobody can account for later is
  indistinguishable from censorship.
- Removal never deletes the row. The content stops resurfacing; the record of
  what was removed, by whom and why does not.

Rate limiting is per principal on writes only, using the app's existing sliding
window. This is a research commons, not a timeline.

## Where it connects

- Every post anchored to an ayah (via `{{ayah:2:45}}` or `[[2:45]]`) appears in
  that ayah's **Discussion** tab in the reader.
- `[[root:صبر]]` anchors a post to a root.
- Findings, hypotheses and notes flow in from the workspace.
- Nothing here is a softer path into the system than the workspace it sits on:
  `reader` to read, `researcher` to write, `reviewer` to moderate.

## A bug this work surfaced

Building the write path exposed that `bootstrap_principal()` — the identity used
when auth is disabled — carried `user_id=0`, which is **not a row in
`app_user`**. Every authored write in the app (notes and findings included, not
just posts) violated its foreign key the moment auth was switched off, which is
the default on a laptop. The local identity is now a real, clearly-labelled
`local (auth disabled)` account resolved in `api/deps.py`, so a reviewer reading
something later can tell it was written on an unauthenticated deployment.
