"""EXP-011: replay the EXP-004 forward engine over a historical window.

Purpose (docs/experiments/EXP-011_PLAN.md): verify that the forward
implementation of EXP-010 variant A (and of S) behaves the way the
EXP-009/EXP-010 backtests say it should, BEFORE relying on months of
live paper trading. This is an implementation check, not a new
profitability test.

How it works:
  - imports exp004_forward as F4 and points F4.FWD at a scratch dir
    (forward_replay/), so the live forward state is never touched;
  - seeds a fresh state (R, W, V long-only; S, A with shorts) and patches
    F4.START to the window start, F4.PORTFOLIOS to the replay set, and
    F4.next_trading_day to the next day present in the price data
    (forward/tse_holidays.txt only covers the live campaign's year);
  - steps every trading day from the last trading day before the window
    (so the first orders are decided exactly like a campaign starting on
    the window's first day) through the window end, slicing panels to a
    rolling ~560-day warmup so per-day signal computation stays fast;
  - patches F4.due_tranches to count trading days on the FULL price
    calendar: the stock implementation counts within the panel it is
    handed, which the rolling slice corrupts once the slice start passes
    START (first run: rotation degraded from 2023-07-19 — see Amendment 1
    in docs/experiments/EXP-011_PLAN.md). Semantics on a full-history
    panel (what the live `step` passes) are unchanged;
  - reports per-portfolio stats from the scratch ledger, using the same
    annualisation as EXP-009's stats() with the forward budget (¥400,000).

Excluded: M (needs the frozen LightGBM model + lightgbm, and a 2022-2026
replay would be in-sample for it) and L (its trap scores are point-in-time
artefacts that cannot be replayed without look-ahead).

Usage:
    python experiments/exp011_replay_forward.py
    # optional: python experiments/exp011_replay_forward.py 2022-01-04 2026-09-25

Requires data/free/prices to be populated (run
`python experiments/exp004_forward.py update-data` once if it is not).
Delete forward_replay/ before re-running.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp004_forward as F4  # noqa: E402
import free_data as FD  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCRATCH = ROOT / "forward_replay"
REPLAY_PORTFOLIOS = ("R", "W", "V", "S", "A")
WARMUP_DAYS = 560  # calendar days of panel history kept per step (covers every lookback used)


def seed_state(last_step: pd.Timestamp) -> dict:
    def long_only() -> dict:
        return {"tranches": [{"cash": F4.BUDGET / F4.N_TRANCHES, "holdings": {}}
                             for _ in range(F4.N_TRANCHES)], "pending": None}

    def long_short() -> dict:
        pf = long_only()
        pf["shorts"] = [{} for _ in range(F4.N_TRANCHES)]
        pf["realized"] = 0.0
        return pf

    state = {name: (long_short() if name in ("S", "A") else long_only())
             for name in REPLAY_PORTFOLIOS}
    state["last_step"] = str(last_step.date())
    return state


def stats(v: pd.Series) -> dict:
    """Same annualisation as exp009_long_short.stats, with the forward budget."""
    years = (v.index[-1] - v.index[0]).days / 365.25
    ann = (v.iloc[-1] / F4.BUDGET) ** (1 / years) - 1
    dd = float((v / v.cummax() - 1).min())
    return {"profit": round(float(v.iloc[-1] - F4.BUDGET)),
            "annual_pct": round(ann * 100, 2),
            "max_dd_pct": round(dd * 100, 2),
            "annual_over_dd": round(ann / abs(dd), 3) if dd < 0 else None}


def main(start: str, end: str) -> None:
    prices_dir = ROOT / "data" / "free" / "prices"
    if not prices_dir.exists() or len(list(prices_dir.glob("*.csv"))) < 100:
        raise SystemExit("data/free/prices is not populated; run "
                         "`python experiments/exp004_forward.py update-data` once first")
    if (SCRATCH / "state.json").exists():
        raise SystemExit(f"{SCRATCH} already holds a replay state; delete the folder to re-run")
    SCRATCH.mkdir(parents=True, exist_ok=True)

    topix_all, panel_all, fins = FD.load()
    all_dates = topix_all.index
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    pre_pos = int(all_dates.searchsorted(start_ts)) - 1
    if pre_pos < 1:
        raise SystemExit("not enough price history before the window start")
    pre = all_dates[pre_pos]  # first orders are decided on this day, executed at the window start
    days = [d for d in all_dates if pre <= d <= end_ts]
    if not days or days[-1] < end_ts:
        raise SystemExit("window end is beyond the price data")

    # --- patch the forward module to run the replay campaign in the scratch dir ---
    F4.FWD = SCRATCH
    F4.START = start_ts
    F4.PORTFOLIOS = REPLAY_PORTFOLIOS
    F4.next_trading_day = lambda after: all_dates[int(all_dates.searchsorted(after, side="right"))]
    # step_day builds rank["M"] unconditionally; M is excluded from the replay,
    # so stub its scorer (the frozen model needs lightgbm, absent here). The
    # stubbed ranking is never used: orders are generated only for PORTFOLIOS.
    F4.model_scores = lambda feats, ok, d: pd.Series(dtype=float)
    # due_tranches counts trading days since START within the panel it is
    # handed; the rolling 560-day slice below would freeze that count once
    # the slice start passes START (first run: tranches_due degraded from
    # 2023-07-19 — same tranche due for weeks, long empty stretches).
    # Count on the full price calendar instead; identical to the stock
    # function when the panel covers the full history, as in live `step`.
    def due_full_calendar(day, trading_days=None):
        if day < F4.START:
            return []
        i = int(all_dates.searchsorted(day)) - int(all_dates.searchsorted(F4.START))
        if i == 0:
            return list(range(F4.N_TRANCHES))
        return [(i % F4.HOLD_DAYS) // 2] if i % 2 == 0 else []

    F4.due_tranches = due_full_calendar
    assert F4.FWD != FD.FWD, "scratch dir must differ from the live forward dir"

    (SCRATCH / "state.json").write_text(
        json.dumps(seed_state(all_dates[pre_pos - 1]), ensure_ascii=False, indent=1) + "\n")

    for i, day in enumerate(days):
        state = F4.load_state()
        lo = day - pd.Timedelta(days=WARMUP_DAYS)
        F4.step_day(state,
                    topix_all.loc[lo:day],
                    {k: v.loc[lo:day] for k, v in panel_all.items()},
                    fins)
        if (i + 1) % 100 == 0:
            print(f"  replay {day.date()} ({i + 1}/{len(days)})", file=sys.stderr)

    led = pd.read_csv(SCRATCH / "ledger.csv", parse_dates=["date"])
    out = {}
    for name in REPLAY_PORTFOLIOS:
        r = led[led.portfolio == name].sort_values("date")
        s = pd.Series(r.value.to_numpy(), index=pd.DatetimeIndex(r.date))
        out[name] = stats(s)
    print(json.dumps({"window": [start, end], "budget": F4.BUDGET, "replay": out},
                     ensure_ascii=False))


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2022-01-04"
    b = sys.argv[2] if len(sys.argv) > 2 else "2026-09-25"
    main(a, b)
