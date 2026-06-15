"""Shared crawl utilities.

Spec §9.2 rules:
- robots.txt respected
- request interval >= 2.0 s
- save raw HTML/PDF + index with sha256
- never bypass paywalls / logins
- skip restricted datasets (CFPS/CRRS/CHFS)
"""
from __future__ import annotations
import hashlib
import json
import os
import random
import time
import urllib.parse as up
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
from urllib.robotparser import RobotFileParser

# JST per SOUL.md.
JST = timezone(timedelta(hours=9))

PROJECT_ROOT = Path("/home/user/projects/epvr-replication")
DATA_DIR = PROJECT_ROOT / "data"
RAW_HTML = DATA_DIR / "raw_html"
RAW_PDF = DATA_DIR / "raw_pdf"
PROCESSED = DATA_DIR / "processed"
CRAWL_INDEX = DATA_DIR / "crawl_index.jsonl"
LOG_DIR = PROJECT_ROOT / "analysis" / "logs"
for _p in (RAW_HTML, RAW_PDF, PROCESSED, LOG_DIR):
    _p.mkdir(parents=True, exist_ok=True)

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

# Hosts known to block from GCP egress (HTTP 403).  We document and skip per spec §9.2.
KNOWN_BLOCKED_HOSTS = {
    "reea.agri.cn",
    "www.reea.agri.cn",
}

OFFICIAL_TLDS = (".gov.cn", ".org.cn")
OFFICIAL_HOSTS = {
    "mnr.gov.cn", "www.mnr.gov.cn",
    "mee.gov.cn", "www.mee.gov.cn",
    "moa.gov.cn", "www.moa.gov.cn",
    "agri.cn", "www.agri.cn",
    "reea.agri.cn", "www.reea.agri.cn",
    "stats.gov.cn", "www.stats.gov.cn",
    "gov.cn", "www.gov.cn",
}

REQUEST_INTERVAL_S = 2.05  # >= 2.0 per spec §9.2.
_last_request_t: dict[str, float] = {}

_robots_cache: dict[str, RobotFileParser] = {}
_robots_status: dict[str, str] = {}


def _domain(url: str) -> str:
    return up.urlparse(url).netloc.lower()


def _scheme(url: str) -> str:
    return up.urlparse(url).scheme or "https"


def _robots_url(url: str) -> str:
    return f"{_scheme(url)}://{_domain(url)}/robots.txt"


def can_fetch(url: str) -> tuple[bool, str]:
    host = _domain(url)
    if not host:
        return False, "no_host"
    if host in KNOWN_BLOCKED_HOSTS:
        _robots_status[host] = "blocked_by_waf"
        return False, "host_blocked_by_waf"
    rp = _robots_cache.get(host)
    if rp is None:
        rp = RobotFileParser()
        rp.set_url(_robots_url(url))
        try:
            r = requests.get(_robots_url(url), headers=HEADERS, timeout=8, verify=False)
            if r.status_code == 200 and r.text.strip():
                rp.parse(r.text.splitlines())
                _robots_status[host] = "fetched"
            else:
                _robots_status[host] = f"missing_{r.status_code}"
                rp.parse(["User-agent: *", "Allow: /"])
        except Exception as e:
            _robots_status[host] = f"error_{type(e).__name__}"
            rp.parse(["User-agent: *", "Allow: /"])
        _robots_cache[host] = rp
    allowed = rp.can_fetch(UA, url)
    return allowed, "" if allowed else "robots_disallow"


def _respect_rate_limit(host: str) -> None:
    last = _last_request_t.get(host, 0.0)
    now = time.time()
    wait = REQUEST_INTERVAL_S - (now - last)
    if wait > 0:
        time.sleep(wait + random.uniform(0, 0.3))
    _last_request_t[host] = time.time()


def _now_jst_date() -> str:
    return datetime.now(JST).strftime("%Y%m%d")


