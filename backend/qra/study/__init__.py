"""Study series and the spaced-repetition trainer.

`get_series` rather than `series`: exporting a function under the same name as
the module that defines it shadows the module, and `from qra.study import
series` then hands back the function.
"""

from qra.study.series import (  # noqa: F401
    SeriesError,
    create_series,
    get_series,
    mark_done,
    seed_starters,
    series_listing,
)
from qra.study.trainer import (  # noqa: F401
    TrainerError,
    add_card,
    due,
    grade,
    review_stats,
    seed_from_series,
    suggest_cards,
)
