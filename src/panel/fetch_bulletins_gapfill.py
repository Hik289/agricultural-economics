"""Second-pass gap fill: find provinces × years we're missing and try alternate
URL sources via Brave with broader queries.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bulletin_common import fetch, brave_search, MANIFEST  # noqa: E402

PROV_NAMES: dict[str, str] = {
    "11": "北京", "12": "天津", "13": "河北", "14": "山西", "15": "内蒙古",
    "21": "辽宁", "22": "吉林", "23": "黑龙江", "31": "上海", "32": "江苏",
    "33": "浙江", "34": "安徽", "35": "福建", "36": "江西", "37": "山东",
    "41": "河南", "42": "湖北", "43": "湖南", "44": "广东", "45": "广西",
    "46": "海南", "50": "重庆", "51": "四川", "52": "贵州", "53": "云南",
    "54": "西藏", "61": "陕西", "62": "甘肃", "63": "青海", "64": "宁夏",
    "65": "新疆",
}


def _have_ok(geo_code: str, year: int) -> bool:
    if not MANIFEST.exists():
        return False
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok" and r.get("level") == "province" and r.get("geo_code") == geo_code and r.get("year") == year:
            return True
    return False


def _candidate_urls(prov_name: str, year: int) -> list[str]:
    """Run multiple Brave queries and collect candidate URLs."""
    queries = []
    suffix = "省" if prov_name not in {"北京", "上海", "天津", "重庆", "内蒙古", "广西", "西藏", "宁夏", "新疆"} else ("市" if prov_name in {"北京", "上海", "天津", "重庆"} else "自治区")
    base = prov_name + suffix
    queries.append(f"site:gov.cn {base} {year}年 国民经济和社会发展统计公报")
    queries.append(f"{base} {year}年 国民经济和社会发展统计公报 全省 城镇居民人均可支配收入")
    queries.append(f"{base} {year}年 国民经济和社会发展统计公报 农村居民")
    queries.append(f"\"{year}年{base}国民经济和社会发展统计公报\"")
    urls: list[str] = []
    seen = set()
    for q in queries:
        for r in brave_search(q, count=10):
            u = r["url"]; host = r["host"]
            if not u or u in seen:
                continue
            seen.add(u)
            if not host.endswith(".gov.cn"):
                continue
            if "图解" in u or "/jdwd/" in u or "解读" in u:
                continue
            urls.append(u)
    return urls


def main() -> int:
    YEARS = list(range(2015, 2025))
    missing = [(c, y) for c in PROV_NAMES for y in YEARS if not _have_ok(c, y)]
    print(f"missing pairs: {len(missing)}", flush=True)

    fetched = 0
    for code, year in missing:
        cands = _candidate_urls(PROV_NAMES[code], year)
        print(f"[{code}/{year}] {len(cands)} candidates", flush=True)
        for u in cands[:6]:  # try up to 6 candidates per pair
            rec = fetch(u, "province", code, year, kind="html")
            if rec:
                fetched += 1
                print(f"   ok -> {rec['path']}", flush=True)
                break
        else:
            print(f"   all candidates failed", flush=True)
    print(f"\nDONE gapfill fetched={fetched}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
