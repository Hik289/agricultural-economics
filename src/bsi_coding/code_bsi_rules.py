"""Rule-based BSI coder.

For each case row in data/processed/cases_dedup.csv compute the 9 positive +
3 capture-risk BSI indicators using deterministic Chinese keyword rules
(see docs/coding_protocol.md §2-3).  Each fired indicator records the
matching sentence as evidence.

Output: data/processed/cases_bsi_rules.csv with the 12 indicators, evidence
sentences, and the composite BSI_raw/capture_risk/BSI_net.
"""
from __future__ import annotations
import csv
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path("/home/user/projects/epvr-replication")
PROCESSED = PROJECT_ROOT / "data" / "processed"

# Each rule is (indicator, list_of_(positive_regex, negative_regex_or_None)).
# A rule fires when any positive regex matches AND no negative regex matches in
# the same sentence.  Multiple regexes increase confidence.
POSITIVE_RULES: dict[str, list[tuple[str, str | None]]] = {
    "farmer_dividend": [
        (r"农户分红", None),
        (r"农户.{0,12}分红", None),
        (r"入股分红", None),
        (r"股金收益", None),
        (r"利润.{0,4}返还.{0,4}农户", None),
        (r"户均分红", None),
        (r"农民.{0,8}股东.{0,15}(分红|股息|收益)", None),
        (r"分红.{0,15}(户|家庭|农户)", None),
        (r"按股分红.{0,15}(农户|村民|社员)", None),
    ],
    "collective_dividend": [
        (r"村集体.{0,15}(分红|收益|分配|返还)", None),
        (r"集体经济.{0,12}(收益|分配|分红)", None),
        (r"集体收入.{0,15}(公共|民生|福利|分配)", None),
        (r"村集体.{0,15}用于.{0,10}(养老|教育|基础设施|公共)", None),
    ],
    "cooperative_participation": [
        (r"农民.{0,2}专业.{0,2}合作社", None),
        (r"合作社.{0,15}(社员|成员).{0,15}(分红|收益|参与|入股)", None),
        (r"合作社.{0,12}(主导|牵头|带动).{0,12}(农户|村民|社员)", None),
        (r"农民合作社.{0,15}(经营|运营|管理)", None),
    ],
    "eco_job": [
        (r"生态(管护|管理|护林|巡护|保护)员", None),
        (r"生态岗位", None),
        (r"公益.?岗位", None),
        (r"森林管护员", None),
        (r"护林员", None),
        (r"巡护员", None),
        (r"管护.{0,4}岗位", None),
        (r"就业.{0,8}(村民|农户).{0,8}(生态|旅游|护林)", None),
    ],
    "guaranteed_purchase": [
        (r"保底.?收购", None),
        (r"订单农业", None),
        (r"优质优价", None),
        (r"溢价.{0,8}(收购|销售)", None),
        (r"最低.?(收购|保护)价", None),
        (r"地理标志.{0,15}(品牌|溢价|增值)", None),
    ],
    "land_or_resource_rent": [
        (r"土地.{0,4}流转.{0,8}(租金|租赁|租)", None),
        (r"林地.{0,4}租金", None),
        (r"水域.{0,4}租金", None),
        (r"租金.{0,4}(支付|发放).{0,4}(农户|村民|集体)", None),
        (r"流转费.{0,8}(农户|村民|集体)", None),
        (r"宅基地.{0,4}(出租|租赁|入股)", None),
        (r"资源.?使用费.{0,8}(农户|村民|集体)", None),
    ],
    "eco_compensation": [
        (r"生态.?(保护)?补偿.{0,15}(农户|村民|集体|村)", None),
        (r"生态.?补偿.{0,15}(资金|款|金).{0,8}(发放|支付)", None),
        (r"流域.?(横向)?(生态)?补偿.{0,15}(农户|村|集体|乡镇)", None),
        (r"退耕还林.{0,8}(补助|补贴|补偿)", None),
        (r"公益林.{0,15}(补偿|补助)", None),
    ],
    "poverty_or_low_income_targeting": [
        (r"低收入.{0,4}(农户|家庭|户)", None),
        (r"脱贫.?(户|户家|户人家)", None),
        (r"建档立卡.{0,4}(户|贫困户)", None),
        (r"贫困户.{0,12}(优先|帮扶|带动|分红)", None),
        (r"易地搬迁.{0,15}(农户|户)", None),
        (r"残疾.{0,2}户", None),
    ],
    "green_credit_inclusion": [
        (r"绿色信贷.{0,15}(农户|合作社|村)", None),
        (r"GEP.?贷|碳汇贷|林权抵押贷|生态贷", None),
        (r"普惠.{0,4}金融.{0,8}(农户|村民|小农)", None),
        (r"农业保险.{0,15}(生态|绿色|农户)", None),
        (r"生态.?资产.?抵押.{0,8}(贷款|融资)", None),
    ],
}

