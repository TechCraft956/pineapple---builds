"""The rule definitions themselves: presets, validation, and their provenance.

These tests deliberately assert the *user-supplied* numbers and the presence of
provenance metadata. If a preset's value changes because the firm changed its
rulebook, these tests should fail — that failure is the reminder to re-verify
everything downstream, not an inconvenience to be silenced.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab.risk.rules import (
    PRESETS,
    RULES_AS_OF,
    AccountRules,
    LockAt,
    PayoutPath,
    PayoutPathKind,
    TOPSTEP_COMBINE_50K,
    TOPSTEP_EXPRESS_FUNDED_50K,
    TOPSTEP_FUNDED_50K,
    TOPSTEP_FUNDED_100K,
    TOPSTEP_FUNDED_150K,
    TrailOn,
    get_preset,
)


@pytest.mark.parametrize(
    "preset, nominal, mll",
    [
        (TOPSTEP_FUNDED_50K, 50_000, 2_000),
        (TOPSTEP_FUNDED_100K, 100_000, 3_000),
        (TOPSTEP_FUNDED_150K, 150_000, 4_500),
    ],
)
def test_maximum_loss_limits_match_the_supplied_figures(preset, nominal, mll):
    assert preset.nominal_size == nominal
    assert preset.max_loss_limit == mll
    assert preset.initial_threshold == nominal - mll


def test_express_funded_starts_at_zero_not_nominal_size():
    # The whole reason Express Funded is modelled separately: the account opens
    # at $0, so its drawdown floor is -2,000, not 48,000.
    assert TOPSTEP_EXPRESS_FUNDED_50K.starting_balance == 0.0
    assert TOPSTEP_EXPRESS_FUNDED_50K.nominal_size == 50_000
    assert TOPSTEP_EXPRESS_FUNDED_50K.initial_threshold == -2_000.0


def test_funded_accounts_carry_both_payout_paths():
    kinds = {p.kind for p in TOPSTEP_FUNDED_150K.payout_paths}
    assert kinds == {PayoutPathKind.STANDARD, PayoutPathKind.CONSISTENCY}


def test_combine_has_no_payout_paths():
    # Nothing to withdraw from an evaluation account.
    assert TOPSTEP_COMBINE_50K.payout_paths == ()


def test_every_preset_carries_provenance():
    assert PRESETS, "preset registry must not be empty"
    for name, rules in PRESETS.items():
        assert rules.source_note.strip(), f"{name} has no source_note"
        assert rules.rules_as_of == RULES_AS_OF
    assert isinstance(RULES_AS_OF, dt.date)


def test_get_preset_is_case_insensitive_and_errors_helpfully():
    assert get_preset(TOPSTEP_FUNDED_50K.name.upper()) is TOPSTEP_FUNDED_50K
    with pytest.raises(KeyError) as exc:
        get_preset("not_a_real_account")
    assert "not_a_real_account" in str(exc.value)


def test_defaults_are_defaults_not_guesses():
    # Fields the source did not specify are left None rather than invented.
    # A fabricated daily loss limit or profit target would silently change every
    # survival number downstream.
    for rules in PRESETS.values():
        assert rules.daily_loss_limit is None
        assert rules.profit_target is None
        assert rules.personal_daily_stop is None


def test_invalid_rule_sets_are_rejected():
    base = dict(
        name="x", starting_balance=50_000, nominal_size=50_000, max_loss_limit=2_000,
        trail_on=TrailOn.EOD_CLOSE, includes_unrealized=True, lock_at=LockAt.STARTING_BALANCE,
    )
    with pytest.raises(ValueError):
        AccountRules(**{**base, "max_loss_limit": 0})
    with pytest.raises(ValueError):
        AccountRules(**{**base, "starting_balance": -1})
    with pytest.raises(ValueError):
        AccountRules(**{**base, "consistency_max_day_share": 1.5})
    with pytest.raises(ValueError):
        # lock_at=PROFIT_TARGET without a target is unsatisfiable, not a default.
        AccountRules(**{**base, "lock_at": LockAt.PROFIT_TARGET})


def test_payout_path_validation():
    with pytest.raises(ValueError):
        PayoutPath(kind=PayoutPathKind.STANDARD, name="bad", min_winning_days=0)
    with pytest.raises(ValueError):
        PayoutPath(kind=PayoutPathKind.CONSISTENCY, name="bad", min_trading_days=0)


def test_with_preserves_vintage_and_replaces_only_named_fields():
    tweaked = TOPSTEP_FUNDED_150K.with_(personal_daily_stop=300.0)
    assert tweaked.personal_daily_stop == 300.0
    assert tweaked.max_loss_limit == TOPSTEP_FUNDED_150K.max_loss_limit
    assert tweaked.rules_as_of == TOPSTEP_FUNDED_150K.rules_as_of
    assert TOPSTEP_FUNDED_150K.personal_daily_stop is None  # original untouched
