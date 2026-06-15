"""Discover and fetch provincial 国民经济和社会发展统计公报 for years 2015-2024.

Strategy:
1. Curated "index page" URLs for each provincial 统计公报 listing.
2. For each listing, parse anchor texts matching `(YYYY) 年.*国民经济和社会发展统计公报`
   and fetch the linked HTML/PDF.
3. Brave Search backup for missing (province, year) pairs.

All fetched files land in `data/external/bulletins/province_{code}_{year}_{sha8}.html`
with a manifest.jsonl entry.
"""
from __future__ import annotations
import re
import sys
import time
import urllib.parse as up
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from _bulletin_common import fetch, brave_search, _decode, _domain, HEADERS, LOG_DIR  # noqa: E402
import requests

PROVINCES: list[tuple[str, str, list[str]]] = [
    ("11", "北京",   ["https://tjj.beijing.gov.cn/tjsj_31433/tjgb_31445/"]),
    ("12", "天津",   ["https://stats.tj.gov.cn/tjsj_52319/tjgb/"]),
    ("13", "河北",   ["http://tjj.hebei.gov.cn/hetj/tjgbcontainer/"]),
    ("14", "山西",   ["http://tjj.shanxi.gov.cn/tjsj/tjgb/"]),
    ("15", "内蒙古", ["http://tj.nmg.gov.cn/tjyw/jdfx/ndgb/"]),
    ("21", "辽宁",   ["http://tjj.ln.gov.cn/tjj/tjgb/index.shtml"]),
    ("22", "吉林",   ["http://tjj.jl.gov.cn/tjsj/tjgb/"]),
    ("23", "黑龙江", ["http://tjj.hlj.gov.cn/tjgb/"]),
    ("31", "上海",   ["https://tjj.sh.gov.cn/tjgb/index.html"]),
    ("32", "江苏",   ["http://tj.jiangsu.gov.cn/col/col4011/index.html"]),
    ("33", "浙江",   ["https://tjj.zj.gov.cn/col/col1525563/index.html"]),
    ("34", "安徽",   ["http://tjj.ah.gov.cn/ssah/qwfbjd/tjgb/index.html"]),
    ("35", "福建",   ["http://tjj.fujian.gov.cn/xxgk/tjgb/", "https://www.fj.gov.cn/zwgk/sjfb/tjgb/"]),
    ("36", "江西",   ["http://tjj.jiangxi.gov.cn/col/col38595/index.html"]),
    ("37", "山东",   ["http://tjj.shandong.gov.cn/col/col6273/index.html"]),
    ("41", "河南",   ["https://tjj.henan.gov.cn/tjfw/tjgb/"]),
    ("42", "湖北",   ["http://tjj.hubei.gov.cn/tjsj/tjgb/"]),
    ("43", "湖南",   ["http://tjj.hunan.gov.cn/tjsj/tjgb/"]),
    ("44", "广东",   ["http://stats.gd.gov.cn/gdtjgb/"]),
    ("45", "广西",   ["http://tjj.gxzf.gov.cn/tjsj/tjgb/"]),
    ("46", "海南",   ["http://stats.hainan.gov.cn/tjj/tjsu/tjgb/"]),
    ("50", "重庆",   ["https://tjj.cq.gov.cn/zwgk_233/tjnj/"]),
    ("51", "四川",   ["http://tjj.sc.gov.cn/scstjj/c105855/list_tjgb.shtml"]),
    ("52", "贵州",   ["http://stjj.guizhou.gov.cn/tjsj_35719/tjgb/"]),
    ("53", "云南",   ["http://stats.yn.gov.cn/tjsj/tjgb/"]),
    ("54", "西藏",   ["http://tjj.xizang.gov.cn/tjsj/tjgb/"]),
    ("61", "陕西",   ["http://tjj.shaanxi.gov.cn/upload/site1/list.jsp?cid=10000"]),
    ("62", "甘肃",   ["http://tjj.gansu.gov.cn/tjj/c109464/info_list.shtml"]),
    ("63", "青海",   ["http://tjj.qinghai.gov.cn/tjData/qhtjgb/"]),
    ("64", "宁夏",   ["http://nxdata.gov.cn/qygjjShzfzgb/"]),
    ("65", "新疆",   ["http://tjj.xinjiang.gov.cn/tjj/tjgb/list_gk.shtml"]),
]

BULLETIN_RE = re.compile(r"(20[1-2][0-9])\s*年(?:.*?)(?:国民经济和社会发展)?统计公报")


