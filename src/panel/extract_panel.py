"""Read all bulletins in data/external/bulletins/, parse each, write panel rows.

Output:
    data/processed/panel_provincial_bulletins.csv     -- one row per (province, year)
        columns: province_code, province_name, year, source_url, html_path, sha8,
                 <variable> + <variable>_evidence + <variable>_pattern
    docs/county_panel_coverage_v2.md  -- gap analysis report

The provincial panel is merged into `data/processed/county_panel.csv` by
`merge_panel_into_county_skeleton.py`, which fills the provincial value into
every county within that province where county-level data is missing (with a
flag indicating "provincial fallback").
"""
from __future__ import annotations
import csv
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from parse_bulletin import extract, VARIABLE_RULES  # noqa: E402

PROJECT_ROOT = Path("/home/user/projects/epvr-replication")
EXT_DIR = PROJECT_ROOT / "data" / "external" / "bulletins"
MANIFEST = EXT_DIR / "manifest.jsonl"
PROCESSED = PROJECT_ROOT / "data" / "processed"
DOCS = PROJECT_ROOT / "docs"


def _load_manifest_index() -> dict:
    """Build {path: manifest_record}."""
    if not MANIFEST.exists():
        return {}
    out = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok" and r.get("path"):
            out[r["path"]] = r
    return out


def _text_from_html(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" "))


def _text_from_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except Exception:
        return ""
    try:
        with pdfplumber.open(str(path)) as pdf:
            chunks = []
            for page in pdf.pages[:80]:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                if t:
                    chunks.append(t)
            return re.sub(r"\s+", " ", "\n".join(chunks))
    except Exception:
        return ""


VARS = list(VARIABLE_RULES.keys())


def main(level: str = "province") -> int:
    idx = _load_manifest_index()
    print(f"manifest: {len(idx)} successful fetches")

    rows = []
    parsed_n = 0
    parsed_var_n = 0
    for path_rel, rec in idx.items():
        if rec.get("level") != level:
            continue
        p = PROJECT_ROOT / path_rel
        if not p.exists():
            continue
        if rec["kind"] == "html":
            text = _text_from_html(p)
        else:
            text = _text_from_pdf(p)
        if len(text) < 1000:
            continue
        # quick topicality filter
        if "国民经济和社会发展统计公报" not in text and "国民经济和社会发展" not in text:
            # still try to parse
            pass
        res = extract(text)
        if not res:
            continue
        parsed_n += 1
        parsed_var_n += len(res)
        row = {
            "geo_code": rec["geo_code"],
            "year": rec["year"],
            "source_url": rec["url"],
            "html_path": path_rel,
            "sha8": rec["sha8"],
        }
        for v in VARS:
            if v in res:
                row[v] = res[v]["value"]
                row[f"{v}_evidence"] = res[v]["evidence"][:200]
            else:
                row[v] = ""
                row[f"{v}_evidence"] = ""
        rows.append(row)

    # Dedup: take latest (highest variable count) per (geo, year)
    by_key: dict[tuple[str, int], dict] = {}
    for r in rows:
        k = (r["geo_code"], r["year"])
        cur = by_key.get(k)
        if cur is None:
            by_key[k] = r
        else:
            cur_n = sum(1 for v in VARS if cur.get(v) not in (None, ""))
            new_n = sum(1 for v in VARS if r.get(v) not in (None, ""))
            if new_n > cur_n:
                by_key[k] = r

    final = list(by_key.values())
    out_csv = PROCESSED / f"panel_{level}_bulletins.csv"
    fieldnames = ["geo_code", "year", "source_url", "html_path", "sha8"]
    for v in VARS:
        fieldnames.append(v)
        fieldnames.append(f"{v}_evidence")
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in final:
            w.writerow(r)
    print(f"extract_panel({level}): parsed {parsed_n} bulletins, {parsed_var_n} variable-extractions, {len(final)} unique (geo,year)")
    print(f"  -> {out_csv}")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="province", choices=["province", "prefecture", "county"])
    args = ap.parse_args()
    raise SystemExit(main(args.level))
