"""Instrument specifications: tick size, tick value, session clock, costs.

Every dollar figure the lab produces flows through these numbers, so they are
the highest-leverage thing to get right. The values below are the CME contract
specs as published for the listed products; the *cost* fields
(``commission_round_turn``, ``default_slippage_ticks``) are deliberately
conservative research defaults, not quotes from any particular broker or prop
firm. Override them from ``config/config.yaml`` with your own fills once you
have 50+ real ones to measure -- see ``lab.journal`` for the measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterator

__all__ = ["Instrument", "INSTRUMENTS", "get_instrument", "known_symbols"]


@dataclass(frozen=True, slots=True)
class Instrument:
    """Contract spec plus the research cost assumptions attached to it.

    Attributes
    ----------
    symbol:
        Lab-canonical symbol. Data-source symbols are mapped onto this in
        :mod:`lab.data.symbols` -- never hardcode a vendor symbol elsewhere.
    tick_size:
        Minimum price increment.
    tick_value:
        Dollar value of one tick for one contract.
    commission_round_turn:
        All-in per-contract cost of opening *and* closing one contract,
        including exchange, clearing and platform fees.
    default_slippage_ticks:
        Ticks of adverse slippage applied to *each* side of a market or stop
        order. Limit entries fill at their price or not at all, but their stops
        still pay this.
    session_tz:
        IANA zone the instrument's session windows are expressed in. CME
        products are quoted against ``America/Chicago`` so DST is handled by the
        exchange clock rather than by hand.
    rth_open / rth_close:
        Regular trading hours in ``session_tz``, ``HH:MM``.
    """

    symbol: str
    name: str
    exchange: str
    tick_size: float
    tick_value: float
    commission_round_turn: float
    default_slippage_ticks: float
    session_tz: str = "America/Chicago"
    rth_open: str = "08:30"
    rth_close: str = "15:00"
    currency: str = "USD"
    micro_of: str | None = None

    # ---- conversions -----------------------------------------------------

    @property
    def point_value(self) -> float:
        """Dollar value of a one-unit move in price for one contract."""
        return self.tick_value / self.tick_size

    def ticks(self, price_distance: float) -> float:
        """Convert a price distance to ticks."""
        return price_distance / self.tick_size

    def dollars(self, price_distance: float, qty: float = 1.0) -> float:
        """Convert a price distance to dollars for ``qty`` contracts."""
        return price_distance * self.point_value * qty

    def price_from_dollars(self, dollars: float, qty: float = 1.0) -> float:
        """Inverse of :meth:`dollars`."""
        return dollars / (self.point_value * qty)

    def round_to_tick(self, price: float, mode: str = "nearest") -> float:
        """Snap a price to the instrument's tick grid.

        ``mode`` is ``"nearest"``, ``"up"`` or ``"down"``. Rounding is done in
        integer tick space to avoid float drift accumulating over a backtest.
        """
        ticks = price / self.tick_size
        if mode == "nearest":
            n = round(ticks)
        elif mode == "up":
            n = -((-ticks) // 1)
        elif mode == "down":
            n = ticks // 1
        else:
            raise ValueError(f"unknown rounding mode {mode!r}")
        return round(n * self.tick_size, 10)

    def slip(self, price: float, direction: int, ticks: float | None = None) -> float:
        """Apply adverse slippage to a fill price.

        ``direction`` is the direction of the *order* (+1 buy, -1 sell): a buy
        fills higher than intended, a sell fills lower.
        """
        t = self.default_slippage_ticks if ticks is None else ticks
        return self.round_to_tick(price + direction * t * self.tick_size)

    def with_costs(
        self,
        commission_round_turn: float | None = None,
        default_slippage_ticks: float | None = None,
    ) -> "Instrument":
        """Return a copy with different cost assumptions (for sensitivity runs)."""
        return replace(
            self,
            commission_round_turn=(
                self.commission_round_turn
                if commission_round_turn is None
                else commission_round_turn
            ),
            default_slippage_ticks=(
                self.default_slippage_ticks
                if default_slippage_ticks is None
                else default_slippage_ticks
            ),
        )


# Contract specs are exchange-published. Commission/slippage are research
# defaults -- replace them with measured values from your own fills.
INSTRUMENTS: dict[str, Instrument] = {
    "ES": Instrument(
        symbol="ES", name="E-mini S&P 500", exchange="CME",
        tick_size=0.25, tick_value=12.50,
        commission_round_turn=4.00, default_slippage_ticks=1.0,
        rth_open="08:30", rth_close="15:00",
    ),
    "MES": Instrument(
        symbol="MES", name="Micro E-mini S&P 500", exchange="CME",
        tick_size=0.25, tick_value=1.25,
        commission_round_turn=1.00, default_slippage_ticks=1.0,
        rth_open="08:30", rth_close="15:00", micro_of="ES",
    ),
    "NQ": Instrument(
        symbol="NQ", name="E-mini Nasdaq 100", exchange="CME",
        tick_size=0.25, tick_value=5.00,
        commission_round_turn=4.00, default_slippage_ticks=1.0,
        rth_open="08:30", rth_close="15:00",
    ),
    "MNQ": Instrument(
        symbol="MNQ", name="Micro E-mini Nasdaq 100", exchange="CME",
        tick_size=0.25, tick_value=0.50,
        commission_round_turn=1.00, default_slippage_ticks=1.0,
        rth_open="08:30", rth_close="15:00", micro_of="NQ",
    ),
    "CL": Instrument(
        symbol="CL", name="Crude Oil", exchange="NYMEX",
        tick_size=0.01, tick_value=10.00,
        commission_round_turn=4.40, default_slippage_ticks=1.0,
        rth_open="08:00", rth_close="13:30",
    ),
    "MCL": Instrument(
        symbol="MCL", name="Micro Crude Oil", exchange="NYMEX",
        tick_size=0.01, tick_value=1.00,
        commission_round_turn=1.20, default_slippage_ticks=1.0,
        rth_open="08:00", rth_close="13:30", micro_of="CL",
    ),
    "GC": Instrument(
        symbol="GC", name="Gold", exchange="COMEX",
        tick_size=0.10, tick_value=10.00,
        commission_round_turn=4.40, default_slippage_ticks=1.0,
        rth_open="07:20", rth_close="12:30",
    ),
    "MGC": Instrument(
        symbol="MGC", name="Micro Gold", exchange="COMEX",
        tick_size=0.10, tick_value=1.00,
        commission_round_turn=1.20, default_slippage_ticks=1.0,
        rth_open="07:20", rth_close="12:30", micro_of="GC",
    ),
}


def get_instrument(symbol: str) -> Instrument:
    """Look up an instrument, case-insensitively, with a helpful error."""
    key = symbol.strip().upper()
    if key in INSTRUMENTS:
        return INSTRUMENTS[key]
    # Tolerate vendor decorations like "ES1!", "ES=F", "CL_CONT".
    for suffix in ("1!", "=F", "_CONT", "-CONT", ".C"):
        if key.endswith(suffix):
            stem = key[: -len(suffix)]
            if stem in INSTRUMENTS:
                return INSTRUMENTS[stem]
    raise KeyError(
        f"unknown instrument {symbol!r}; known: {', '.join(sorted(INSTRUMENTS))}. "
        "Add it to lab/core/instruments.py with exchange-published tick specs."
    )


def known_symbols() -> Iterator[str]:
    yield from sorted(INSTRUMENTS)
