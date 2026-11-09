"""EXP-111: evaluate the registered conditions from a finished
replay ledger. ABRW passes if (i) profit >= replay A, or (ii) max
DD shallower than replay A AND annual/DD above replay A.
Check 1 (replay A within +/-5% of the scaled backtest A,
+JPY 832,137) is reported for the record; by the known
forward-runs-hotter pattern it is expected to fail and is not
the arbiter."""
import json
import sys
from pathlib import Path

import pandas as pd

BUDGET = 400_000
NAMES = ("S", "A", "ABRW")
NEW = ("ABRW",)
A_SCALED = 832_137


def stats(v: pd.Series) -> dict:
    years = (v.index[-1] - v.index[0]).days / 365.25
    ann = (v.iloc[-1] / BUDGET) ** (1 / years) - 1
    dd = float((v / v.cummax() - 1).min())
    return {"profit": round(float(v.iloc[-1] - BUDGET)),
            "annual_pct": round(ann * 100, 2),
            "max_dd_pct": round(dd * 100, 2),
            "annual_over_dd": round(ann / abs(dd), 3) if dd < 0 else None}


led = pd.read_csv(Path(sys.argv[1]) / "ledger.csv", parse_dates=["date"])
out = {n: stats(led[led.portfolio == n].set_index("date")["value"]) for n in NAMES}
a = out["A"]
checks = {}
for n in NEW:
    r = out[n]
    i = r["profit"] >= a["profit"]
    ii = r["max_dd_pct"] > a["max_dd_pct"] and (r["annual_over_dd"] or -9) > (a["annual_over_dd"] or -9)
    checks[n] = {"i_profit_ge_A": bool(i), "ii_dd_shallower_and_ratio_above_A": bool(ii),
                 "grounds_to_continue": bool(i or ii)}
print(json.dumps({"replay": out, "checks": checks,
                  "check1_A_within_5pct_of_scaled_backtest":
                      abs(a["profit"] - A_SCALED) <= 0.05 * A_SCALED},
                 ensure_ascii=False, indent=1))
