"""Find PDF attachments inside crawled HTML and download them.

Sources of PDF URLs:
1. <a href="*.pdf"> inside every HTML in data/raw_html/.
2. The Brave-search candidate queue at data/_pdf_queue_from_search.jsonl.
"""
from __future__ import annotations
import json
import re
import sys
import urllib.parse as up
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from _common import fetch_pdf, LOG_DIR, RAW_HTML, CRAWL_INDEX  # noqa: E402

PDF_HREF_RE = re.compile(r"\.pdf(\?|$)", re.I)


def _read_index_url_for(html_path: str) -> str | None:
    """Find the original source URL for a given saved html file."""
    try:
        with open(CRAWL_INDEX, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("html_path") == html_path:
                    return rec.get("final_url") or rec.get("url")
    except FileNotFoundError:
        pass
    return None


def main() -> int:
    log: list[str] = []
    pdf_urls: dict[str, str] = {}  # url -> origin_html

    # 1) parse HTMLs
    for f in sorted(RAW_HTML.glob("*.html")):
        try:
            html = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = str(f.relative_to(f.parents[2]))
        base_url = _read_index_url_for(rel) or ""
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not PDF_HREF_RE.search(href):
                continue
            abs_url = up.urljoin(base_url, href)
            host = up.urlparse(abs_url).netloc
            if not host:
                continue
            # only follow gov.cn / org.cn / agri.cn pdfs
            if not (host.endswith(".gov.cn") or host.endswith(".org.cn") or host.endswith(".agri.cn")):
                continue
            pdf_urls.setdefault(abs_url, rel)

    # 2) Brave-discovered PDF queue
    queue_path = Path("/home/user/projects/epvr-replication/data/_pdf_queue_from_search.jsonl")
    if queue_path.exists():
        for line in queue_path.read_text(encoding="utf-8").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            u = obj.get("url")
            if u and u not in pdf_urls:
                pdf_urls[u] = "from_brave_search"

    log.append(f"[discovered] {len(pdf_urls)} PDF URLs to attempt")
    fetched = 0
    cap = 200  # avoid runaway
    for u, origin in pdf_urls.items():
        if fetched >= cap:
            break
        rec = fetch_pdf(u)
        if rec:
            fetched += 1
            log.append(f"[ok] {u}  ({rec['bytes']}B)  origin={origin}")
        else:
            log.append(f"[skip] {u}  origin={origin}")
    (LOG_DIR / "download_pdfs.log").write_text("\n".join(log), encoding="utf-8")
    print(f"download_pdfs: discovered={len(pdf_urls)} fetched={fetched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
