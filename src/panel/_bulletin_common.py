"""Shared helpers for crawling provincial / municipal 国民经济和社会发展统计公报.

Spec §9.2 rules continue to apply: robots.txt, ≥ 2 s / host, identifying UA,
no paywall bypass.  We reuse the same crawl_index.jsonl so all evidence is
auditable from one place.

Output paths:
    data/external/bulletins/{level}_{geo_code}_{year}_{sha8}.html  (or .pdf)
    data/external/bulletins/manifest.jsonl  (one record per saved file)
"""
from __future__ import annotations
import hashlib
import json
import os
import random
import re
import time
import urllib.parse as up
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
from urllib.robotparser import RobotFileParser

JST = timezone(timedelta(hours=9))

PROJECT_ROOT = Path("/home/user/projects/epvr-replication")
EXT_DIR = PROJECT_ROOT / "data" / "external" / "bulletins"
MANIFEST = EXT_DIR / "manifest.jsonl"
PROCESSED = PROJECT_ROOT / "data" / "processed"
LOG_DIR = PROJECT_ROOT / "analysis" / "logs"
EXT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 "
    "(Research-Lab academic-research-crawler; contact [REDACTED])"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}

REQUEST_INTERVAL_S = 2.05
_last_request_t: dict[str, float] = {}
_robots: dict[str, RobotFileParser] = {}
_robots_status: dict[str, str] = {}

# Hosts we already saw block GCP egress; we skip them entirely.
KNOWN_BLOCKED = {"www.reea.agri.cn", "reea.agri.cn"}


def _domain(url: str) -> str:
    return up.urlparse(url).netloc.lower()


def _scheme(url: str) -> str:
    return up.urlparse(url).scheme or "https"


def can_fetch(url: str) -> tuple[bool, str]:
    host = _domain(url)
    if not host:
        return False, "no_host"
    if host in KNOWN_BLOCKED:
        _robots_status[host] = "blocked_by_waf"
        return False, "host_blocked_by_waf"
    rp = _robots.get(host)
    if rp is None:
        rp = RobotFileParser()
        rp.set_url(f"{_scheme(url)}://{host}/robots.txt")
        try:
            r = requests.get(rp.url, headers=HEADERS, timeout=8, verify=False)
            if r.status_code == 200 and r.text.strip():
                rp.parse(r.text.splitlines())
                _robots_status[host] = "fetched"
            else:
                _robots_status[host] = f"missing_{r.status_code}"
                rp.parse(["User-agent: *", "Allow: /"])
        except Exception as e:
            _robots_status[host] = f"error_{type(e).__name__}"
            rp.parse(["User-agent: *", "Allow: /"])
        _robots[host] = rp
    return (rp.can_fetch(UA, url), "" if rp.can_fetch(UA, url) else "robots_disallow")


def _respect_rate(host: str) -> None:
    last = _last_request_t.get(host, 0.0)
    wait = REQUEST_INTERVAL_S - (time.time() - last)
    if wait > 0:
        time.sleep(wait + random.uniform(0, 0.3))
    _last_request_t[host] = time.time()


def _now_jst() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def _sha8(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:8]


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def manifest_append(rec: dict) -> None:
    with MANIFEST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _decode(content: bytes, ctype: str = "", url: str = "") -> str:
    """Decode HTML bytes — tries utf-8, gbk, gb2312."""
    # Look for meta charset
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


def fetch(url: str, level: str, geo_code: str, year: int, kind: str = "html") -> Optional[dict]:
    """Fetch one bulletin URL and persist to data/external/bulletins/."""
    host = _domain(url)
    if not host:
        return None
    ok, reason = can_fetch(url)
    if not ok:
        manifest_append({"ts_jst": _now_jst(), "url": url, "level": level,
                         "geo_code": geo_code, "year": year, "kind": kind,
                         "status": "skipped", "reason": reason})
        return None
    _respect_rate(host)
    try:
        r = requests.get(url, headers=HEADERS, timeout=(6, 18), verify=False, allow_redirects=True)
    except Exception as e:
        manifest_append({"ts_jst": _now_jst(), "url": url, "level": level,
                         "geo_code": geo_code, "year": year, "kind": kind,
                         "status": "error", "reason": f"{type(e).__name__}: {str(e)[:80]}"})
        return None
    if r.status_code != 200:
        manifest_append({"ts_jst": _now_jst(), "url": url, "level": level,
                         "geo_code": geo_code, "year": year, "kind": kind,
                         "status": "error", "http_status": r.status_code})
        return None
    body = r.content
    if not body or len(body) < 500:
        manifest_append({"ts_jst": _now_jst(), "url": url, "level": level,
                         "geo_code": geo_code, "year": year, "kind": kind,
                         "status": "empty"})
        return None
    is_pdf = body[:4].startswith(b"%PDF") or url.lower().endswith(".pdf") or "application/pdf" in r.headers.get("Content-Type", "").lower()
    if kind == "html" and is_pdf:
        kind = "pdf"
    sha8 = _sha8(body)
    sha256 = _sha256(body)
    ext = "pdf" if kind == "pdf" else "html"
    fname = f"{level}_{geo_code}_{year}_{sha8}.{ext}"
    path = EXT_DIR / fname
    if not path.exists():
        if kind == "html":
            try:
                text = _decode(body, r.headers.get("Content-Type", ""), url)
                path.write_text(text, encoding="utf-8", errors="replace")
            except Exception:
                path.write_bytes(body)
        else:
            path.write_bytes(body)
    rec = {
        "ts_jst": _now_jst(),
        "url": url, "final_url": r.url, "domain": host,
        "level": level, "geo_code": geo_code, "year": year, "kind": kind,
        "status": "ok", "http_status": r.status_code,
        "bytes": len(body), "sha256": sha256, "sha8": sha8,
        "path": str(path.relative_to(PROJECT_ROOT)),
    }
    manifest_append(rec)
    return rec


def brave_search(query: str, count: int = 10) -> list[dict]:
    key = os.environ.get("SEARCH_API_KEY") or os.environ.get("BRAVE_API_KEY")
    if not key:
        return []
    headers = {"Accept": "application/json", "X-Subscription-Token": key}
    params = {"q": query, "count": min(count, 20), "country": "CN", "search_lang": "zh-hans"}
    time.sleep(1.1)
    try:
        r = requests.get("https://api.search.brave.com/res/v1/web/search",
                         headers=headers, params=params, timeout=15)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    try:
        data = r.json()
    except Exception:
        return []
    out = []
    for it in data.get("web", {}).get("results", []) or []:
        out.append({
            "url": it.get("url", ""),
            "title": it.get("title", ""),
            "description": it.get("description", ""),
            "host": _domain(it.get("url", "")),
        })
    return out
