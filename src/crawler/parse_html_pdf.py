"""Parse raw HTML / PDF → data/processed/cases_raw.csv (one row per source).

Implements spec §3.1.2 (40+ fields) + §3.1.3 9-class case_type classifier
+ §9.4 dedup + §9.5 quality flags.

Outputs:
    data/processed/cases_raw.csv     -- one row per crawled source
    data/processed/cases_dedup.csv   -- deduplicated case-county-year rows
"""
from __future__ import annotations
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
try:
    import pdfplumber
except Exception:
    pdfplumber = None

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    PROJECT_ROOT,
    RAW_HTML,
    RAW_PDF,
    PROCESSED,
    CRAWL_INDEX,
    is_official,
)

# ---------------------------------------------------------------------------
# Reference tables: GB/T 2260 provinces, simple county detector.
# ---------------------------------------------------------------------------
PROVINCES = {
    "北京": ("11", "Beijing"),
    "天津": ("12", "Tianjin"),
    "河北": ("13", "Hebei"),
    "山西": ("14", "Shanxi"),
    "内蒙古": ("15", "Inner Mongolia"),
    "辽宁": ("21", "Liaoning"),
    "吉林": ("22", "Jilin"),
    "黑龙江": ("23", "Heilongjiang"),
    "上海": ("31", "Shanghai"),
    "江苏": ("32", "Jiangsu"),
    "浙江": ("33", "Zhejiang"),
    "安徽": ("34", "Anhui"),
    "福建": ("35", "Fujian"),
    "江西": ("36", "Jiangxi"),
    "山东": ("37", "Shandong"),
    "河南": ("41", "Henan"),
    "湖北": ("42", "Hubei"),
    "湖南": ("43", "Hunan"),
    "广东": ("44", "Guangdong"),
    "广西": ("45", "Guangxi"),
    "海南": ("46", "Hainan"),
    "重庆": ("50", "Chongqing"),
    "四川": ("51", "Sichuan"),
    "贵州": ("52", "Guizhou"),
    "云南": ("53", "Yunnan"),
    "西藏": ("54", "Tibet"),
    "陕西": ("61", "Shaanxi"),
    "甘肃": ("62", "Gansu"),
    "青海": ("63", "Qinghai"),
    "宁夏": ("64", "Ningxia"),
    "新疆": ("65", "Xinjiang"),
}

PROVINCE_RE = re.compile(
    r"(北京市|天津市|河北省|山西省|内蒙古自治区|辽宁省|吉林省|黑龙江省|上海市|江苏省|浙江省|安徽省|"
    r"福建省|江西省|山东省|河南省|湖北省|湖南省|广东省|广西壮族自治区|海南省|重庆市|四川省|贵州省|"
    r"云南省|西藏自治区|陕西省|甘肃省|青海省|宁夏回族自治区|新疆维吾尔自治区|"
    r"广西|内蒙古|西藏|宁夏|新疆)"
)

# County: greedy match Chinese county names ending in 县/市/区/旗/自治县/自治旗
COUNTY_RE = re.compile(
    r"([\u4e00-\u9fff]{2,8}?(?:县|市|区|旗|自治县|自治旗))"
)

# Year extractor
YEAR_RE = re.compile(r"(20[0-2][0-9])\s*年")
DATE_META_RE = re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})")

# Policy batch
BATCH_RE = re.compile(r"(第[一二三四五六七八九十0-9]+批)")

