"""EXP-099: replay the forward engine (ABG addition) over
2022-01-04..2026-09-25 and judge ABG by the registered relative
conditions of EXP-099_PLAN: (i) replay profit >= replay A, or
(ii) replay DD shallower than A AND annual/DD above A.

Follows the EXP-011/047 harness pattern: import exp004_forward
as F4, point F4.FWD at a scratch dir (the live forward state is
never touched), patch START / PORTFOLIOS / next_trading_day /
due_tranches (full-calendar counting), seed a fresh state, and
step every trading day with a rolling ~560-day warmup slice. The
scratch dir must contain names.json, an orders/ dir, and the feed
CSVs (broad_events.csv WITH the EXP-099 strength column,
large_events.csv, voluntary_events.csv) covering the window.

Check 1 of the EXP-055 plan (replay A within +/-5% of the scaled
backtest A, +JPY 832,137) is printed for the record; by the known
forward-runs-hotter pattern it is expected to fail and is not the
arbiter. The registered arbiter is conditions (i)/(ii), evaluated
by exp099_replay_check.py.

Usage:
    python experiments/exp099_replay_forward.py <scratch_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp004_forward as F4
import free_data as FD

REPLAY_PORTFOLIOS = ("S", "A", "AB", "ABG")
START = pd.Timestamp("2022-01-04")
END = pd.Timestamp("2026-09-25")
WARMUP_DAYS = 560
A_SCALED = 832_137


def seed_state(last_step: pd.Timestamp) -> dict:
    def long_short() -> dict:
        return {"tranches": [{"cash": F4.BUDGET / F4.N_TRANCHES,
                              "holdings": {}}
                             for _ in range(F4.N_TRANCHES)],
                "shorts": [{} for _ in range(F4.N_TRANCHES)],
                "realized": 0.0, "pending": None}

    state = {name: long_short() for name in REPLAY_PORTFOLIOS}
    state["last_step"] = str(last_step.date())
    return state


def stats(v: pd.Series) -> dict:
    years = (v.index[-1] - v.index[0]).days / 365.25
    ann = (v.iloc[-1] / F4.BUDGET) ** (1 / years) - 1
    dd = float((v / v.cummax() - 1).min())
    return {"profit": round(float(v.iloc[-1] - F4.BUDGET)),
            "annual_pct": round(ann * 100, 2),
            "max_dd_pct": round(dd * 100, 2),
            "annual_over_dd": round(ann / abs(dd), 3) if dd < 0 else None}


def main(scratch: Path) -> None:
    topix_all, panel_all, fins = FD.load()
    days = [d for d in topix_all.index if START <= d <= END]
    prev = topix_all.index[topix_all.index < START][-1]

    F4.FWD = scratch
    F4.START = START
    F4.PORTFOLIOS = REPLAY_PORTFOLIOS

    full = topix_all.index

    def next_td(after: pd.Timestamp) -> pd.Timestamp:
        nxt = full[full > after]
        return nxt[0] if len(nxt) else after + pd.Timedelta(days=1)

    def due_full(day: pd.Timestamp, _td) -> list[int]:
        if day < START:
            return []
        i = int(((full >= START) & (full < day)).sum())
        if i == 0:
            return list(range(F4.N_TRANCHES))
        return [(i % F4.HOLD_DAYS) // 2] if i % 2 == 0 else []

    F4.next_trading_day = next_td
    F4.due_tranches = due_full

    if (scratch / "state.json").exists():
        state = json.loads((scratch / "state.json").read_text())
        done = pd.Timestamp(state["last_step"])
        days = [d for d in days if d > done]
        print(f"resuming after {done.date()}: {len(days)} days left")
    else:
        state = seed_state(prev)
    for day in days:
        lo = day - pd.Timedelta(days=WARMUP_DAYS)
        F4.step_day(state, topix_all.loc[lo:day],
                    {k: v.loc[lo:day] for k, v in panel_all.items()},
                    fins)
        state = json.loads((scratch / "state.json").read_text())
    led = pd.read_csv(scratch / "ledger.csv", parse_dates=["date"])
    out = {}
    for name in REPLAY_PORTFOLIOS:
        s = led[led.portfolio == name].set_index("date")["value"]
        out[name] = stats(s)
    print(json.dumps({"replay": out,
                      "check1_A_within_5pct_of_scaled_backtest":
                          abs(out["A"]["profit"] - A_SCALED) <= 0.05 * A_SCALED},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
