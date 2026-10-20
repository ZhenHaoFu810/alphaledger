"""Factor identity: value fingerprints (authoritative) and expression hashes (diagnostic)."""

from alphaledger.identity.normalize import CanonicalizeError, canonical_expr, expr_fingerprint
from alphaledger.identity.similarity import NEAR_DUPLICATE_THRESHOLD, max_abs_corr
from alphaledger.identity.value_fp import value_fingerprint

__all__ = [
    "CanonicalizeError",
    "NEAR_DUPLICATE_THRESHOLD",
    "canonical_expr",
    "expr_fingerprint",
    "max_abs_corr",
    "value_fingerprint",
]