# ---------------------------------------------------------------------------
# §3.1.3 case-type classifier (rule-based).
# ---------------------------------------------------------------------------
CASE_TYPE_RULES = [
    ("4_carbon_sink_or_ecological_rights", [r"碳汇", r"碳交易", r"林业碳汇", r"碳普惠", r"生态银行", r"林票", r"用能权", r"排污权", r"碳票"]),
    ("5_water_or_watershed_compensation", [r"流域补偿", r"流域生态补偿", r"上下游补偿", r"水权交易", r"跨省补偿", r"饮用水水源", r"湿地保护补偿"]),
    ("6_land_restoration_or_land_quota", [r"土地修复", r"土地整治", r"占补平衡", r"耕地指标", r"地票", r"全域土地综合整治", r"矿山修复"]),
    ("7_green_finance", [r"绿色信贷", r"绿色金融", r"生态保险", r"碳金融", r"绿色债券", r"GEP贷"]),
    ("3_forest_or_understory_economy", [r"林下经济", r"林业碳汇.*林农", r"森林康养", r"经济林", r"竹产业"]),
    ("2_ecological_tourism", [r"生态旅游", r"乡村旅游", r"研学旅游", r"森林旅游", r"康养旅游", r"民宿"]),
    ("1_green_agriculture_premium", [r"优质优价", r"绿色农产品", r"地理标志", r"有机农业", r"品牌溢价", r"订单农业", r"农产品.*品牌"]),
    ("8_village_collective_ecological_asset_operation", [r"村集体.*经营", r"集体经济.*生态", r"村集体.*生态资产"]),
]

# ---------------------------------------------------------------------------
# Data record.
# ---------------------------------------------------------------------------
SOURCE_FIELDS = [
    "case_id", "source_url", "source_domain", "source_title", "source_date",
    "crawl_date", "case_title", "province", "province_code", "prefecture",
    "county", "county_code", "village_or_town", "case_year", "policy_batch",
    "case_type", "case_type_secondary", "ecosystem_service_type",
    "resource_base", "market_channel", "main_operator", "farmer_participation",
    "village_collective_role", "cooperative_role", "firm_role", "government_role",
    "reported_households_benefiting", "reported_jobs_created",
    "reported_household_income_gain", "reported_collective_income_gain",
    "reported_total_project_income", "reported_dividend_amount",
    "reported_land_rent", "reported_ecological_compensation",
    "reported_green_finance_amount", "reported_carbon_sink_amount",
    "reported_tourism_income", "amount_original_string", "raw_text",
    "pdf_path", "html_path", "source_hash",
    "quality_official_source", "quality_has_county", "quality_has_year",
    "quality_has_pdf", "quality_has_income_amount",
]


@dataclass
class CaseRow:
    case_id: str = ""
    source_url: str = "NA_NOT_REPORTED"
    source_domain: str = "NA_NOT_REPORTED"
    source_title: str = "NA_NOT_REPORTED"
    source_date: str = "NA_NOT_REPORTED"
    crawl_date: str = "NA_NOT_REPORTED"
    case_title: str = "NA_NOT_REPORTED"
    province: str = "NA_UNRESOLVED"
    province_code: str = "NA_UNRESOLVED"
    prefecture: str = "NA_UNRESOLVED"
    county: str = "NA_UNRESOLVED"
    county_code: str = "NA_UNRESOLVED"
    village_or_town: str = "NA_NOT_REPORTED"
    case_year: str = "NA_UNRESOLVED"
    policy_batch: str = "NA_NOT_REPORTED"
    case_type: str = "NA_UNRESOLVED"
    case_type_secondary: str = "NA_NOT_APPLICABLE"
    ecosystem_service_type: str = "NA_NOT_REPORTED"
    resource_base: str = "NA_NOT_REPORTED"
    market_channel: str = "NA_NOT_REPORTED"
    main_operator: str = "NA_NOT_REPORTED"
    farmer_participation: str = "NA_NOT_REPORTED"
    village_collective_role: str = "NA_NOT_REPORTED"
    cooperative_role: str = "NA_NOT_REPORTED"
    firm_role: str = "NA_NOT_REPORTED"
    government_role: str = "NA_NOT_REPORTED"
    reported_households_benefiting: str = "NA_NOT_REPORTED"
    reported_jobs_created: str = "NA_NOT_REPORTED"
    reported_household_income_gain: str = "NA_NOT_REPORTED"
    reported_collective_income_gain: str = "NA_NOT_REPORTED"
    reported_total_project_income: str = "NA_NOT_REPORTED"
    reported_dividend_amount: str = "NA_NOT_REPORTED"
    reported_land_rent: str = "NA_NOT_REPORTED"
    reported_ecological_compensation: str = "NA_NOT_REPORTED"
    reported_green_finance_amount: str = "NA_NOT_REPORTED"
    reported_carbon_sink_amount: str = "NA_NOT_REPORTED"
    reported_tourism_income: str = "NA_NOT_REPORTED"
    amount_original_string: str = "NA_NOT_REPORTED"
    raw_text: str = ""
    pdf_path: str = "NA_NOT_APPLICABLE"
    html_path: str = "NA_NOT_APPLICABLE"
    source_hash: str = ""
    quality_official_source: int = 0
    quality_has_county: int = 0
    quality_has_year: int = 0
    quality_has_pdf: int = 0
    quality_has_income_amount: int = 0


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _extract_html_text(html: str) -> tuple[str, str, str]:
    """Return (title, publish_date_str_or_NA, body_text)."""
    soup = BeautifulSoup(html, "html.parser")
    # title
    title_tag = soup.find("title")
    title = _clean_text(title_tag.get_text()) if title_tag else ""
    h1 = soup.find(["h1", "h2"])
    if h1:
        h1_txt = _clean_text(h1.get_text())
        if h1_txt and len(h1_txt) > 4:
            title = h1_txt or title
    # publish date — look for meta or first date in body
    pub_date = ""
    for meta in soup.find_all("meta"):
        nm = (meta.get("name") or "").lower()
        if nm in ("pubdate", "publishdate", "publish_date", "date", "article:published_time"):
            pub_date = meta.get("content", "")
            break
    body = ""
    # try main article tags
    for tag in ("article", "main"):
        node = soup.find(tag)
        if node:
            body = _clean_text(node.get_text(" "))
            break
    if not body:
        # remove scripts/styles
        for s in soup(["script", "style", "noscript"]):
            s.decompose()
        body = _clean_text(soup.get_text(" "))
    if not pub_date:
        m = DATE_META_RE.search(body[:2000])
        if m:
            y, mo, d = m.groups()
            pub_date = f"{y}-{int(mo):02d}-{int(d):02d}"
    return title, pub_date or "NA_NOT_REPORTED", body


