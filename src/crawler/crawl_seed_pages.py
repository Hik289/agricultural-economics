"""Crawl spec §3.1.1 seed pages and their immediate case-list children.

Strategy:
1. Hit the 5 listed seed URLs directly.
2. For mnr.gov.cn, mee.gov.cn, gov.cn we treat them as roots; we use the
   on-page links that look like EPVR/典型案例/生态产品价值实现 detail pages and
   recurse one level.
3. We do NOT spider broadly — only links whose anchor text or URL matches
   EPVR / GEP / 生态银行 / 林票 / 碳汇 / 流域补偿 / 生态旅游 / 绿色金融 /
   典型案例 keywords (spec §3.1.1).
"""
from __future__ import annotations
import re
import sys
import urllib.parse as up
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    fetch_html,
    LOG_DIR,
    is_official,
)

SEED_URLS = [
    "https://www.reea.agri.cn/lsfzpj/202502/t20250227_8715235.htm",
    "https://www.hunan.gov.cn/zqt/zcsd/202602/t20260206_33911711.html",
    "https://www.mnr.gov.cn/",
    "https://www.mee.gov.cn/",
    "https://www.stats.gov.cn/sj/ndsj/",
]

# Topic-related anchor-text keywords (Chinese only matters for these sites).
KEYWORD_RE = re.compile(
    r"(生态产品|价值实现|典型案例|GEP|生态银行|林票|碳汇|流域补偿|"
    r"生态旅游|绿色金融|生态保护补偿|生态修复|EPVR|生态资源|"
    r"农业生态产品|农户分红|村集体|绿色农产品)"
)

# Don't expand into non-Chinese-mainland or clearly off-topic domains.
ALLOWED_TLD_RE = re.compile(r"\.(gov\.cn|org\.cn|edu\.cn|cn)$")


def _is_candidate_link(href: str, text: str) -> bool:
    if not href:
        return False
    if href.startswith("javascript:"):
        return False
    target = (text or "") + " " + href
    return bool(KEYWORD_RE.search(target))


def _absolutize(base: str, href: str) -> str:
    return up.urljoin(base, href)


def _extract_children(base_url: str, html: str) -> list[str]:
    out: list[str] = []
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        if not _is_candidate_link(href, text):
            continue
        abs_url = _absolutize(base_url, href)
        host = up.urlparse(abs_url).netloc.lower()
        if not host or not ALLOWED_TLD_RE.search(host):
            continue
        # only follow detail-like pages (have a year segment or `.html` /`.htm`)
        if not re.search(r"(\.html?$|\.shtml$|20\d{2}/|t20\d{6}_\d+)", abs_url):
            continue
        out.append(abs_url)
    # de-dup while keeping order
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def main() -> int:
    log = []
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(u, 0) for u in SEED_URLS]
    fetched_pages: list[dict] = []
    MAX_DEPTH = 2
    MAX_FETCH = 200  # for this script alone

    while queue and len(fetched_pages) < MAX_FETCH:
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        rec = fetch_html(url)
        if rec:
            rec["depth"] = depth
            rec["official"] = is_official(rec["domain"])
            fetched_pages.append(rec)
            log.append(f"[ok depth={depth}] {url}  ({rec['bytes']}B)")
            # follow children
            if depth < MAX_DEPTH:
                try:
                    html_text = Path("/home/user/projects/epvr-replication" + "/" + rec["html_path"]).read_text(encoding="utf-8", errors="replace")
                except Exception:
                    html_text = ""
                children = _extract_children(rec.get("final_url", url), html_text)
                for c in children[:30]:  # cap per page
                    if c not in visited:
                        queue.append((c, depth + 1))
        else:
            log.append(f"[skip] {url}")

    (LOG_DIR / "crawl_seed_pages.log").write_text("\n".join(log), encoding="utf-8")
    print(f"crawl_seed_pages: fetched={len(fetched_pages)} visited={len(visited)} queue_left={len(queue)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
