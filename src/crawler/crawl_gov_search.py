"""Brave Search → official gov.cn URLs (spec §3.1.1 keyword combinations).

We use the Brave Search API (key in TOOLS.md) to discover candidate URLs for the
11 search-keyword combinations.  We then hand the URLs back to fetch_html(),
which honors robots.txt and the 2-second interval.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import brave_search, fetch_html, LOG_DIR  # noqa: E402

SEARCH_QUERIES = [
    "site:mnr.gov.cn 生态产品价值实现 典型案例",
    "site:mnr.gov.cn 生态产品价值实现 第六批",
    "site:mnr.gov.cn 生态产品价值实现 第五批",
    "site:mnr.gov.cn 生态产品价值实现 第四批",
    "site:reea.agri.cn 农业生态产品价值实现 典型案例",
    "site:gov.cn 生态产品价值实现 典型案例 农户 分红",
    "site:gov.cn 生态产品价值实现 村集体 增收",
    "site:gov.cn 生态产品价值实现 合作社 农户",
    "site:gov.cn 生态产品价值实现 生态岗位",
    "site:gov.cn 生态产品价值实现 绿色金融 农户",
    "site:gov.cn 生态产品价值实现 林票",
    "site:gov.cn 生态产品价值实现 碳汇 农户",
    "site:gov.cn 生态产品价值实现 地票 农户",
    # extra queries with stronger case-detail signal
    "site:gov.cn 生态产品价值实现 典型案例 流域补偿",
    "site:gov.cn 生态产品价值实现 典型案例 生态旅游 村",
    "site:gov.cn 生态银行 林票 典型案例",
    "site:mee.gov.cn 生态产品价值实现 典型案例",
    "site:moa.gov.cn 农业生态 典型案例 价值实现",
    "site:moa.gov.cn 绿色农产品 优质优价 典型案例",
    "生态产品价值实现 典型案例 县 农户分红 site:gov.cn",
    "生态产品价值实现 典型案例 村集体 分红 site:gov.cn",
]

# heuristic: detail URLs look like /t2024nnnn_*.html or include year + numeric id
DETAIL_RE = re.compile(r"(t20\d{6}_\d+|\.html?$|\.shtml$|20\d{2}/.*\d{6,}|case|dianxing|anli)", re.I)
PDF_RE = re.compile(r"\.pdf(\?|$)", re.I)


def main() -> int:
    log: list[str] = []
    candidates_pages: dict[str, str] = {}
    candidates_pdfs: dict[str, str] = {}
    for q in SEARCH_QUERIES:
        res = brave_search(q, count=20)
        log.append(f"[query] {q}  -> {len(res)} hits")
        for r in res:
            u = r["url"]
            host = r["host"]
            if not host.endswith(".gov.cn") and host != "":
                # also accept org.cn for the agri sub-bureau
                if not host.endswith(".agri.cn"):
                    continue
            if PDF_RE.search(u):
                candidates_pdfs[u] = r["title"]
            elif DETAIL_RE.search(u):
                candidates_pages[u] = r["title"]
    log.append(f"=== found {len(candidates_pages)} page candidates, {len(candidates_pdfs)} pdf candidates ===")

    fetched = 0
    for u, title in candidates_pages.items():
        rec = fetch_html(u)
        if rec:
            fetched += 1
            log.append(f"[page-ok] {u}  ({rec['bytes']}B)  title={title[:60]}")
        else:
            log.append(f"[page-skip] {u}")

    # PDF candidates → for download_pdfs.py.  Persist URLs to disk.
    pdf_queue_path = Path("/home/user/projects/epvr-replication/data/_pdf_queue_from_search.jsonl")
    with pdf_queue_path.open("w", encoding="utf-8") as f:
        for u, title in candidates_pdfs.items():
            f.write(json.dumps({"url": u, "title": title}, ensure_ascii=False) + "\n")

    (LOG_DIR / "crawl_gov_search.log").write_text("\n".join(log), encoding="utf-8")
    print(f"crawl_gov_search: queries={len(SEARCH_QUERIES)} pages_fetched={fetched} pdf_queue={len(candidates_pdfs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