def _extract_pdf_text(path: Path) -> str:
    if pdfplumber is None:
        return ""
    try:
        with pdfplumber.open(str(path)) as pdf:
            chunks = []
            for page in pdf.pages[:60]:  # cap pages
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                if t:
                    chunks.append(t)
            return _clean_text("\n".join(chunks))
    except Exception:
        return ""


def _detect_province(text: str) -> tuple[str, str]:
    """Return (province_name_zh, GB/T 2-digit code) or ('NA_UNRESOLVED', 'NA_UNRESOLVED')."""
    m = PROVINCE_RE.search(text)
    if not m:
        return "NA_UNRESOLVED", "NA_UNRESOLVED"
    raw = m.group(1)
    # normalize to bare province name
    for k in PROVINCES.keys():
        if raw.startswith(k):
            return k + ("市" if PROVINCES[k][0] in {"11", "12", "31", "50"} else "省" if PROVINCES[k][0] not in {"15", "45", "54", "64", "65"} else "自治区"), PROVINCES[k][0]
    return "NA_UNRESOLVED", "NA_UNRESOLVED"


def _detect_county(text: str, province_zh: str) -> str:
    """Crude detector: first county/city/district token in the first 2000 chars
    that is not the same as the province name."""
    window = text[:3000]
    for m in COUNTY_RE.finditer(window):
        cand = m.group(1)
        # skip provincial-level matches
        if cand in {province_zh}:
            continue
        if cand.endswith(("省", "市")) and len(cand) <= 4 and cand[:-1] in PROVINCES:
            continue
        # skip generic placeholder
        if cand in {"本市", "本区", "本县", "城市", "我市", "我县"}:
            continue
        return cand
    return "NA_UNRESOLVED"


def _detect_year(text: str) -> str:
    m = YEAR_RE.search(text[:5000])
    if m:
        y = int(m.group(1))
        if 2000 <= y <= 2030:
            return str(y)
    # fall back to first 4-digit year
    m = re.search(r"\b(20[0-2]\d)\b", text[:5000])
    if m:
        return m.group(1)
    return "NA_UNRESOLVED"


def _detect_batch(text: str) -> str:
    m = BATCH_RE.search(text[:5000])
    return m.group(1) if m else "NA_NOT_REPORTED"


