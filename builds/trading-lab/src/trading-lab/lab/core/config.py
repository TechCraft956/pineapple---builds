"""Lab configuration: paths, credentials, cost overrides, account defaults.

One loader, one search order, no module-level surprises:

1. explicit path passed to :func:`load_config`
2. ``$LAB_CONFIG``
3. ``<repo>/trading-lab/config/config.yaml``
4. built-in defaults

Secrets never live in the config file. ``LSE_API_KEY`` is read from the
environment (optionally seeded from a git-ignored ``.env``), and
:meth:`LabConfig.require_api_key` is the only place that raises about it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

__all__ = ["LabConfig", "load_config", "load_dotenv", "LAB_ROOT"]

LAB_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | str | None = None, *, override: bool = False) -> dict[str, str]:
    """Read ``KEY=value`` pairs from a ``.env`` file into ``os.environ``.

    Deliberately tiny: no interpolation, no export keyword, no quoting rules
    beyond stripping a single matched pair of quotes. Existing environment
    variables win unless ``override`` is set, so a shell export always beats a
    stale file.
    """
    p = Path(path) if path else LAB_ROOT / ".env"
    loaded: dict[str, str] = {}
    if not p.exists():
        return loaded
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        loaded[key] = val
        if override or key not in os.environ:
            os.environ[key] = val
    return loaded


@dataclass(slots=True)
class LabConfig:
    """Everything the lab needs to know that is not a strategy parameter."""

    root: Path = LAB_ROOT
    data_dir: Path = field(default_factory=lambda: LAB_ROOT / "data")
    results_dir: Path = field(default_factory=lambda: LAB_ROOT / "results")
    journal_dir: Path = field(default_factory=lambda: LAB_ROOT / "journal")

    # --- data source -----------------------------------------------------
    api_key_env: str = "LSE_API_KEY"
    default_timeframe: str = "1m"
    cache_format: str = "parquet"
    #: Refuse to re-download anything already cached unless explicitly forced.
    #: The free tier meters exports; caching is not an optimisation here, it is
    #: the difference between a working research loop and a throttled one.
    cache_first: bool = True
    max_live_symbols: int = 16

    # --- execution assumptions ------------------------------------------
    #: Per-symbol overrides applied on top of lab/core/instruments.py defaults.
    #: ``{"ES": {"commission_round_turn": 4.10, "default_slippage_ticks": 1.5}}``
    cost_overrides: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    #: When a bar's high and low both reach the stop and the target, assume the
    #: stop filled first unless finer-resolution bars are supplied. Turning this
    #: off makes every backtest a lie; it exists only so the pessimism can be
    #: measured, never so it can be switched away.
    pessimistic_intrabar: bool = True

    # --- account ---------------------------------------------------------
    account_size: int = 150_000
    account_type: str = "funded"  # "combine" | "funded" | "express_funded"

    # --- reproducibility -------------------------------------------------
    random_seed: int = 20260805

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.data_dir = Path(self.data_dir)
        self.results_dir = Path(self.results_dir)
        self.journal_dir = Path(self.journal_dir)

    # ---- paths ----------------------------------------------------------

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def cleaned_dir(self) -> Path:
        return self.data_dir / "cleaned"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "topstep_exports"

    def ensure_dirs(self) -> "LabConfig":
        for p in (self.raw_dir, self.cleaned_dir, self.exports_dir, self.results_dir, self.journal_dir):
            p.mkdir(parents=True, exist_ok=True)
        return self

    # ---- credentials ----------------------------------------------------

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None

    def require_api_key(self) -> str:
        key = self.api_key
        if not key:
            raise RuntimeError(
                f"{self.api_key_env} is not set. Get a free key at "
                "https://londonstrategicedge.com/data and export it:\n"
                f"    export {self.api_key_env}='...'\n"
                f"or put it in {self.root / '.env'} (git-ignored). "
                "Never commit it."
            )
        return key

    # ---- costs ----------------------------------------------------------

    def instrument(self, symbol: str):
        """Instrument spec with this config's cost overrides applied."""
        from lab.core.instruments import get_instrument  # local: avoid import cycle

        inst = get_instrument(symbol)
        override = self.cost_overrides.get(inst.symbol) or self.cost_overrides.get(symbol.upper())
        if override:
            inst = inst.with_costs(
                commission_round_turn=override.get("commission_round_turn"),
                default_slippage_ticks=override.get("default_slippage_ticks"),
            )
        return inst

    def with_(self, **kwargs: Any) -> "LabConfig":
        """Copy with fields replaced -- for sensitivity sweeps."""
        return replace(self, **kwargs)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        raise RuntimeError(
            f"{path} exists but PyYAML is not installed. `pip install pyyaml` "
            "or delete the file to fall back to built-in defaults."
        ) from None
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data


def load_config(path: Path | str | None = None, *, load_env: bool = True) -> LabConfig:
    """Build a :class:`LabConfig` from the first config file found.

    Unknown keys are rejected rather than ignored -- a typo'd
    ``comission_round_turn`` that silently does nothing is worse than a crash.
    """
    if load_env:
        load_dotenv()
    candidates = [
        Path(path) if path else None,
        Path(os.environ["LAB_CONFIG"]) if os.environ.get("LAB_CONFIG") else None,
        LAB_ROOT / "config" / "config.yaml",
    ]
    for cand in candidates:
        if cand and cand.exists():
            raw = _read_yaml(cand)
            known = {f for f in LabConfig.__slots__}
            unknown = set(raw) - known
            if unknown:
                raise ValueError(
                    f"{cand}: unknown config keys {sorted(unknown)}; "
                    f"valid keys are {sorted(known)}"
                )
            cfg = LabConfig(**raw)
            cfg.root = cfg.root if path is None else cfg.root
            return cfg
    return LabConfig()
