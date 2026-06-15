"""Targeted gap-fill for 5 high-priority EPVR-rich provinces still missing."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bulletin_common import fetch, brave_search

PRIORITY = {
    "15": "内蒙古自治区",
    "36": "江西省",
    "51": "四川省",
    "52": "贵州省",
    "61": "陕西省",
    "33": "浙江省",
    "44": "广东省",
    "32": "江苏省",
    "53": "云南省",
    "45": "广西壮族自治区",
}


def main():
    YEARS = list(range(2015, 2025))
    saved = 0
    for code, name in PRIORITY.items():
        for y in YEARS:
            queries = [
                f'"{y}年{name}国民经济和社会发展统计公报"',
                f"site:gov.cn {name[:2]} {y}年 国民经济 统计公报 全省 城镇 农村 可支配收入",
                f"site:stats.gov.cn {name[:2]} {y}年 统计公报",
            ]
            urls = []
            seen = set()
            for q in queries:
                for r in brave_search(q, count=10):
                    u = r["url"]; host = r["host"]
                    if not u or u in seen: continue
                    seen.add(u)
                    if not host.endswith(".gov.cn"): continue
                    bad = [
                        "tjj.zhengzhou", "tjj.sjz", "tjj.ankang", "tjj.nanjing",
                        "tjj.shenyang", "tjj.xam", "tjj.dwq", "www.beibei",
                        "www.zhanjiang", "www.czq", "www.baoshan",
                        "www.lvliang", "www.jcgov", "tjj.nc", "tjj.huizhou",
                        "tjj.sz.gov.cn",
                    ]
                    if any(b in host for b in bad):
                        continue
                    urls.append(u)
            print(f"[{code}/{y}] {len(urls)} candidates", flush=True)
            for u in urls[:5]:
                rec = fetch(u, "province", code, y, kind="html")
                if rec:
                    saved += 1
                    print(f"   ok -> {rec['path']}", flush=True)
                    break
    print(f"\nDONE  saved={saved}", flush=True)


if __name__ == "__main__":
    main()