def _classify_case_type(text: str) -> tuple[str, str]:
    """Return (primary, secondary_or_NA)."""
    hits = []
    for code, patterns in CASE_TYPE_RULES:
        score = 0
        for p in patterns:
            if re.search(p, text):
                score += 1
        if score:
            hits.append((score, code))
    if not hits:
        return "NA_UNRESOLVED", "NA_NOT_APPLICABLE"
    hits.sort(reverse=True)
    primary = hits[0][1]
    if len(hits) >= 2 and hits[1][0] >= 1:
        # mixed model when at least 3 strong hits or top two have similar scores
        if len(hits) >= 3 or (hits[0][0] == hits[1][0]):
            return "9_mixed_model", primary
    if len(hits) >= 3:
        return "9_mixed_model", primary
    return primary, hits[1][1] if len(hits) >= 2 else "NA_NOT_APPLICABLE"


# Amount detector (yuan / 万元 / 亿元)
AMOUNT_RE = re.compile(r"((?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?))\s*(亿元|万元|元)")


def _detect_any_amount(text: str) -> int:
    return int(bool(AMOUNT_RE.search(text)))


# Households / jobs
HOUSEHOLDS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(户|户人家|户农户)")
JOBS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:个)?(?:就业岗位|生态岗位|公益岗位|岗位)")


def _detect_number(text: str, pattern: re.Pattern) -> str:
    m = pattern.search(text)
    return m.group(1) if m else "NA_NOT_REPORTED"


def _load_index() -> dict[str, dict]:
    """Map file_path (rel) -> latest index record."""
    idx: dict[str, dict] = {}
    if not CRAWL_INDEX.exists():
        return idx
    for line in CRAWL_INDEX.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        for k in ("html_path", "pdf_path"):
            if rec.get(k):
                idx[rec[k]] = rec
    return idx


# ---------------------------------------------------------------------------
# Main parse.
# ---------------------------------------------------------------------------

def _row_from_html(path: Path, index: dict) -> Optional[CaseRow]:
    rel = str(path.relative_to(PROJECT_ROOT))
    meta = index.get(rel, {})
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    if "<html" not in html.lower() and "<body" not in html.lower() and len(html) < 500:
        return None
    title, pub_date, body = _extract_html_text(html)
    if len(body) < 300:
        return None
    # very short bodies are not case texts
    if "生态产品价值实现" not in body and "典型案例" not in body and "生态保护补偿" not in body \
       and "生态银行" not in body and "林票" not in body and "碳汇" not in body \
       and "流域补偿" not in body and "生态补偿" not in body and "村集体" not in body:
        # not topical at all
        return None

    prov_zh, prov_code = _detect_province(body)
    county = _detect_county(body, prov_zh)
    year = _detect_year(body)
    batch = _detect_batch(body)
    ctype, ctype2 = _classify_case_type(body)
    amt_str = AMOUNT_RE.search(body)
    amount_original = amt_str.group(0) if amt_str else "NA_NOT_REPORTED"

    domain = meta.get("domain") or path.name.split("_")[0]

    row = CaseRow(
        source_url=meta.get("final_url") or meta.get("url") or "NA_NOT_REPORTED",
        source_domain=domain,
        source_title=title or "NA_NOT_REPORTED",
        source_date=pub_date,
        crawl_date=meta.get("ts_jst", "NA_NOT_REPORTED")[:10],
        case_title=title or "NA_NOT_REPORTED",
        province=prov_zh,
        province_code=prov_code,
        county=county,
        case_year=year,
        policy_batch=batch,
        case_type=ctype,
        case_type_secondary=ctype2,
        reported_households_benefiting=_detect_number(body, HOUSEHOLDS_RE),
        reported_jobs_created=_detect_number(body, JOBS_RE),
        amount_original_string=amount_original,
        raw_text=body[:8000],
        html_path=rel,
        source_hash=meta.get("sha256", hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest()),
    )
    row.quality_official_source = is_official(domain)
    row.quality_has_county = int(row.county != "NA_UNRESOLVED")
    row.quality_has_year = int(row.case_year != "NA_UNRESOLVED")
    row.quality_has_pdf = 0
    row.quality_has_income_amount = _detect_any_amount(body)
    row.case_id = "C_" + row.source_hash[:12]
    return row


