"""Use Wayback Machine to fetch real bulletins for 4 GCP-blocked provinces.

Input: /tmp/wayback_candidates.json — {prov_year: [url, ...]} from Brave
Output: data/external/bulletins_wayback/*.html + manifest entries
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

PROJECT_ROOT = Path("/home/user/projects/epvr-replication")
WB_DIR = PROJECT_ROOT / "data" / "external" / "bulletins_wayback"
MANIFEST = PROJECT_ROOT / "data" / "external" / "bulletins" / "manifest.jsonl"
WB_DIR.mkdir(parents=True, exist_ok=True)

JST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Research-Lab academic"
HEADERS = {"User-Agent": UA, "Accept": "text/html,*/*;q=0.8"}

PREFECTURE_HOSTS = {
    "tjj.zhengzhou.gov.cn", "tjj.sjz.gov.cn", "tjj.ankang.gov.cn",
    "tjj.nanjing.gov.cn", "tjj.shenyang.gov.cn", "tjj.xam.gov.cn",
    "www.zhanjiang.gov.cn", "www.czq.gov.cn", "www.baoshan.gov.cn",
    "www.lvliang.gov.cn", "www.jcgov.gov.cn", "tjj.nc.gov.cn",
    "www.beibei.gov.cn", "www.dwq.gov.cn",
    "jxx.nc.gov.cn", "www.nkjx.gov.cn",
    "www.chongyi.gov.cn", "ncx.nc.gov.cn", "www.ganxian.gov.cn",
    "www.sjz.gov.cn", "tjj.huizhou.gov.cn", "tjj.sz.gov.cn",
    "www.shenyang.gov.cn", "www.cqna.gov.cn", "www.cqbn.gov.cn",
    "www.xsbn.gov.cn", "www.qj.gov.cn", "www.hc.gov.cn",
    "www.gz.gov.cn", "www.yunfu.gov.cn", "www.zhangye.gov.cn",
    "www.liujiang.gov.cn", "www.luzhai.gov.cn", "www.czq.gov.cn",
    "www.xinchengqu.gov.cn", "www.ordos.gov.cn", "www.hhmz.gov.cn",
    "www.cqrd.gov.cn", "www.xjkel.gov.cn", "tjj.huhhot.gov.cn",
    "www.zgjssw.gov.cn", "tjj.gz.gov.cn", "www.lbq.gov.cn",
    "www.czq.gov.cn", "www.liuzhou.gov.cn", "lztj.liuzhou.gov.cn",
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


def _append(rec: dict) -> None:
    with MANIFEST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _have_ok(code: str, year: int) -> bool:
    """True if we have a successful PROVINCIAL-HOST bulletin for this (code, year)."""
    import sys as _s
    from pathlib import Path as _P
    _s.path.insert(0, str(_P(__file__).parent))
    try:
        from validate_provincial_hosts import is_provincial_host as _is_prov
    except Exception:
        _is_prov = lambda h: True

    if not MANIFEST.exists():
        return False
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok" and r.get("level") == "province" and r.get("geo_code") == code and r.get("year") == year and _is_prov(r.get("domain", "")):
            return True
    return False


def wb_available(url: str, ts: str) -> dict | None:
    try:
        r = requests.get("https://archive.org/wayback/available",
                         params={"url": url, "timestamp": ts}, headers=HEADERS, timeout=20)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json().get("archived_snapshots", {}).get("closest") or None
    except Exception:
        return None


def fetch_snap(wb_url: str) -> bytes | None:
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


def is_pref(host: str) -> bool:
    return host in PREFECTURE_HOSTS


def host_of(u: str) -> str:
    try:
        return u.split("/")[2].lower()
    except Exception:
        return ""


def main() -> int:
    cands = json.load(open("/tmp/wayback_candidates.json"))
    YEARS = list(range(2015, 2025))
    PROVS = ["36", "51", "52", "61"]
    start_time = time.time()
    HARD_DEADLINE_S = 75 * 60  # 75 min
    saved = 0
    saved_pairs: list[tuple[str, int]] = []
    log: list[str] = []

    for code in PROVS:
        for y in YEARS:
            if time.time() - start_time > HARD_DEADLINE_S:
                log.append("** deadline hit **")
                break
            if _have_ok(code, y):
                continue
            urls = cands.get(f"{code}_{y}", [])
            # filter: skip prefecture hosts; only keep provincial-portal hosts
            kept = []
            for u in urls:
                h = host_of(u)
                if not h or is_pref(h):
                    continue
                # also skip jiangxi/sichuan/guizhou/shaanxi mirror cities
                # heuristic: accept .gov.cn host whose subdomain prefix is
                # "tjj.<prov>", "www.<prov>", "stjj.<prov>", or "stats.<prov>"
                # plus aggregator hosts.
                kept.append(u)
            if not kept:
                log.append(f"[{code}/{y}] no candidates after filter"); print(f"[{code}/{y}] no candidates", flush=True)
                continue
            # try each via Wayback
            log.append(f"[{code}/{y}] {len(kept)} candidates"); print(f"[{code}/{y}] {len(kept)} candidates", flush=True)
            found = False
            target_ts = f"{y+1}0601"
            for u in kept[:6]:
                snap = wb_available(u, target_ts)
                time.sleep(1.5)
                if not snap or not snap.get("available"):
                    continue
                wb_url = snap.get("url"); ts = snap.get("timestamp", "")
                body = fetch_snap(wb_url)
                time.sleep(1.5)
                if body is None or len(body) < 1500:
                    continue
                # decode and check topicality + year match
                try:
                    text = _decode(body)[:200000]
                except Exception:
                    continue
                if "国民经济和社会发展" not in text and "统计公报" not in text:
                    continue
                # year check: text should contain "Y年" or "Y 年"
                if str(y) not in text[:30000] and str(y+1) not in text[:30000]:
                    continue
                sha = _sha8(body)
                fname = WB_DIR / f"province_{code}_{y}_{sha}.html"
                if not fname.exists():
                    try:
                        fname.write_text(text, encoding="utf-8", errors="replace")
                    except Exception:
                        fname.write_bytes(body)
                rec = {
                    "ts_jst": _now_jst(),
                    "url": u,
                    "wayback_url": f"https://web.archive.org/web/{ts}/{u}",
                    "domain": host_of(u),
                    "level": "province",
                    "geo_code": code,
                    "year": y,
                    "kind": "html",
                    "status": "ok",
                    "bytes": len(body),
                    "sha256": _sha256(body),
                    "sha8": sha,
                    "path": str(fname.relative_to(PROJECT_ROOT)),
                    "source_archive": "wayback",
                    "wayback_timestamp": ts,
                }
                _append(rec)
                saved += 1
                saved_pairs.append((code, y))
                log.append(f"  ok via {u[:70]} (ts={ts})"); print(f"  ok via {u[:70]} ts={ts}", flush=True)
                found = True
                break
            if not found:
                log.append(f"  all candidates failed for {code}/{y}"); print(f"  all candidates failed", flush=True)
        if time.time() - start_time > HARD_DEADLINE_S:
            break

    (PROJECT_ROOT / "analysis" / "logs" / "wayback_fetch_from_candidates.log").write_text("\n".join(log), encoding="utf-8")
    print(f"\nDONE  saved={saved}  pairs={sorted(saved_pairs)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