NEGATIVE_RULES: dict[str, list[tuple[str, str | None]]] = {
    "firm_dominated_no_distribution": [
        # fires when a firm/scenic operator/platform is the operator
        # AND no positive sharing signal is present (we evaluate that
        # at the case level, not the sentence level, in code_case()).
        (r"(企业|公司|集团|平台|景区运营|文旅公司|开发公司).{0,8}(主导|运营|经营|建设|开发)", None),
        (r"成立.{0,4}(项目|开发|文旅).?公司", None),
    ],
    "elite_or_large_household_only": [
        (r"大户.{0,6}(经营|带动|主体)", None),
        (r"种植大户|养殖大户|经营大户|规模大户", None),
        (r"少数.{0,6}(精英|大户|投资人)", None),
        (r"龙头.{0,4}(企业|户).{0,15}(收益|分红).{0,8}(集中|主要)", None),
    ],
    "conservation_restriction_no_compensation": [
        (r"禁止.{0,4}(砍伐|放牧|捕捞|采伐|开发)", None),
        (r"限制.{0,4}(放牧|捕捞|采伐|开发|生产)", None),
        (r"禁渔|禁牧|禁伐", None),
        (r"封山育林", None),
        (r"退耕.{0,4}(还林|还草)", None),
    ],
}

POSITIVE_KEYS = list(POSITIVE_RULES.keys())
NEGATIVE_KEYS = list(NEGATIVE_RULES.keys())
ALL_KEYS = POSITIVE_KEYS + NEGATIVE_KEYS


def _split_sentences(text: str) -> list[str]:
    # naive Chinese-aware sentence splitter
    return [s.strip() for s in re.split(r"(?<=[。！？!?\n])", text) if s.strip()]


def _find_sentence(text: str, pat: str) -> str | None:
    for s in _split_sentences(text):
        if re.search(pat, s):
            return s[:300]
    # fall back: find window
    m = re.search(pat, text)
    if m:
        i = m.start()
        return text[max(0, i - 80): i + 120].strip()[:300]
    return None


def code_one(text: str) -> dict:
    """Return dict with indicators -> 0/1 and evidence sentences."""
    if not text or text in {"NA_NOT_REPORTED", "NA_NOT_APPLICABLE"}:
        return {k: 0 for k in ALL_KEYS} | {f"{k}_evidence": "" for k in ALL_KEYS} | {f"{k}_rule": "" for k in ALL_KEYS}
    res: dict = {}
    for ind, rules in POSITIVE_RULES.items():
        val = 0
        evid = ""
        rule_hit = ""
        for pat, neg in rules:
            sentence = _find_sentence(text, pat)
            if sentence is None:
                continue
            if neg and re.search(neg, sentence):
                continue
            val = 1
            evid = sentence
            rule_hit = pat
            break
        res[ind] = val
        res[f"{ind}_evidence"] = evid
        res[f"{ind}_rule"] = rule_hit

    # negative indicators: special handling — firm_dominated_no_distribution
    # requires firm-led operator AND NO positive sharing fired anywhere.
    fired_pos_count = sum(res[k] for k in POSITIVE_KEYS)

    for ind, rules in NEGATIVE_RULES.items():
        val = 0
        evid = ""
        rule_hit = ""
        for pat, neg in rules:
            sentence = _find_sentence(text, pat)
            if sentence is None:
                continue
            if neg and re.search(neg, sentence):
                continue
            val = 1
            evid = sentence
            rule_hit = pat
            break
        if ind == "firm_dominated_no_distribution" and val == 1:
            # only count it if positives are weak (< 2 fired)
            if fired_pos_count >= 2:
                val = 0
                evid = ""
                rule_hit = ""
        if ind == "conservation_restriction_no_compensation" and val == 1:
            # only count if eco_compensation and land_or_resource_rent and eco_job all 0
            if res["eco_compensation"] or res["land_or_resource_rent"] or res["eco_job"]:
                val = 0
                evid = ""
                rule_hit = ""
        res[ind] = val
        res[f"{ind}_evidence"] = evid
        res[f"{ind}_rule"] = rule_hit

    return res


def main() -> int:
    src = PROCESSED / "cases_dedup.csv"
    if not src.exists():
        print(f"missing {src}; run parse_html_pdf.py first")
        return 1
    out = PROCESSED / "cases_bsi_rules.csv"
    with src.open(encoding="utf-8") as f_in, out.open("w", encoding="utf-8", newline="") as f_out:
        reader = csv.DictReader(f_in)
        first = True
        writer = None
        for row in reader:
            text = row.get("raw_text", "")
            coded = code_one(text)
            bsi_raw = sum(coded[k] for k in POSITIVE_KEYS)
            cap = sum(coded[k] for k in NEGATIVE_KEYS)
            coded.update({
                "case_id": row["case_id"],
                "rule_bsi_raw": bsi_raw,
                "rule_capture_risk": cap,
                "rule_bsi_net": bsi_raw - cap,
            })
            if first:
                first = False
                fieldnames = ["case_id"] + ALL_KEYS + [f"{k}_evidence" for k in ALL_KEYS] + [f"{k}_rule" for k in ALL_KEYS] + ["rule_bsi_raw", "rule_capture_risk", "rule_bsi_net"]
                writer = csv.DictWriter(f_out, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
            writer.writerow(coded)
    print(f"code_bsi_rules: -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
