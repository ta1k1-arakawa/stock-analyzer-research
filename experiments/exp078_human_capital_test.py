"""Kill test for round-8 idea 6: human-capital growth.

Formation 2025-07-01. Signal = mean pct-rank of (average-salary 3y
CAGR, consolidated headcount 3y growth). Kill if coverage (both-wave
salary) < 80% of the 306, or top-minus-bottom quintile 12m TOPIX-
excess spread <= 0, or Spearman(signal, forecast-ROE rank) > 0.5.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent))
import exp003_rotation as E3

OUT = Path("/home/hatch/workspace/exp079_kill")
CACHE = Path("/home/hatch/workspace/cache/jquants_exp002")
FORM = pd.Timestamp("2025-07-01")
END = pd.Timestamp("2026-06-30")


def main() -> None:
    waves = json.loads((OUT / "waves.json").read_text())
    w22, w25 = waves["w2022"], waves["w2025"]
    topix, panel, fins = E3.load(CACHE)
    dates = topix.index
    close = panel["C"].ffill()
    codes = list(close.columns)

    sal_cov = [c for c in codes if w22.get(c, {}).get("salary")
               and w25.get(c, {}).get("salary")
               and w25[c].get("filed", "9999") <= "2025-06-30"]
    print(f"(a) both-wave salary coverage: {len(sal_cov)}/306 = {len(sal_cov) / 306:.0%}"
          f" -> {'KILL' if len(sal_cov) / 306 < 0.80 else 'pass'}")

    rows = {}
    for c in sal_cov:
        a, b = w22[c], w25[c]
        yrs = (pd.Timestamp(b["period_end"]) - pd.Timestamp(a["period_end"])).days / 365.25
        if yrs < 2.0 or not a["salary"] or not b["salary"]:
            continue
        cagr = (b["salary"] / a["salary"]) ** (1 / yrs) - 1
        hc = None
        if b.get("hc_now") and b.get("hc_p3"):
            hc = b["hc_now"] / b["hc_p3"] - 1
        rows[c] = {"cagr": cagr, "hc": hc}
    sig = pd.DataFrame(rows).T.dropna()
    print(f"signal names (salary CAGR + headcount growth): {len(sig)}")
    signal = (sig["cagr"].rank(pct=True) + sig["hc"].rank(pct=True)) / 2

    i0 = int(dates.searchsorted(FORM, side="right")) - 1
    i1 = int(dates.searchsorted(END, side="right")) - 1
    fwd = close.iloc[i1] / close.iloc[i0] - 1.0
    tfwd = float(topix["C"].iloc[i1] / topix["C"].iloc[i0] - 1.0)
    exc = (fwd - tfwd).reindex(signal.index).dropna()
    s = signal.reindex(exc.index)
    q = pd.qcut(s, 5, labels=False)
    top = exc[q == 4].mean()
    bot = exc[q == 0].mean()
    spread = float(top - bot)
    print(f"(b) quintile 12m excess: top {top * 100:+.2f}% bottom {bot * 100:+.2f}% "
          f"spread {spread * 100:+.2f}pt -> {'KILL' if spread <= 0 else 'pass'}")

    prof = E3.signals(panel, fins, dates)["profit_only"]
    proe = prof.iloc[i0].reindex(s.index)
    both = pd.concat([s, proe], axis=1).dropna()
    rho = spearmanr(both.iloc[:, 0], both.iloc[:, 1]).statistic
    print(f"(c) Spearman(signal, forecast ROE rank): {rho:+.3f} (n={len(both)})"
          f" -> {'KILL' if rho > 0.5 else 'pass'}")
    killed = (len(sal_cov) / 306 < 0.80) or spread <= 0 or rho > 0.5
    print("VERDICT:", "KILLED" if killed else "SURVIVES - eligible for preregistration draft")


if __name__ == "__main__":
    main()
