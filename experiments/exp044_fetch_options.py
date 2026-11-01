"""EXP-044 data fetch: Nikkei 225 option sheets around gate triggers.

Pass 1 fetches each trigger day's full put chain and applies the
preregistered selection rule (earliest contract month with SQ >=
21 days out; long strike = highest strike <= 0.97 x underlying;
short strike = highest strike <= long - 500). Pass 2 fetches the
two chosen contracts' daily settlement prices from buy date to
last trading day. Output: selection.json + data/legs/<date>.json.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, "/home/hatch/workspace/exp044_push/experiments")
import exp003_rotation as E3
import exp038_jpy_gate as E38

spec = importlib.util.spec_from_file_location(
    "jq", "/home/hatch/workspace/custom-connectors/custom.jquants/bin/"
    "jquants_api.py")
jq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jq)

CACHE = Path("/home/hatch/workspace/cache/jquants_exp002")
FX = Path("/home/hatch/workspace/exp038_run/usdjpy.csv")
OUT = Path("/home/hatch/workspace/exp044_run")
FIELDS = ("Code", "Strike", "CM", "Settle", "Theo", "Vo", "OI",
          "LTD", "SQD", "UnderPx")


def fetch_day(date_str: str) -> list[dict]:
    d = jq.get_json("/v2/derivatives/bars/daily/options/225",
                    {"date": date_str})
    rows = d.get("data", [])
    while d.get("pagination_key"):
        d = jq.get_json("/v2/derivatives/bars/daily/options/225",
                        {"date": date_str,
                         "pagination_key": d["pagination_key"]})
        rows += d.get("data", [])
    return rows


def main() -> None:
    topix, panel, fins = E3.load(CACHE)
    dates = topix.index
    gate = E38.gate_schedule(dates, FX)
    triggers = [t for t in range(len(dates))
                if gate[t] and (t == 0 or not gate[t - 1])]
    trig_dates = [str(dates[t].date()) for t in triggers]
    print("triggers:", trig_dates)

    data_dir = OUT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    selection = []
    for td in trig_dates:
        fp = data_dir / f"chain_{td}.json"
        if fp.exists():
            rows = json.loads(fp.read_text())
        else:
            raw = fetch_day(td)
            rows = [{k: r.get(k) for k in FIELDS}
                    for r in raw if r.get("PCDiv") == "1"]
            fp.write_text(json.dumps(rows))
            time.sleep(0.3)
        buy = pd.Timestamp(td)
        under = float(rows[0]["UnderPx"])
        cms = {}
        for r in rows:
            if r.get("SQD"):
                cms.setdefault(r["CM"], r["SQD"])
        cands = sorted(
            (sqd, cm) for cm, sqd in cms.items()
            if pd.Timestamp(sqd) >= buy + pd.Timedelta(days=21))
        sqd, cm = cands[0]
        chain = sorted((r for r in rows if r["CM"] == cm),
                       key=lambda r: -float(r["Strike"]))
        long_leg = next(r for r in chain
                        if float(r["Strike"]) <= 0.97 * under)
        lk = float(long_leg["Strike"])
        short_leg = next(r for r in chain
                         if float(r["Strike"]) <= lk - 500)
        selection.append({
            "buy_date": td, "cm": cm, "sqd": sqd,
            "under": under,
            "long": {"code": long_leg["Code"], "strike": lk,
                     "settle": float(long_leg["Settle"])},
            "short": {"code": short_leg["Code"],
                      "strike": float(short_leg["Strike"]),
                      "settle": float(short_leg["Settle"])},
        })
        print("selected:", selection[-1])

    (OUT / "selection.json").write_text(json.dumps(selection,
                                                   indent=1))
    legs_dir = data_dir / "legs"
    legs_dir.mkdir(exist_ok=True)
    wanted = {}
    for sel in selection:
        wanted[sel["long"]["code"]] = sel
        wanted[sel["short"]["code"]] = sel
    for sel in selection:
        ltd = next(r["LTD"] for r in json.loads(
            (data_dir / f"chain_{sel['buy_date']}.json").read_text())
            if r["Code"] == sel["long"]["code"])
        days = [str(d.date()) for d in dates
                if sel["buy_date"] <= str(d.date()) <= ltd]
        for ds in days:
            fp = legs_dir / f"{ds}.json"
            if fp.exists():
                continue
            raw = fetch_day(ds)
            got = {r["Code"]: float(r["Settle"]) for r in raw
                   if r.get("Code") in wanted
                   and r.get("Settle") not in (None, "")}
            fp.write_text(json.dumps(got))
            time.sleep(0.3)
        print("window done:", sel["buy_date"], "->", ltd,
              f"({len(days)} days)")
    print("FETCH DONE")


if __name__ == "__main__":
    main()