def _now_jst_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def _sha8(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:8]


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def append_index(record: dict) -> None:
    with CRAWL_INDEX.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def fetch_html(url: str, timeout: int = 15) -> Optional[dict]:
    host = _domain(url)
    if not host:
        return None
    allowed, reason = can_fetch(url)
    if not allowed:
        append_index({"ts_jst": _now_jst_iso(), "url": url, "status": "skipped", "reason": reason})
        return None
    _respect_rate_limit(host)
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, verify=False, allow_redirects=True)
    except Exception as e:
        append_index({"ts_jst": _now_jst_iso(), "url": url, "status": "error", "reason": f"{type(e).__name__}: {str(e)[:80]}"})
        return None
    if r.status_code != 200:
        append_index({"ts_jst": _now_jst_iso(), "url": url, "status": "error", "http_status": r.status_code})
        return None
    ctype = r.headers.get("Content-Type", "")
    body = r.content
    if not body or len(body) < 200:
        append_index({"ts_jst": _now_jst_iso(), "url": url, "status": "empty"})
        return None
    if "text" not in ctype and "html" not in ctype and "xml" not in ctype:
        return None
    sha8 = _sha8(body)
    sha256 = _sha256(body)
    fname = f"{host}_{_now_jst_date()}_{sha8}.html"
    path = RAW_HTML / fname
    if not path.exists():
        if r.encoding and r.encoding.lower() in ("iso-8859-1", "latin-1") and "charset" not in ctype.lower():
            try:
                body.decode("utf-8"); r.encoding = "utf-8"
            except UnicodeDecodeError:
                try:
                    body.decode("gbk"); r.encoding = "gbk"
                except UnicodeDecodeError:
                    pass
        try:
            path.write_text(r.text, encoding="utf-8", errors="replace")
        except Exception:
            path.write_bytes(body)
    rec = {
        "ts_jst": _now_jst_iso(),
        "url": url,
        "final_url": r.url,
        "domain": host,
        "status": "ok",
        "http_status": r.status_code,
        "content_type": ctype,
        "bytes": len(body),
        "sha256": sha256,
        "sha8": sha8,
        "html_path": str(path.relative_to(PROJECT_ROOT)),
    }
    append_index(rec)
    return rec


def fetch_pdf(url: str, timeout: int = 30) -> Optional[dict]:
    host = _domain(url)
    if not host:
        return None
    allowed, reason = can_fetch(url)
    if not allowed:
        append_index({"ts_jst": _now_jst_iso(), "url": url, "status": "skipped", "reason": reason, "kind": "pdf"})
        return None
    _respect_rate_limit(host)
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, verify=False, allow_redirects=True)
    except Exception as e:
        append_index({"ts_jst": _now_jst_iso(), "url": url, "status": "error", "kind": "pdf", "reason": f"{type(e).__name__}: {str(e)[:80]}"})
        return None
    if r.status_code != 200:
        append_index({"ts_jst": _now_jst_iso(), "url": url, "status": "error", "kind": "pdf", "http_status": r.status_code})
        return None
    body = r.content
    if not body[:4].startswith(b"%PDF"):
        return None
    sha8 = _sha8(body); sha256 = _sha256(body)
    fname = f"{host}_{_now_jst_date()}_{sha8}.pdf"
    path = RAW_PDF / fname
    if not path.exists():
        path.write_bytes(body)
    rec = {
        "ts_jst": _now_jst_iso(),
        "url": url,
        "final_url": r.url,
        "domain": host,
        "status": "ok",
        "kind": "pdf",
        "bytes": len(body),
        "sha256": sha256,
        "sha8": sha8,
        "pdf_path": str(path.relative_to(PROJECT_ROOT)),
    }
    append_index(rec)
    return rec


def is_official(host: str) -> int:
    h = (host or "").lower()
    if h in OFFICIAL_HOSTS:
        return 1
    return int(any(h.endswith(t) for t in OFFICIAL_TLDS))


def brave_search(query: str, count: int = 20, offset: int = 0, freshness: Optional[str] = None) -> list[dict]:
    key = os.environ.get("BRAVE_API_KEY", "BSA5JKAPj6u6qyLS4kj_wv4BVh2dUSZ")
    headers = {"Accept": "application/json", "X-Subscription-Token": key}
    params = {"q": query, "count": min(count, 20), "offset": offset, "country": "CN", "search_lang": "zh-hans"}
    if freshness:
        params["freshness"] = freshness
    time.sleep(1.1)
    try:
        r = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=15)
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


def robots_status_snapshot() -> dict:
    return dict(_robots_status)
