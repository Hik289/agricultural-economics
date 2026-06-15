"""Wayback Machine gap-fill for 4 GCP-unreachable provinces.

Strategy:
1. For each (province, year) gap, use the Wayback `available` API to find a
   snapshot of the original bulletin URL (we know these URLs from earlier
   Brave hits).
2. Also try a `cdx` query on `tjj.<province>.gov.cn/*tjgb*` style patterns to
   discover all archived bulletin URLs.
3. Fetch each successful snapshot HTML and persist to
   `data/external/bulletins_wayback/`.
4. Append entries to the existing `data/external/bulletins/manifest.jsonl`
   with `source_archive: "wayback"` and `original_url`, so downstream code
   treats them like any other bulletin.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

PROJECT_ROOT = Path("/home/user/projects/epvr-replication")
WB_DIR = PROJECT_ROOT / "data" / "external" / "bulletins_wayback"
MANIFEST = PROJECT_ROOT / "data" / "external" / "bulletins" / "manifest.jsonl"
LOG_DIR = PROJECT_ROOT / "analysis" / "logs"
WB_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

JST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36 Research-Lab academic-archive-fetcher"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}

# Known URLs from earlier Brave hits per (province, year).
KNOWN_URLS: dict[tuple[str, int], list[str]] = {
    # Jiangxi
    ("36", 2015): ["http://tjj.jiangxi.gov.cn/art/2016/4/27/art_38595_368283.html"],
    ("36", 2017): ["http://tjj.jiangxi.gov.cn/art/2018/3/20/art_38595_823124.html"],
    ("36", 2019): ["http://tjj.jiangxi.gov.cn/art/2020/3/24/art_38595_2192728.html"],
    ("36", 2020): ["http://tjj.jiangxi.gov.cn/art/2021/3/26/art_38595_3258020.html"],
    ("36", 2022): ["http://tjj.jiangxi.gov.cn/art/2023/4/4/art_38595_4498527.html"],
    ("36", 2023): ["http://tjj.jiangxi.gov.cn/art/2024/3/24/art_38595_4621567.html"],
    # Sichuan
    ("51", 2015): ["http://tjj.sc.gov.cn/scstjj/c105855/2016/3/1/d8f9b54b8f8d4d24a44e7b2af0b35e26.shtml"],
    ("51", 2018): ["http://tjj.sc.gov.cn/scstjj/c105855/2019/3/26/c9fbf4a3d4b8434588fa3e34fa9c3e5a.shtml"],
    ("51", 2019): ["http://tjj.sc.gov.cn/scstjj/c105855/2020/3/18/d4fbcfb3e9794055be0b9d3a8d0d2bd1.shtml"],
    ("51", 2020): ["http://tjj.sc.gov.cn/scstjj/c105855/2021/3/24/db8f4b5fc0d8489eb3e3e3d9a3bbf2f8.shtml"],
    ("51", 2022): ["http://tjj.sc.gov.cn/scstjj/c105855/2023/3/29/db4f8e5f5a8a40d5b0c47c1f37f24ed5.shtml"],
    ("51", 2023): ["http://tjj.sc.gov.cn/scstjj/c105855/2024/3/26/4d527d8a13aa44dabb01e87fc92a7cb6.shtml"],
    # Guizhou
    ("52", 2015): ["http://stjj.guizhou.gov.cn/tjsj_35719/tjgb/201605/t20160526_1042167.html"],
    ("52", 2016): ["http://stjj.guizhou.gov.cn/tjsj_35719/tjgb/201705/t20170504_1042178.html"],
    ("52", 2018): ["http://stjj.guizhou.gov.cn/tjsj_35719/tjgb/201904/t20190417_1042195.html"],
    ("52", 2020): ["http://stjj.guizhou.gov.cn/tjsj_35719/tjgb/202103/t20210330_67007830.html"],
    ("52", 2021): ["http://stjj.guizhou.gov.cn/tjsj_35719/tjgb/202205/t20220517_73803961.html"],
    ("52", 2023): ["http://stjj.guizhou.gov.cn/tjsj/tjfbyjd/202403/t20240329_84106180.html"],
    # Shaanxi
    ("61", 2015): ["http://tjj.shaanxi.gov.cn/upload/2016/zk/sxsndgb/sxsndgb.html"],
    ("61", 2016): ["http://tjj.shaanxi.gov.cn/upload/2017/zk/sxsndgb/sxsndgb.html"],
    ("61", 2017): ["http://tjj.shaanxi.gov.cn/upload/2018/zk/sxsndgb/sxsndgb.html"],
    ("61", 2018): ["http://tjj.shaanxi.gov.cn/upload/2019/zk/sxsndgb/sxsndgb.html"],
    ("61", 2019): ["http://tjj.shaanxi.gov.cn/upload/2020/zk/sxsndgb/sxsndgb.html"],
    ("61", 2020): ["http://tjj.shaanxi.gov.cn/upload/2021/zk/sxsndgb/sxsndgb.html"],
    ("61", 2021): ["http://tjj.shaanxi.gov.cn/upload/2022/zk/sxsndgb/sxsndgb.html"],
    ("61", 2022): ["http://tjj.shaanxi.gov.cn/upload/2023/zk/sxsndgb/sxsndgb.html"],
    ("61", 2023): ["http://tjj.shaanxi.gov.cn/upload/2024/zk/sxsndgb/sxsndgb.html"],
}

# Generic listing hosts whose CDX should give us more URLs.
LIST_HOSTS: dict[str, list[str]] = {
    "36": ["tjj.jiangxi.gov.cn/art", "tjj.jiangxi.gov.cn"],
    "51": ["tjj.sc.gov.cn/scstjj/c105855", "tjj.sc.gov.cn"],
    "52": ["stjj.guizhou.gov.cn/tjsj_35719/tjgb", "stjj.guizhou.gov.cn/tjsj/tjfbyjd"],
    "61": ["tjj.shaanxi.gov.cn/upload"],
}


def _now_jst() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def _sha8(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:8]


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _decode(content: bytes) -> str:
    head = content[:2000].decode("ascii", errors="replace").lower()
    m = re.search(r'charset=["\']?([^"\'>\s]+)', head)
    if m:
        enc = m.group(1)
        try:
            return content.decode(enc, errors="replace")
        except LookupError:
            pass
    for enc in ("utf-8", "gbk", "gb2312", "gb18030"):
        try:
            return content.decode(enc, errors="strict")
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _append_manifest(rec: dict) -> None:
    with MANIFEST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _have_ok_province(code: str, year: int) -> bool:
    """Check if we already have a successful provincial bulletin for (code, year)."""
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


# ---- Wayback API helpers ----

def wb_available(url: str, timestamp: str = "") -> dict | None:
    """Return closest Wayback snapshot for `url` near `timestamp`."""
    try:
        params = {"url": url}
        if timestamp:
            params["timestamp"] = timestamp
        r = requests.get("https://archive.org/wayback/available", params=params, headers=HEADERS, timeout=25)
    except Exception as e:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json().get("archived_snapshots", {}).get("closest") or None
    except Exception:
        return None


def wb_cdx(url_pattern: str, max_attempts: int = 4) -> list[tuple[str, str]]:
    """CDX search for a URL pattern. Returns list of (timestamp, original_url)."""
    api = "https://web.archive.org/cdx/search/cdx"
    params = {
        "url": url_pattern,
        "output": "json",
        "limit": "300",
        "filter": "statuscode:200",
        "fl": "timestamp,original,statuscode",
        "collapse": "urlkey",
    }
    for attempt in range(max_attempts):
        try:
            r = requests.get(api, params=params, headers=HEADERS, timeout=60)
        except Exception as e:
            time.sleep(8 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                data = r.json()
            except Exception:
                return []
            if not data or len(data) <= 1:
                return []
            return [(row[0], row[1]) for row in data[1:] if len(row) >= 2]
        if r.status_code in (429, 503):
            time.sleep(15 * (attempt + 1))
            continue
        break
    return []


def fetch_wb_snapshot(wb_url: str) -> bytes | None:
    """Fetch a Wayback /web/<ts>/<url> snapshot.

    We replace the http://web.archive.org/web/<ts>/ prefix with the
    `if_` flag to get the raw HTML (no Wayback toolbar)."""
    # Insert "if_" after timestamp so wayback returns unmodified HTML
    m = re.match(r"^(https?://web\.archive\.org/web/)(\d+)/", wb_url)
    if m:
        wb_url = m.group(1) + m.group(2) + "if_/" + wb_url[m.end():]
    try:
        r = requests.get(wb_url, headers=HEADERS, timeout=(8, 40), allow_redirects=True)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    return r.content


def save_wb_html(province: str, year: int, original_url: str, timestamp: str, body: bytes) -> dict:
    sha8 = _sha8(body)
    fname = WB_DIR / f"province_{province}_{year}_{sha8}.html"
    if not fname.exists():
        try:
            text = _decode(body)
            fname.write_text(text, encoding="utf-8", errors="replace")
        except Exception:
            fname.write_bytes(body)
    rec = {
        "ts_jst": _now_jst(),
        "url": original_url,
        "wayback_url": f"https://web.archive.org/web/{timestamp}/{original_url}",
        "domain": original_url.split("/")[2] if original_url.startswith("http") else "",
        "level": "province",
        "geo_code": province,
        "year": year,
        "kind": "html",
        "status": "ok",
        "bytes": len(body),
        "sha256": _sha256(body),
        "sha8": sha8,
        "path": str(fname.relative_to(PROJECT_ROOT)),
        "source_archive": "wayback",
        "wayback_timestamp": timestamp,
    }
    _append_manifest(rec)
    return rec


def harvest_province_year(province: str, year: int, candidate_urls: list[str], log: list[str]) -> dict | None:
    # ts = first day of the year after the bulletin year, since bulletins are
    # released in early-Q1 of year+1.
    target_ts = f"{year+1}0401"
    for orig_url in candidate_urls:
        snap = wb_available(orig_url, timestamp=target_ts)
        time.sleep(2.5)
        if not snap or not snap.get("available"):
            continue
        wb_url = snap.get("url")
        ts = snap.get("timestamp", "")
        body = fetch_wb_snapshot(wb_url)
        time.sleep(2.0)
        if body is None or len(body) < 1000:
            log.append(f"  [skip-snapshot] {province}/{year} {orig_url[:60]} (snap exists but body fetch failed)")
            continue
        rec = save_wb_html(province, year, orig_url, ts, body)
        log.append(f"  [ok-wb] {province}/{year} -> {rec['path']} (snap {ts})")
        return rec
    return None


def discover_via_cdx(province: str, year: int, log: list[str]) -> list[str]:
    """Use CDX to find archived bulletin URLs in that province."""
    found: list[str] = []
    for pat in LIST_HOSTS.get(province, []):
        snaps = wb_cdx(f"{pat}*")
        # filter URLs containing 'tjgb' or 'art_38595' (jiangxi) or 'sxsndgb' (shaanxi) or 'c105855' (sichuan)
        for ts, orig in snaps:
            # detail-page heuristic
            if "tjgb" in orig or "art_38595" in orig or "sxsndgb" in orig or "c105855" in orig:
                found.append((ts, orig))
        time.sleep(4)
    # dedup by original URL
    seen = set()
    out = []
    for ts, orig in found:
        if orig in seen:
            continue
        seen.add(orig)
        out.append((ts, orig))
    log.append(f"  [cdx] {province}/{year} -> {len(out)} candidates from CDX")
    return out


def main() -> int:
    YEARS = list(range(2015, 2025))
    TARGET_PROVINCES = ["36", "51", "52", "61"]
    log: list[str] = []
    saved = 0
    saved_pairs: list[tuple[str, int]] = []
    start_time = time.time()
    HARD_DEADLINE_S = 90 * 60  # 90 min hard cap; leave 10 min for merge+report

    # Phase 1: known URLs.
    log.append(f"=== PHASE 1: known URLs ===")
    for code in TARGET_PROVINCES:
        for y in YEARS:
            if time.time() - start_time > HARD_DEADLINE_S:
                log.append("** deadline hit **")
                break
            if _have_ok_province(code, y):
                continue
            cands = KNOWN_URLS.get((code, y), [])
            if not cands:
                continue
            rec = harvest_province_year(code, y, cands, log)
            if rec:
                saved += 1
                saved_pairs.append((code, y))
        if time.time() - start_time > HARD_DEADLINE_S:
            break

    # Phase 2: CDX discovery (more expensive but broader)
    log.append(f"\n=== PHASE 2: CDX discovery ===")
    for code in TARGET_PROVINCES:
        if time.time() - start_time > HARD_DEADLINE_S:
            break
        cdx_hits = discover_via_cdx(code, 0, log)
        if not cdx_hits:
            continue
        # try each unique original URL via wayback (we already have ts)
        for ts, orig in cdx_hits[:60]:
            if time.time() - start_time > HARD_DEADLINE_S:
                break
            # infer year from URL or content text once fetched
            m = re.search(r"(20[1-2][0-9])", orig)
            if not m:
                continue
            for guess_y in range(2015, 2025):
                if _have_ok_province(code, guess_y):
                    continue
            # We don't know which (province, year) yet; fetch and use bulletin-year heuristic later.
            wb_url = f"https://web.archive.org/web/{ts}/{orig}"
            body = fetch_wb_snapshot(wb_url)
            time.sleep(1.8)
            if body is None or len(body) < 1500:
                continue
            # naive year extract from body
            try:
                text_snip = body[:30000].decode("utf-8", errors="replace") + body[:30000].decode("gbk", errors="replace")
            except Exception:
                continue
            ym = re.search(r"(20[1-2][0-9])\s*年(?:国民经济和社会发展)?统计公报", text_snip)
            if not ym:
                continue
            yr_in_doc = int(ym.group(1))
            if not (2015 <= yr_in_doc <= 2024):
                continue
            if _have_ok_province(code, yr_in_doc):
                continue
            rec = save_wb_html(code, yr_in_doc, orig, ts, body)
            saved += 1
            saved_pairs.append((code, yr_in_doc))
            log.append(f"  [ok-cdx] {code}/{yr_in_doc} -> {rec['path']} (snap {ts})")

    (LOG_DIR / "wayback_gapfill.log").write_text("\n".join(log), encoding="utf-8")
    print(f"\nDONE  wayback_saved={saved}  pairs={sorted(saved_pairs)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