def _fetch_html(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=(8, 20), verify=False, allow_redirects=True)
    except Exception as e:
        print(f"   ! fetch_html err: {type(e).__name__}", flush=True)
        return None
    if r.status_code != 200:
        return None
    return _decode(r.content, r.headers.get("Content-Type", ""), url)


def discover_from_listing(prov_code: str, prov_name: str, listing_url: str) -> dict[int, str]:
    out: dict[int, str] = {}
    html = _fetch_html(listing_url)
    if html is None:
        return out
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if not text:
            continue
        m = BULLETIN_RE.search(text)
        if not m:
            continue
        year = int(m.group(1))
        if not (2015 <= year <= 2025):
            continue
        if "图解" in text or "一图读懂" in text or "解读" in text:
            continue
        href = a["href"].strip()
        url = up.urljoin(listing_url, href)
        if not (url.endswith((".htm", ".html", ".shtml", ".pdf")) or re.search(r"\?\w+=", url)):
            continue
        if year not in out:
            out[year] = url
    return out


def discover_via_brave(prov_name: str, year: int) -> str | None:
    if prov_name in {"北京", "上海", "天津", "重庆"}:
        q = f"{prov_name}市 {year}年 国民经济和社会发展统计公报"
    elif prov_name in {"内蒙古", "广西", "西藏", "宁夏", "新疆"}:
        q = f"{prov_name}自治区 {year}年 国民经济和社会发展统计公报"
    else:
        q = f"{prov_name}省 {year}年 国民经济和社会发展统计公报"
    res = brave_search(q, count=10)
    for r in res:
        host = r["host"]
        url = r["url"]
        if not host or "图解" in url or "tjgb.hongheiku" in host or "tjcn.org" in host:
            continue
        if not host.endswith(".gov.cn"):
            continue
        return url
    return None


def main() -> int:
    log: list[str] = []
    YEARS = list(range(2015, 2025))
    saved = 0
    skipped = 0
    discovered: dict[tuple[str, int], str] = {}

    # Phase 1: listing-page discovery.
    for prov_code, prov_name, listing_urls in PROVINCES:
        for listing in listing_urls:
            print(f"[listing] {prov_name} :: {listing}", flush=True)
            log.append(f"[listing] {prov_name} :: {listing}")
            yr_to_url = discover_from_listing(prov_code, prov_name, listing)
            print(f"   -> {len(yr_to_url)} year-links: {sorted(yr_to_url.keys())}", flush=True)
            log.append(f"   -> found {len(yr_to_url)} year-links: {sorted(yr_to_url.keys())}")
            for y, u in yr_to_url.items():
                if 2015 <= y <= 2024:
                    discovered.setdefault((prov_code, y), u)
            time.sleep(2.0)

    log.append(f"\n=== after listing-phase: {len(discovered)} (prov, year) pairs ===\n")

    print(f"\n=== after listings: {len(discovered)} pairs ===\n", flush=True)
    # Phase 2: Brave for missing (prov, year)
    for prov_code, prov_name, _ in PROVINCES:
        for y in YEARS:
            if (prov_code, y) in discovered:
                continue
            u = discover_via_brave(prov_name, y)
            if u:
                discovered[(prov_code, y)] = u
                print(f"[brave] {prov_name} {y} -> {u[:80]}", flush=True)
                log.append(f"[brave] {prov_name} {y} -> {u}")
            else:
                print(f"[brave-miss] {prov_name} {y}", flush=True)
                log.append(f"[brave-miss] {prov_name} {y}")

    log.append(f"\n=== final discovered: {len(discovered)} / {len(PROVINCES)*len(YEARS)} ===\n")

    print(f"\n=== final discovered: {len(discovered)} ===\n", flush=True)
    # Phase 3: fetch
    for i, ((prov_code, year), url) in enumerate(discovered.items()):
        rec = fetch(url, "province", prov_code, year, kind="html")
        if rec:
            saved += 1
            print(f"[{i+1}/{len(discovered)}] ok {prov_code}/{year} -> {rec['path']}", flush=True)
            log.append(f"[ok] {prov_code} {year} -> {rec['path']}")
        else:
            skipped += 1
            print(f"[{i+1}/{len(discovered)}] skip {prov_code}/{year}", flush=True)
            log.append(f"[skip] {prov_code} {year} -> {url}")

    (LOG_DIR / "crawl_province_bulletins.log").write_text("\n".join(log), encoding="utf-8")
    print(f"crawl_province_bulletins: discovered={len(discovered)} saved={saved} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
