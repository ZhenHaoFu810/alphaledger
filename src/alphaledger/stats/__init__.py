"""Statistical kernel: ranks, cross-sectional RankIC, Newey-West, max-statistic null."""

from alphaledger.stats.ic import cross_sectional_rank_ic, ic_summary
from alphaledger.stats.maxstat import bootstrap_counts, estimate_bar, max_stat_null
from alphaledger.stats.nw import iid_t, newey_west_t, student_t_two_sided_p
from alphaledger.stats.rank import average_rank_int

__all__ = [
    "average_rank_int",
    "bootstrap_counts",
    "cross_sectional_rank_ic",
    "estimate_bar",
    "ic_summary",
    "iid_t",
    "max_stat_null",
    "newey_west_t",
    "student_t_two_sided_p",
]
