# The claim registry

A `Finding` is what one run produced. A `Claim` is an assertion the team stands
behind, which may outlive several runs and be revised by later ones.

What decays in a research group is not the evidence — it is the memory of *why*
a claim was accepted, by whom, and what was said against it at the time. Three
rules follow.

## Status is a projection of a history

Every change is a `ClaimEvent` with an actor, a timestamp and a **non-nullable
reason**. The current status is derived from that history rather than being a
value someone set. A status change with no reason is, six months later,
indistinguishable from an accident.

```
proposed         →            → proposed      claim-author    from the co-occurrence sweep
status_changed   proposed     → under_review  claim-reviewer  picked up for review
status_changed   under_review → supported     claim-reviewer  counts and baseline verified
objection_raised                              claim-author    the same pairing holds in the hadith corpus
status_changed   supported    → contested     claim-author    an unanswered objection was raised
```

## `contested` is a status, not an absence of one

Most registries force a claim to be accepted or rejected. That is not the shape
this material has: the classical literature disagrees about most things worth
claiming, and a schema that cannot represent disagreement will be made to lie
about it.

## Claims are superseded, never deleted

A withdrawn claim stays readable with its reason attached, because the fact that
something was once believed and then dropped is exactly what stops the next
researcher rediscovering it. Supersession chains are checked for cycles — a
chain that loops has no current version and every reader walking it spins.

## What the registry refuses

| Refusal | Why |
|---|---|
| `proposed` → `supported` directly | The point of the registry is that an asserting status has a reviewer behind it |
| An author promoting their own claim | Self-approval recorded as review is worse than no status at all |
| L0 or L1 with no citation | Those levels assert what the sources *say*; without a citation the level does work the evidence cannot |
| Any change with an empty reason | See above |
| A claim superseding itself, or a cycle | Leaves no current version |

An asserting claim that draws an unanswered objection is moved to `contested`
automatically. Leaving it marked `supported` would be the registry telling a
reader something it knows to be doubtful.

**Validation happens before mutation.** An earlier draft assigned the new status
to the in-memory row and *then* validated the reason, so a caller that caught
the error left a dirty `Claim` behind — and the next commit would have persisted
a status change with no event under it, which is the one thing this table exists
to prevent. Same shape as the rijal rebuild guard that ran after its first
`DELETE`.

# Citation styles

Four styles — `chicago`, `mla`, `ijmes`, `plain` — because a researcher who
cannot paste a citation into a submission will retype it, and a retyped citation
is where the surah number drifts by one.

Two conventions specific to this material, both of which a generic citation
library gets wrong:

**Scripture is cited by reference, not by page.** Qur'an 2:255 *is* the
citation. The edition determines the wording, not the location, so it follows
the reference rather than replacing it.

**A hadith's grading travels with it in every style.** Authenticity is part of a
narration's identity in a way that has no analogue in secular citation — quoting
Bukhari 1 without saying it was graded *sahih* omits what a reader needs most.
Where a published manual has no slot for it, it is appended rather than dropped,
and the payload says so.

Arabic patronymics are not inverted: a generic formatter splits on the last
space and turns "Ibn Kathir" into "Kathir, Ibn". `Ibn`, `Abu`, `al-` and their
kin are part of the name.
