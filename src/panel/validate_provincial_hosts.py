"""Re-extract panel from manifest after filtering to PROVINCIAL hosts only.

Some discovered URLs are prefecture-level (e.g. tjj.zhengzhou.gov.cn,
tjj.sjz.gov.cn).  Their data values describe the prefecture, not the
province.  We accept a bulletin only if its host belongs to the
provincial-level pattern.
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
from _bulletin_common import MANIFEST  # noqa: E402

PROJECT_ROOT = Path("/home/user/projects/epvr-replication")
PROCESSED = PROJECT_ROOT / "data" / "processed"

# Allowed provincial-level host patterns.  Two formats:
# - exact host string
# - regex pattern (compiled)
ALLOWED_HOSTS_EXACT = {
    # national
    "www.stats.gov.cn",
    "www.ndrc.gov.cn",        # NDRC (national)
    "cif.mofcom.gov.cn",      # MOFCOM CIF (national directory of provincial bulletins)
    "www.neac.gov.cn",        # SEAC (国家民委), publishes provincial autonomy area bulletins
    # provincial portals (www.<prov>.gov.cn)
    "www.beijing.gov.cn", "www.tj.gov.cn", "www.hebei.gov.cn", "www.shanxi.gov.cn",
    "www.nmg.gov.cn",
    "www.ln.gov.cn", "www.jl.gov.cn", "www.hlj.gov.cn",
    "www.shanghai.gov.cn", "www.js.gov.cn", "www.zj.gov.cn", "www.ah.gov.cn",
    "www.fujian.gov.cn", "www.fj.gov.cn", "www.jiangxi.gov.cn", "www.shandong.gov.cn",
    "www.henan.gov.cn", "www.hubei.gov.cn", "www.hunan.gov.cn",
    "www.gd.gov.cn", "www.gxzf.gov.cn", "www.hainan.gov.cn",
    "www.cq.gov.cn", "www.sc.gov.cn", "www.guizhou.gov.cn", "www.yn.gov.cn",
    "www.xizang.gov.cn",
    "www.shaanxi.gov.cn", "www.gansu.gov.cn", "www.qinghai.gov.cn",
    "www.nx.gov.cn", "www.xinjiang.gov.cn",
    # provincial statistics bureaus (tjj.<prov>.gov.cn / stats.<prov>.gov.cn / tj.<prov>.gov.cn)
    "tjj.beijing.gov.cn",
    "stats.tj.gov.cn",
    "tjj.hebei.gov.cn",
    "tjj.shanxi.gov.cn",
    "tj.nmg.gov.cn",
    "tjj.ln.gov.cn", "tjj.jl.gov.cn", "tjj.hlj.gov.cn",
    "tjj.sh.gov.cn",
    "tj.jiangsu.gov.cn",
    "tjj.zj.gov.cn",
    "tjj.ah.gov.cn",
    "tjj.fujian.gov.cn",
    "tjj.jiangxi.gov.cn",
    "tjj.shandong.gov.cn",
    "tjj.henan.gov.cn",
    "tjj.hubei.gov.cn", "tjj.hunan.gov.cn",
    "stats.gd.gov.cn",
    "tjj.gxzf.gov.cn",
    "stats.hainan.gov.cn",
    "tjj.cq.gov.cn",
    "tjj.sc.gov.cn",
    "stjj.guizhou.gov.cn", "stats.yn.gov.cn",
    "tjj.xizang.gov.cn",
    "tjj.shaanxi.gov.cn", "tjj.gansu.gov.cn", "tjj.qinghai.gov.cn",
    "tj.nx.gov.cn", "nxdata.gov.cn",
    "tjj.xinjiang.gov.cn",
    # *zd.stats.gov.cn: provincial branch domains for national stats portal
    "tjzd.stats.gov.cn", "hnzd.stats.gov.cn", "hnzdhd.stats.gov.cn",
    "sxzd.stats.gov.cn", "gdzd.stats.gov.cn", "zjzd.stats.gov.cn",
    "xjzd.stats.gov.cn", "jszd.stats.gov.cn", "ahzd.stats.gov.cn",
    "fjzd.stats.gov.cn", "jlzd.stats.gov.cn",
    "lnzd.stats.gov.cn", "hbzd.stats.gov.cn",
    "scsd.stats.gov.cn",
    "jxzd.stats.gov.cn",
    "qhzd.stats.gov.cn", "nxzd.stats.gov.cn", "gxzd.stats.gov.cn",
    "sczd.stats.gov.cn", "yunzd.stats.gov.cn", "shaanxizd.stats.gov.cn",
    "gzzd.stats.gov.cn", "hbeizd.stats.gov.cn",
    # provincial CMS / OSS hosts that mirror the bulletin
    "zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn",
    "www.yn.gov.cn",
    # provincial natural-resources bureau or other provincial bureau that hosts
    # the bulletin as part of its 信息公开 page:
    "nmt.nmg.gov.cn",  # 内蒙古自治区自然资源厅
}

# Patterns that we ALWAYS trust as provincial.
# *zd.stats.gov.cn and *zdhd.stats.gov.cn are NBS provincial branches; the
# prefix is the provincial abbreviation (zj, hn, sx, jl, …), not a
# prefecture name.  So these are safe to auto-accept.
ALLOWED_AUTO_PATTERNS = [
    re.compile(r"^[a-z]+zd\.stats\.gov\.cn$"),
    re.compile(r"^[a-z]+zdhd\.stats\.gov\.cn$"),
]


def is_provincial_host(host: str) -> bool:
    host = (host or "").lower()
    if host in ALLOWED_HOSTS_EXACT:
        return True
    for pat in ALLOWED_AUTO_PATTERNS:
        if pat.match(host):
            return True
    return False


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
    # Build manifest index keyed by path; for province level, filter by host.
    if not MANIFEST.exists():
        print("no manifest")
        return 1
    records: list[dict] = []
    rejected_hosts: dict[str, int] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") != "ok" or r.get("level") != level:
            continue
        if level == "province" and not is_provincial_host(r["domain"]):
            rejected_hosts[r["domain"]] = rejected_hosts.get(r["domain"], 0) + 1
            continue
        records.append(r)
    print(f"manifest ok records: {len(records)} (filter: provincial host)")
    if rejected_hosts:
        print("rejected hosts (sample):", sorted(rejected_hosts.items(), key=lambda x: -x[1])[:15])

    rows = []
    for r in records:
        p = PROJECT_ROOT / r["path"]
        if not p.exists():
            continue
        if r["kind"] == "html":
            text = _text_from_html(p)
        else:
            text = _text_from_pdf(p)
        if len(text) < 1000:
            continue
        res = extract(text)
        if not res:
            continue
        row = {
            "geo_code": r["geo_code"],
            "year": int(r["year"]),
            "source_url": r["url"],
            "source_host": r["domain"],
            "html_path": r["path"],
            "sha8": r["sha8"],
        }
        for v in VARS:
            if v in res:
                row[v] = res[v]["value"]
                row[f"{v}_evidence"] = res[v]["evidence"][:200]
            else:
                row[v] = ""
                row[f"{v}_evidence"] = ""
        rows.append(row)

    # Dedup keeping the one with most variables filled.
    by_key: dict[tuple[str, int], dict] = {}
    for r in rows:
        k = (r["geo_code"], r["year"])
        cur = by_key.get(k)
        if cur is None:
            by_key[k] = r
            continue
        cur_n = sum(1 for v in VARS if cur.get(v) not in (None, ""))
        new_n = sum(1 for v in VARS if r.get(v) not in (None, ""))
        if new_n > cur_n:
            by_key[k] = r

    final = list(by_key.values())
    out_csv = PROCESSED / f"panel_{level}_bulletins.csv"
    fieldnames = ["geo_code", "year", "source_url", "source_host", "html_path", "sha8"]
    for v in VARS:
        fieldnames.append(v)
        fieldnames.append(f"{v}_evidence")
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in final:
            w.writerow(r)
    print(f"validate_provincial_hosts({level}): kept {len(final)} unique (geo,year) from {len(rows)} parses")
    print(f"  -> {out_csv}")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="province")
    args = ap.parse_args()
    raise SystemExit(main(args.level))
