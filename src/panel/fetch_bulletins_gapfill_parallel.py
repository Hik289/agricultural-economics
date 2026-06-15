"""Parallel gap-fill: pre-compute Brave candidates for ALL missing pairs
upfront, then fetch in parallel grouped by host (≥2 s/host within group).
"""
from __future__ import annotations
import concurrent.futures as cf
import json
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bulletin_common import fetch, brave_search, MANIFEST, _domain  # noqa: E402

PROV_NAMES: dict[str, str] = {
    "11": "北京", "12": "天津", "13": "河北", "14": "山西", "15": "内蒙古",
    "21": "辽宁", "22": "吉林", "23": "黑龙江", "31": "上海", "32": "江苏",
    "33": "浙江", "34": "安徽", "35": "福建", "36": "江西", "37": "山东",
    "41": "河南", "42": "湖北", "43": "湖南", "44": "广东", "45": "广西",
    "46": "海南", "50": "重庆", "51": "四川", "52": "贵州", "53": "云南",
    "54": "西藏", "61": "陕西", "62": "甘肃", "63": "青海", "64": "宁夏",
    "65": "新疆",
}


def _have_ok(code: str, year: int) -> bool:
    if not MANIFEST.exists():
        return False
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok" and r.get("level") == "province" and r.get("geo_code") == code and r.get("year") == year:
            return True
    return False


def _candidate_urls(prov_name: str, year: int) -> list[str]:
    suffix = "省" if prov_name not in {"北京", "上海", "天津", "重庆", "内蒙古", "广西", "西藏", "宁夏", "新疆"} else ("市" if prov_name in {"北京", "上海", "天津", "重庆"} else "自治区")
    base = prov_name + suffix
    queries = [
        f"site:gov.cn {base} {year}年 国民经济和社会发展统计公报",
        f"\"{year}年{base}国民经济和社会发展统计公报\"",
    ]
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
            if "图解" in u or "解读" in u or "/jdwd/" in u:
                continue
            urls.append(u)
    return urls[:8]


def main() -> int:
    YEARS = list(range(2015, 2025))
    missing = [(c, y) for c in PROV_NAMES for y in YEARS if not _have_ok(c, y)]
    print(f"missing pairs: {len(missing)}", flush=True)

    # Phase 1: discover (sequential — Brave RPS limit).
    pair_to_urls: dict[tuple[str, int], list[str]] = {}
    for i, (code, year) in enumerate(missing):
        cands = _candidate_urls(PROV_NAMES[code], year)
        pair_to_urls[(code, year)] = cands
        if (i + 1) % 10 == 0:
            print(f"  [discover {i+1}/{len(missing)}]", flush=True)
    print(f"discover done; total candidate URLs: {sum(len(v) for v in pair_to_urls.values())}", flush=True)

    # Phase 2: parallel fetch grouped by host.
    # Build a queue: (code, year, [url1, url2, ...]) where each is a tuple of attempts.
    # We attempt URLs sequentially per pair; if any succeeds we mark and stop.
    pair_lock = threading.Lock()
    succeeded: set[tuple[str, int]] = set()
    counts = {"ok": 0, "skip": 0}

    # Group attempt-events by host so a single host's quota stays ≥ 2 s.
    by_host: dict[str, list[tuple[str, int, str, int]]] = defaultdict(list)
    for (code, year), urls in pair_to_urls.items():
        for prio, u in enumerate(urls):
            by_host[_domain(u)].append((code, year, u, prio))
    # within each host bucket, sort by prio so we try the best URL first
    for h in by_host:
        by_host[h].sort(key=lambda t: t[3])

    def worker(host: str, attempts: list) -> None:
        for code, year, url, prio in attempts:
            with pair_lock:
                if (code, year) in succeeded:
                    continue
            rec = fetch(url, "province", code, year, kind="html")
            if rec:
                with pair_lock:
                    if (code, year) not in succeeded:
                        succeeded.add((code, year))
                        counts["ok"] += 1
                        print(f"  [ok {len(succeeded)}/{len(missing)}] {code}/{year} @ {host} prio={prio}", flush=True)

    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        futures = [ex.submit(worker, h, items) for h, items in by_host.items()]
        for f in cf.as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"worker err: {e}", flush=True)
    counts["skip"] = len(missing) - len(succeeded)
    print(f"\nDONE  ok={counts['ok']}  still-missing={counts['skip']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
