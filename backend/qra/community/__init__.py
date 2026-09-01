"""The commons: shared research, discussion and signals.

Built on one asymmetry. A vote is a *popularity* signal; attached findings,
verified citations and hypothesis verdicts are *evidence* signals. The feed may
sort by the first. It may never let the first overwrite the second — an upvoted
post whose attached hypothesis was refuted still reads "refuted", in red, above
the score.
"""

from qra.community.service import CommunityError

__all__ = ["CommunityError"]
