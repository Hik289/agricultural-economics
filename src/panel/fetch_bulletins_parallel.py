"""Parallel fetcher: reads the discover list from a stashed file (or re-runs
the discovery), then fetches in parallel across hosts (respecting 2 s/host).

Use after `crawl_province_bulletins.py` has been killed mid-fetch.
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
from _bulletin_common import fetch, manifest_append, _domain, MANIFEST, LOG_DIR  # noqa: E402


def _already_have(geo_code: str, year: int, level: str) -> bool:
    """Look in manifest for an existing successful fetch."""
    if not MANIFEST.exists():
        return False
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok" and r.get("level") == level and r.get("geo_code") == geo_code and r.get("year") == year:
            return True
    return False


def _host_locks() -> dict:
    return defaultdict(threading.Lock)


def main():
    # Discover list is in the crawl_province log (we parse [brave] lines).
    log_path = LOG_DIR / "crawl_province_bulletins.txt"
    discovered: list[tuple[str, int, str]] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("[brave] ") or line.startswith("[listing-found] "):
                # parse: [brave] 北京 2015 -> URL
                try:
                    rest = line.split("] ", 1)[1]
                    prov, rest2 = rest.split(" ", 1)
                    year_s, url = rest2.split(" -> ", 1)
                    discovered.append((prov, int(year_s.strip()), url.strip()))
                except Exception:
                    pass

    # Also re-run discover to get listing-found URLs (the script only printed [brave])
    from crawl_province_bulletins import PROVINCES, discover_from_listing
    print(f"re-running listing discovery for {len(PROVINCES)} provinces ...", flush=True)
    for code, name, urls in PROVINCES:
        for u in urls:
            try:
                yr_to_url = discover_from_listing(code, name, u)
                for y, link in yr_to_url.items():
                    if 2015 <= y <= 2024:
                        discovered.append((name, y, link))
            except Exception:
                pass

    # name -> code map
    name2code = {n: c for c, n, _ in PROVINCES}
    queue: list[tuple[str, int, str]] = []
    seen = set()
    for prov_name, year, url in discovered:
        code = name2code.get(prov_name)
        if not code:
            continue
        if (code, year) in seen:
            continue
        seen.add((code, year))
        if _already_have(code, year, "province"):
            continue
        queue.append((code, year, url))

    print(f"queue size: {len(queue)} (after dedup, already-have filter)", flush=True)

    # Group by host so we can run hosts in parallel; sequential within host.
    by_host: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for c, y, u in queue:
        by_host[_domain(u)].append((c, y, u))

    print(f"distinct hosts: {len(by_host)}", flush=True)

    counts = {"ok": 0, "skip": 0}
    counts_lock = threading.Lock()

    def worker(host: str, items: list[tuple[str, int, str]]) -> None:
        for code, year, url in items:
            rec = fetch(url, "province", code, year, kind="html")
            with counts_lock:
                if rec:
                    counts["ok"] += 1
                    tag = "ok"
                else:
                    counts["skip"] += 1
                    tag = "skip"
                tot = counts["ok"] + counts["skip"]
                print(f"  [{tot}/{len(queue)}] {tag} {code}/{year} @ {host}", flush=True)

    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        futures = [ex.submit(worker, h, items) for h, items in by_host.items()]
        for f in cf.as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"worker err: {e}", flush=True)

    print(f"\nDONE  ok={counts['ok']}  skip={counts['skip']}", flush=True)


if __name__ == "__main__":
    main()
