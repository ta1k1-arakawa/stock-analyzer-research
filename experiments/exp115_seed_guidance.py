"""EXP-115: build the seed for forward/guidance_events.csv from the
EXP-002 cache fins (~/workspace/cache/jquants_exp002), under the
EXP-114 definition exactly.

The CSV stores the RAW FY rows (every J-Quants fins record with
CurPerType == "FY", in cache order): date, code, fy_end, np, nxfnp,
disc_no. The forward engine's guidance_flags() re-derives the
EXP-114 disclosures from these raw rows at run time (per
(code, CurFYEn): last DiscDate row carrying NP defines the
disclosure; NxFNp falls back to the latest NxFNp-carrying row of
the group; flag = NxFNp/NP - 1 <= -0.10 with NP, NxFNp both
positive and non-missing), so the registered re-judgement rule and
any late corrections stay reproducible from the feed alone.

Verification printed at the end rebuilds the disclosures with
EXP-114's own build_fy_frame (imported from the EXP-114 run dir)
and checks the gate counts: raw FY rows 4,910; deduped disclosures
2,925; NxFNp non-missing after fallback 2,565; judgeable 2,329;
flag events 671 (FH 311 / SH 360); flag codes 238.

Usage: python exp115_seed_guidance.py <out_csv>
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path.home() / "workspace" / "exp114_run"))
import exp003_rotation as E3  # noqa: E402
import exp114_joint as E114  # noqa: E402

CACHE = Path.home() / "workspace" / "cache" / "jquants_exp002"


def main(out_csv: Path) -> None:
    _, _, fins = E3.load(CACHE)
    rows = []
    for code, recs in fins.items():
        for r in recs:
            if r.get("CurPerType") != "FY":
                continue
            rows.append({"date": r.get("DiscDate", ""),
                         "code": str(code)[:4],
                         "fy_end": r.get("CurFYEn", ""),
                         "np": r.get("NP", ""),
                         "nxfnp": r.get("NxFNp", ""),
                         "disc_no": r.get("DiscNo", "")})
    print(f"raw FY rows: {len(rows)} (gate: 4910)")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "code", "fy_end",
                                          "np", "nxfnp", "disc_no"])
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r[k] is None else str(r[k]))
                        for k in r})

    fy = E114.build_fy_frame(fins)
    fl = fy[fy["flag"]]
    chk = {
        "fy_rows_raw": int(fy.attrs["n_raw"]),
        "deduped_disclosures": int(len(fy)),
        "nxfnp_nonnull_after_fill": int(fy["NxFNp"].notna().sum()),
        "judgeable": int(fy["nx_growth"].notna().sum()),
        "flag_events": int(fy["flag"].sum()),
        "flag_FH": int((fl["disc"] <= "2021-12-30").sum()),
        "flag_SH": int((fl["disc"] >= "2022-01-04").sum()),
        "flag_codes": int(fl["code"].nunique()),
        "flag_date_min": str(fl["disc"].min()),
        "flag_date_max": str(fl["disc"].max()),
        "disc_date_min": str(fy["disc"].min()),
        "disc_date_max": str(fy["disc"].max()),
    }
    print(chk)
    assert chk["fy_rows_raw"] == 4910, chk
    assert chk["deduped_disclosures"] == 2925, chk
    assert chk["nxfnp_nonnull_after_fill"] == 2565, chk
    assert chk["judgeable"] == 2329, chk
    assert chk["flag_events"] == 671, chk
    assert chk["flag_FH"] == 311 and chk["flag_SH"] == 360, chk
    assert chk["flag_codes"] == 238, chk
    print("seed OK:", out_csv)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
