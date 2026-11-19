"""Prop-firm account rules as data, not as code.

**Prop-firm rules change, and this module must never be trusted blindly.**
Every number below is a *default*, sourced from what the user supplied on
2026-08-05 (see :data:`RULES_AS_OF`) or, where noted in a preset's
``source_note``, from a reasonable-but-unverified assumption filled in to make
the dataclass usable at all. Before trusting any output derived from these
presets -- a "would I have survived" answer, a payout-eligibility claim, a
sizing recommendation -- **re-read the firm's current rulebook and diff it
against the fields on the :class:`AccountRules` instance you are using.**
Nothing here is fetched live; nothing here is guaranteed current.

Two things are deliberately *not* baked in as fixed behaviour:

* The trailing/locking mechanics (:class:`TrailOn`, :class:`LockAt`,
  ``includes_unrealized``) are configurable enums/flags, not an if/else buried
  in the simulator, because different firms (and the same firm at different
  times) implement trailing drawdown differently.
* Payout eligibility is modelled as a list of :class:`PayoutPath` objects
  rather than a single hardcoded condition, because "5 winning days" and "40%
  consistency" are two independently-satisfiable routes to the same payout,
  and firms have been known to change the thresholds without changing the
  shape of the rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum
from typing import Any

__all__ = [
    "RULES_AS_OF",
    "TrailOn",
    "LockAt",
    "PayoutPathKind",
    "PayoutPath",
    "AccountRules",
    "STANDARD_PAYOUT_PATH",
    "CONSISTENCY_PAYOUT_PATH",
    "TOPSTEP_COMBINE_50K",
    "TOPSTEP_COMBINE_100K",
    "TOPSTEP_COMBINE_150K",
    "TOPSTEP_FUNDED_50K",
    "TOPSTEP_FUNDED_100K",
    "TOPSTEP_FUNDED_150K",
    "TOPSTEP_EXPRESS_FUNDED_50K",
    "TOPSTEP_EXPRESS_FUNDED_100K",
    "TOPSTEP_EXPRESS_FUNDED_150K",
    "PRESETS",
    "get_preset",
]

#: The date the *user-supplied* numbers in this module (MLL dollar amounts,
#: the trailing/lock description, Express Funded's $0 start, both payout
#: paths) were provided. Anything in a preset's ``source_note`` marked
#: "assumed" was NOT supplied on this date and carries lower confidence --
#: verify those fields independently before relying on them.
RULES_AS_OF = date(2026, 8, 5)


class TrailOn(str, Enum):
    """What value the trailing Maximum Loss Limit threshold trails.

    ``EOD_CLOSE``: the threshold only *moves* once per trading day, using that
    day's closing (realised) balance as the new high-water mark candidate.
    This is the behaviour the user described ("trails based on end-of-day
    results") and is TopstepX's documented mechanic as of the source date.

    ``INTRADAY_PEAK``: the threshold moves continuously, using the highest
    equity actually *touched* intraday (realised + unrealised, i.e. including
    a trade's MFE) as the high-water mark. Some firms and some historical
    Topstep rule versions worked this way. Offered as a configuration option,
    not the default, because the user's description matches ``EOD_CLOSE``.

    Note this is orthogonal to :data:`AccountRules.includes_unrealized`: a
    breach can be detected intrabar from open drawdown (MAE) even while the
    threshold itself only *ratchets* at end of day. See
    :mod:`lab.risk.account` for exactly how the two interact.
    """

    EOD_CLOSE = "eod_close"
    INTRADAY_PEAK = "intraday_peak"


class LockAt(str, Enum):
    """When the trailing threshold stops trailing (locks) permanently.

    ``STARTING_BALANCE``: once the threshold, ratcheting up, would reach the
    account's starting balance, it clamps there and never moves again -- the
    well-known "trails until you're break-even, then it's fixed" behaviour.
    For an Express Funded account (``starting_balance == 0``) this locks the
    floor at $0.

    ``NEVER``: the threshold keeps trailing for the life of the account (only
    ever moving up, never down).

    ``PROFIT_TARGET``: the threshold locks once cumulative equity reaches
    ``AccountRules.profit_target``. Requires ``profit_target`` to be set;
    constructing an :class:`AccountRules` with this and no target raises.
    """

    STARTING_BALANCE = "starting_balance"
    NEVER = "never"
    PROFIT_TARGET = "profit_target"


class PayoutPathKind(str, Enum):
    """Which family of payout rule a :class:`PayoutPath` implements."""

    STANDARD = "standard"
    CONSISTENCY = "consistency"


@dataclass(frozen=True, slots=True)
class PayoutPath(object):
    """One independently-satisfiable route to payout eligibility.

    A rule set can carry more than one path (that is the whole point --
    Topstep's August 2026 rules, as supplied by the user, offer two), and an
    account is eligible the moment *any* path is satisfied. Threshold fields
    left as ``None`` fall back to the matching field on the
    :class:`AccountRules` the path is attached to, so a firm-wide default
    ("a winning day is >= $150") does not have to be repeated on every path.

    Attributes
    ----------
    kind:
        ``STANDARD`` (N winning days of >= $X) or ``CONSISTENCY`` (>= N
        trading days, largest single day <= Y% of total profit).
    min_trading_days:
        Minimum distinct trading days with at least one trade, required by
        this path specifically (separate from any account-wide
        ``AccountRules.min_trading_days``).
    min_winning_days:
        STANDARD path only: number of distinct days with realised PnL >=
        ``min_winning_day_amount`` required.
    min_winning_day_amount:
        STANDARD path only: dollar bar a day's realised PnL must clear to
        count as a "winning day". ``None`` -> falls back to
        ``AccountRules.min_winning_day``.
    max_single_day_share:
        CONSISTENCY path only: the largest single day's realised profit must
        be <= this fraction of cumulative realised profit. ``None`` -> falls
        back to ``AccountRules.consistency_max_day_share``.
    source_note:
        Where this exact threshold came from and how stale it might be.
    """

    kind: PayoutPathKind
    name: str
    min_trading_days: int = 0
    min_winning_days: int | None = None
    min_winning_day_amount: float | None = None
    max_single_day_share: float | None = None
    source_note: str = ""

    def __post_init__(self) -> None:
        if self.kind is PayoutPathKind.STANDARD and not self.min_winning_days:
            raise ValueError(
                f"payout path {self.name!r}: STANDARD path needs min_winning_days > 0"
            )
        if self.kind is PayoutPathKind.CONSISTENCY and self.min_trading_days <= 0:
            raise ValueError(
                f"payout path {self.name!r}: CONSISTENCY path needs min_trading_days > 0"
            )


#: Path A, "standard": 5 winning days of >= $150 each. User-supplied 2026-08-05.
STANDARD_PAYOUT_PATH = PayoutPath(
    kind=PayoutPathKind.STANDARD,
    name="standard_5x150",
    min_winning_days=5,
    min_winning_day_amount=150.0,
    source_note=(
        "User-supplied 2026-08-05: 5 winning days of >= $150 each (net realised "
        "PnL per day). Re-verify count and dollar bar against the current rulebook."
    ),
)

#: Path B, "consistency": >= 3 trading days, largest single day <= 40% of
#: total profit. User-supplied 2026-08-05.
CONSISTENCY_PAYOUT_PATH = PayoutPath(
    kind=PayoutPathKind.CONSISTENCY,
    name="consistency_40pct",
    min_trading_days=3,
    max_single_day_share=0.40,
    source_note=(
        "User-supplied 2026-08-05: >= 3 trading days with the single largest "
        "day's realised profit <= 40% of cumulative realised profit. "
        "Re-verify the day count and percentage against the current rulebook."
    ),
)

_BOTH_PAYOUT_PATHS = (STANDARD_PAYOUT_PATH, CONSISTENCY_PAYOUT_PATH)


@dataclass(frozen=True, slots=True)
class AccountRules(object):
    """A firm's account rules, as one immutable, fully-parameterised object.

    Nothing about *how* a rule set behaves is hardcoded into the simulator in
    :mod:`lab.risk.account`; every knob a firm might change (or that the same
    firm's Combine/Funded/Express variants disagree on) is a field here.

    Attributes
    ----------
    starting_balance:
        Equity the account actually opens with. Equal to ``nominal_size`` for
        Combine and (this module's assumption) Funded accounts; **zero** for
        Express Funded accounts per the user's 2026-08-05 statement.
    nominal_size:
        The account "size" as marketed (50K/100K/150K) -- used to label the
        account and, for Combine/Funded, to size ``starting_balance``. Kept
        separate from ``starting_balance`` specifically so Express Funded's
        $0-start does not have to lie about which tier's MLL/targets it uses.
    max_loss_limit:
        Trailing drawdown allowance in dollars (the "MLL"). The account
        breaches when equity (realised, or realised+unrealised per
        ``includes_unrealized``) touches ``peak - max_loss_limit``.
    trail_on, includes_unrealized, lock_at:
        See :class:`TrailOn`, :class:`LockAt` and the module docstring.
    daily_loss_limit:
        Firm-imposed hard stop on a single day's realised loss, if any. Left
        ``None`` by default on every preset in this module because the
        source the user provided (2026-08-05) did not specify one --
        Topstep-family firms have gone back and forth on enforcing one. Set
        it explicitly once you have confirmed the current rulebook.
    personal_daily_stop:
        Self-imposed daily loss cap, purely a research/discipline input --
        never a firm rule. ``None`` means "no personal stop simulated."
    profit_target:
        Dollar target to graduate a Combine, if the firm sets one. Left
        ``None`` on every preset here (not supplied by the user) rather than
        guessing a percentage-of-account figure -- fill it in from the
        current rulebook before running anything that depends on it (e.g.
        ``lock_at=PROFIT_TARGET``).
    min_trading_days:
        Account-wide minimum number of distinct trading days before *any*
        payout/graduation is possible, independent of any individual
        :class:`PayoutPath`'s own day requirement. Defaults to 0 (unenforced)
        for the same reason as ``profit_target``.
    payout_paths:
        Independently-satisfiable routes to payout eligibility. Empty for
        Combine presets (nothing to pay out on an evaluation account).
    consistency_max_day_share / min_winning_day:
        Firm-wide defaults a :class:`PayoutPath` falls back to when it leaves
        its own threshold as ``None``.
    commission_per_rt:
        Flat per-round-turn commission assumption used by sizing/frequency
        analysis when this module needs a cost number and isn't handed one
        from :mod:`lab.core.instruments`. Deliberately symbol-agnostic and
        defaulted to 0.0 -- pass the real instrument's
        ``commission_round_turn`` in from the caller when you have one.
    source_note:
        Free-text provenance for this specific preset. Always read this
        before trusting the preset.
    rules_as_of:
        Vintage date for this specific instance. Defaults to
        :data:`RULES_AS_OF` but is copied forward by :meth:`with_` so a
        deliberately-edited rule set still says when its *base* came from.
    """

    name: str
    starting_balance: float
    nominal_size: float
    max_loss_limit: float
    trail_on: TrailOn
    includes_unrealized: bool
    lock_at: LockAt
    daily_loss_limit: float | None = None
    personal_daily_stop: float | None = None
    profit_target: float | None = None
    min_trading_days: int = 0
    payout_paths: tuple[PayoutPath, ...] = ()
    consistency_max_day_share: float = 0.40
    min_winning_day: float = 150.0
    commission_per_rt: float = 0.0
    source_note: str = ""
    rules_as_of: date = RULES_AS_OF

    def __post_init__(self) -> None:
        if self.starting_balance < 0:
            raise ValueError(f"{self.name}: starting_balance must be >= 0")
        if self.nominal_size <= 0:
            raise ValueError(f"{self.name}: nominal_size must be > 0")
        if self.max_loss_limit <= 0:
            raise ValueError(f"{self.name}: max_loss_limit must be > 0")
        if not 0 < self.consistency_max_day_share <= 1:
            raise ValueError(f"{self.name}: consistency_max_day_share must be in (0, 1]")
        if self.min_winning_day < 0:
            raise ValueError(f"{self.name}: min_winning_day must be >= 0")
        if self.commission_per_rt < 0:
            raise ValueError(f"{self.name}: commission_per_rt must be >= 0")
        if self.lock_at is LockAt.PROFIT_TARGET and self.profit_target is None:
            raise ValueError(
                f"{self.name}: lock_at=PROFIT_TARGET requires profit_target to be set"
            )
        if self.daily_loss_limit is not None and self.daily_loss_limit <= 0:
            raise ValueError(f"{self.name}: daily_loss_limit must be > 0 when set")
        if self.personal_daily_stop is not None and self.personal_daily_stop <= 0:
            raise ValueError(f"{self.name}: personal_daily_stop must be > 0 when set")

    @property
    def initial_threshold(self) -> float:
        """The MLL threshold before any trailing has happened."""
        return self.starting_balance - self.max_loss_limit

    def resolve_min_winning_day_amount(self, path: PayoutPath) -> float:
        return (
            self.min_winning_day
            if path.min_winning_day_amount is None
            else path.min_winning_day_amount
        )

    def resolve_max_single_day_share(self, path: PayoutPath) -> float:
        return (
            self.consistency_max_day_share
            if path.max_single_day_share is None
            else path.max_single_day_share
        )

    def with_(self, **kwargs: Any) -> "AccountRules":
        """Copy with fields replaced -- for what-if sweeps over a preset."""
        return replace(self, **kwargs)


def _combine(nominal: float, mll: float, source_note: str) -> AccountRules:
    return AccountRules(
        name=f"topstep_combine_{int(nominal // 1000)}k",
        starting_balance=nominal,
        nominal_size=nominal,
        max_loss_limit=mll,
        trail_on=TrailOn.EOD_CLOSE,
        includes_unrealized=True,
        lock_at=LockAt.STARTING_BALANCE,
        daily_loss_limit=None,
        personal_daily_stop=None,
        profit_target=None,
        min_trading_days=0,
        payout_paths=(),
        source_note=source_note,
    )


def _funded(nominal: float, mll: float, source_note: str) -> AccountRules:
    return AccountRules(
        name=f"topstep_funded_{int(nominal // 1000)}k",
        starting_balance=nominal,
        nominal_size=nominal,
        max_loss_limit=mll,
        trail_on=TrailOn.EOD_CLOSE,
        includes_unrealized=True,
        lock_at=LockAt.STARTING_BALANCE,
        daily_loss_limit=None,
        personal_daily_stop=None,
        profit_target=None,
        min_trading_days=0,
        payout_paths=_BOTH_PAYOUT_PATHS,
        source_note=source_note,
    )


def _express_funded(nominal: float, mll: float, source_note: str) -> AccountRules:
    return AccountRules(
        name=f"topstep_express_funded_{int(nominal // 1000)}k",
        starting_balance=0.0,
        nominal_size=nominal,
        max_loss_limit=mll,
        trail_on=TrailOn.EOD_CLOSE,
        includes_unrealized=True,
        lock_at=LockAt.STARTING_BALANCE,
        daily_loss_limit=None,
        personal_daily_stop=None,
        profit_target=None,
        min_trading_days=0,
        payout_paths=_BOTH_PAYOUT_PATHS,
        source_note=source_note,
    )


_MLL_SOURCE = (
    "MLL dollar amount user-supplied 2026-08-05. trail_on=EOD_CLOSE, "
    "includes_unrealized=True and lock_at=STARTING_BALANCE together encode the "
    "user's description: 'the MLL includes unrealised P&L and trails based on "
    "end-of-day results until it locks.' profit_target, min_trading_days and "
    "daily_loss_limit were NOT supplied and default to unenforced (None/0) -- "
    "set them from the current rulebook before relying on graduation-timing or "
    "daily-limit output."
)

TOPSTEP_COMBINE_50K = _combine(50_000, 2_000, _MLL_SOURCE)
TOPSTEP_COMBINE_100K = _combine(100_000, 3_000, _MLL_SOURCE)
TOPSTEP_COMBINE_150K = _combine(150_000, 4_500, _MLL_SOURCE)

TOPSTEP_FUNDED_50K = _funded(50_000, 2_000, _MLL_SOURCE)
TOPSTEP_FUNDED_100K = _funded(100_000, 3_000, _MLL_SOURCE)
TOPSTEP_FUNDED_150K = _funded(150_000, 4_500, _MLL_SOURCE)

_EXPRESS_SOURCE = _MLL_SOURCE + (
    " starting_balance=0 is user-supplied 2026-08-05 ('Express Funded accounts "
    "start at a $0 balance rather than the nominal account size'). Whether Topstep "
    "actually offers Express Funded at every one of 50K/100K/150K, and whether the "
    "100K/150K MLL figures given for Funded also apply unchanged to Express Funded "
    "at those sizes, was ASSUMED for symmetry, not confirmed -- verify before use."
)

TOPSTEP_EXPRESS_FUNDED_50K = _express_funded(50_000, 2_000, _EXPRESS_SOURCE)
TOPSTEP_EXPRESS_FUNDED_100K = _express_funded(100_000, 3_000, _EXPRESS_SOURCE)
TOPSTEP_EXPRESS_FUNDED_150K = _express_funded(150_000, 4_500, _EXPRESS_SOURCE)

PRESETS: dict[str, AccountRules] = {
    r.name: r
    for r in (
        TOPSTEP_COMBINE_50K, TOPSTEP_COMBINE_100K, TOPSTEP_COMBINE_150K,
        TOPSTEP_FUNDED_50K, TOPSTEP_FUNDED_100K, TOPSTEP_FUNDED_150K,
        TOPSTEP_EXPRESS_FUNDED_50K, TOPSTEP_EXPRESS_FUNDED_100K, TOPSTEP_EXPRESS_FUNDED_150K,
    )
}


def get_preset(name: str) -> AccountRules:
    """Look up a preset by name, e.g. ``"topstep_funded_100k"``."""
    key = name.strip().lower()
    if key in PRESETS:
        return PRESETS[key]
    raise KeyError(f"unknown account preset {name!r}; known: {sorted(PRESETS)}")
