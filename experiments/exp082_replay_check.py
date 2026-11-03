"""EXP-082: evaluate the registered conditions from a finished
replay ledger (the replay itself is exp082_replay_forward.py run
with REPLAY_PORTFOLIOS = S/A/A75/AF/A75F/AV/AV75)."""
import json
import sys
from pathlib import Path

import pandas as pd

BUDGET = 400_000


def stats(v: pd.Series) -> dict:
    years = (v.index[-1] - v.index[0]).days / 365.25
    ann = (v.iloc[-1] / BUDGET) ** (1 / years) - 1
    dd = float((v / v.cummax() - 1).min())
    return {"profit": round(float(v.iloc[-1] - BUDGET)),
            "annual_pct": round(ann * 100, 2),
            "max_dd_pct": round(dd * 100, 2),
            "annual_over_dd": round(ann / abs(dd), 3) if dd < 0 else None}


led = pd.read_csv(Path(sys.argv[1]) / "ledger.csv", parse_dates=["date"])
out = {}
for name in ("S", "A", "A75", "AF", "A75F", "AV", "AV75"):
    out[name] = stats(led[led.portfolio == name].set_index("date")["value"])
a, af, a75 = out["A"], out["AF"], out["A75"]
f, v, v75 = out["A75F"], out["AV"], out["AV75"]
checks = {
    "A75F_conditions": {
        "i_dd_shallower_than_A_A75_AF":
            f["max_dd_pct"] > max(a["max_dd_pct"], a75["max_dd_pct"], af["max_dd_pct"]),
        "ii_profit_ge_90pct_of_A": f["profit"] >= 0.90 * a["profit"],
        "iii_ratio_above_A": (f["annual_over_dd"] or -9) > (a["annual_over_dd"] or -9),
        "KILL_dd_not_shallower_than_AF": not (f["max_dd_pct"] > af["max_dd_pct"]),
    },
    "AV75_conditions": {
        "i_ratio_ge_AV_ratio": (v75["profit"] / a["profit"]) >= (v["profit"] / a["profit"]),
        "ii_dd_shallower_than_A": v75["max_dd_pct"] > a["max_dd_pct"],
        "KILL_ratio_below_1": (v75["profit"] / a["profit"]) < 1.00,
    },
    "ratios": {"AV_over_A": round(v["profit"] / a["profit"], 4),
               "AV75_over_A": round(v75["profit"] / a["profit"], 4),
               "A75F_over_A": round(f["profit"] / a["profit"], 4)},
}
def to_plain(x):
    if isinstance(x, dict):
        return {k: to_plain(v) for k, v in x.items()}
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


print(json.dumps(to_plain({"replay": out, "checks": checks}), ensure_ascii=False, indent=1))