def _row_from_pdf(path: Path, index: dict) -> Optional[CaseRow]:
    rel = str(path.relative_to(PROJECT_ROOT))
    meta = index.get(rel, {})
    body = _extract_pdf_text(path)
    if len(body) < 300:
        return None
    if "生态产品价值实现" not in body and "典型案例" not in body and "生态补偿" not in body and "林票" not in body and "碳汇" not in body:
        return None
    prov_zh, prov_code = _detect_province(body)
    county = _detect_county(body, prov_zh)
    year = _detect_year(body)
    batch = _detect_batch(body)
    ctype, ctype2 = _classify_case_type(body)
    amt_str = AMOUNT_RE.search(body)
    amount_original = amt_str.group(0) if amt_str else "NA_NOT_REPORTED"
    domain = meta.get("domain") or path.name.split("_")[0]
    # title: first non-empty line
    first_lines = [l for l in body.split("\n") if l.strip()][:5]
    title = first_lines[0] if first_lines else "NA_NOT_REPORTED"

    row = CaseRow(
        source_url=meta.get("final_url") or meta.get("url") or "NA_NOT_REPORTED",
        source_domain=domain,
        source_title=title[:200],
        source_date=meta.get("ts_jst", "NA_NOT_REPORTED")[:10],
        crawl_date=meta.get("ts_jst", "NA_NOT_REPORTED")[:10],
        case_title=title[:200],
        province=prov_zh,
        province_code=prov_code,
        county=county,
        case_year=year,
        policy_batch=batch,
        case_type=ctype,
        case_type_secondary=ctype2,
        reported_households_benefiting=_detect_number(body, HOUSEHOLDS_RE),
        reported_jobs_created=_detect_number(body, JOBS_RE),
        amount_original_string=amount_original,
        raw_text=body[:8000],
        pdf_path=rel,
        source_hash=meta.get("sha256", hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()),
    )
    row.quality_official_source = is_official(domain)
    row.quality_has_county = int(row.county != "NA_UNRESOLVED")
    row.quality_has_year = int(row.case_year != "NA_UNRESOLVED")
    row.quality_has_pdf = 1
    row.quality_has_income_amount = _detect_any_amount(body)
    row.case_id = "C_" + row.source_hash[:12]
    return row


def _dedup_key(r: CaseRow) -> str:
    # spec §9.4
    title = re.sub(r"[\s\W]+", "", r.case_title)[:40]
    return f"{title}|{r.province}|{r.county}|{r.policy_batch}"


def main() -> int:
    index = _load_index()
    rows: list[CaseRow] = []

    # HTML
    for f in sorted(RAW_HTML.glob("*.html")):
        r = _row_from_html(f, index)
        if r is not None:
            rows.append(r)
    # PDF
    for f in sorted(RAW_PDF.glob("*.pdf")):
        r = _row_from_pdf(f, index)
        if r is not None:
            rows.append(r)

    # Write cases_raw.csv (one row per source).
    raw_csv = PROCESSED / "cases_raw.csv"
    with raw_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SOURCE_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            d = asdict(r)
            # truncate raw_text in the CSV (keep full version in cases_bsi.csv tied to evidence)
            d["raw_text"] = d["raw_text"][:2500]
            w.writerow(d)

    # Dedup.
    # Prefer official sources / sources with PDFs / longer raw text.
    by_key: dict[str, CaseRow] = {}
    for r in rows:
        k = _dedup_key(r)
        if k not in by_key:
            by_key[k] = r
            continue
        cur = by_key[k]
        # pick the better one
        score_r = (r.quality_official_source, r.quality_has_pdf, len(r.raw_text))
        score_c = (cur.quality_official_source, cur.quality_has_pdf, len(cur.raw_text))
        if score_r > score_c:
            by_key[k] = r

    dedup_rows = list(by_key.values())
    dedup_csv = PROCESSED / "cases_dedup.csv"
    with dedup_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SOURCE_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in dedup_rows:
            d = asdict(r)
            d["raw_text"] = d["raw_text"][:2500]
            w.writerow(d)

    print(f"parse_html_pdf: raw_rows={len(rows)} dedup_rows={len(dedup_rows)}")
    print(f"  -> {raw_csv}")
    print(f"  -> {dedup_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
