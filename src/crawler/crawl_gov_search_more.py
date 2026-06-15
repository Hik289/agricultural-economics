"""Second-pass keyword expansion to push case count above 200."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import brave_search, fetch_html, LOG_DIR  # noqa: E402

EXTRA_QUERIES = [
    # 5-province batch hunt for typical-case PDFs
    "site:zj.gov.cn 生态产品价值实现 典型案例",
    "site:fujian.gov.cn 生态产品价值实现 典型案例",
    "site:jiangxi.gov.cn 生态产品价值实现 典型案例",
    "site:sichuan.gov.cn 生态产品价值实现 典型案例",
    "site:gz.gov.cn 生态产品价值实现 典型案例",
    "site:ah.gov.cn 生态产品价值实现 典型案例",
    "site:yn.gov.cn 生态产品价值实现 典型案例",
    "site:gd.gov.cn 生态产品价值实现 典型案例",
    "site:hunan.gov.cn 生态产品价值实现 典型案例",
    "site:hubei.gov.cn 生态产品价值实现 典型案例",
    "site:hebei.gov.cn 生态产品价值实现 典型案例",
    "site:shandong.gov.cn 生态产品价值实现 典型案例",
    "site:hainan.gov.cn 生态产品价值实现 典型案例",
    "site:shaanxi.gov.cn 生态产品价值实现 典型案例",
    "site:gov.cn 林票制度 试点",
    "site:gov.cn 碳汇 林农 受益",
    "site:gov.cn 农村集体经济 生态资源",
    "site:gov.cn 共同富裕 生态产品价值",
    "site:gov.cn 横向生态补偿 流域",
    "site:gov.cn 生态产品 价值实现 浙江丽水",
    "site:gov.cn 生态产品 价值实现 武夷山",
    "site:gov.cn 生态产品 价值实现 三江源",
    "site:gov.cn 生态产品 价值实现 典型 农业农村",
    "site:gov.cn 自然资源部 推荐 典型案例 生态产品",
    "site:gov.cn 典型案例 生态系统 服务付费",
]
DETAIL_RE = re.compile(r"(t20\d{6}_\d+|\.html?$|\.shtml$|case|dianxing|anli)", re.I)
PDF_RE = re.compile(r"\.pdf(\?|$)", re.I)


def main() -> int:
    log: list[str] = []
    page_cands: dict[str, str] = {}
    pdf_cands: dict[str, str] = {}
    for q in EXTRA_QUERIES:
        res = brave_search(q, count=20)
        log.append(f"[query] {q}  -> {len(res)} hits")
        for r in res:
            u = r["url"]; host = r["host"]
            if not (host.endswith(".gov.cn") or host.endswith(".agri.cn") or host.endswith(".org.cn")):
                continue
            if PDF_RE.search(u):
                pdf_cands[u] = r["title"]
            elif DETAIL_RE.search(u):
                page_cands[u] = r["title"]
    log.append(f"=== found {len(page_cands)} pages, {len(pdf_cands)} pdfs ===")
    fetched = 0
    for u, title in page_cands.items():
        rec = fetch_html(u)
        if rec:
            fetched += 1
            log.append(f"[page-ok] {u}")
        else:
            log.append(f"[page-skip] {u}")
    # merge PDFs into the queue file
    queue_path = Path("/home/user/projects/epvr-replication/data/_pdf_queue_from_search.jsonl")
    with queue_path.open("a", encoding="utf-8") as f:
        for u, title in pdf_cands.items():
            f.write(json.dumps({"url": u, "title": title}, ensure_ascii=False) + "\n")
    (LOG_DIR / "crawl_gov_search_more.log").write_text("\n".join(log), encoding="utf-8")
    print(f"crawl_gov_search_more: queries={len(EXTRA_QUERIES)} pages_fetched={fetched} pdf_queue+={len(pdf_cands)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
