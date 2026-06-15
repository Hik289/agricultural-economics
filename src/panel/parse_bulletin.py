"""Extract socioeconomic variables from a 国民经济和社会发展统计公报 HTML text.

The provincial bulletins follow a very consistent wording.  We extract:

| variable                              | unit returned        |
|---|---|
| rural_disposable_income (per capita)  | yuan                 |
| urban_disposable_income (per capita)  | yuan                 |
| gdp                                   | 亿元 (100 M CNY)     |
| primary_industry_value_added          | 亿元                 |
| population (year-end total)           | 万人 (10 000 people) |
| rural_population (year-end)           | 万人                 |
| fiscal_revenue (general public budget)| 亿元                 |
| fiscal_expenditure (general public)   | 亿元                 |
| agri_forestry_animal_fishery_output   | 亿元                 |
| tourism_revenue                       | 亿元                 |
| grain_output                          | 万吨 (10 000 tons)   |
| forest_coverage                       | %                    |

Each extracted value carries its evidence sentence so the value is auditable.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# Number-with-unit patterns.  Chinese bulletins write numbers in three styles:
#   "12345.6 亿元"          (plain)
#   "1,260,582 亿元"        (comma-grouped)
#   "1260582 亿元"          (no grouping)
# Order alternatives "comma-form first" so the comma-form is preferred when
# both could match.
NUM = r"((?:[0-9]{1,3}(?:[,，][0-9]{3})+)(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
# Currency / count units we may see — we normalize at extraction time.

# --- canonical evidence patterns -------------------------------------------
# Each rule is (var, [(pattern, scale_to_canonical_unit, kind)]).

# For income (per capita): canonical unit = yuan.
# Source phrases:
#   农村居民人均可支配收入 21691 元
#   农村常住居民人均可支配收入 21691.0元
#   农村人均可支配收入 21691元
RURAL_INCOME = [
    rf"(?:农村|农村常住|乡村)居民人均可支配收入(?:为|达|达到|约)?[^0-9]{{0,12}}{NUM}\s*元",
    rf"农村人均可支配收入(?:为|达|达到|约)?[^0-9]{{0,12}}{NUM}\s*元",
    rf"农村居民可支配收入(?:[^0-9]{{0,8}}人均){{0,1}}(?:为|达|达到|约)?[^0-9]{{0,12}}{NUM}\s*元",
]
URBAN_INCOME = [
    rf"(?:城镇|城镇常住)居民人均可支配收入(?:为|达|达到|约)?[^0-9]{{0,12}}{NUM}\s*元",
    rf"城镇人均可支配收入(?:为|达|达到|约)?[^0-9]{{0,12}}{NUM}\s*元",
]

# Joint "三分别" form (Zhejiang 2023 style):
#   "全体及城乡居民人均可支配收入分别为 63830、74997 和 40311 元"
# Order: total, urban, rural.
JOINT_INCOMES = [
    rf"全体及城乡居民人均可支配收入分别为\s*{NUM}[、，,]\s*{NUM}\s*和\s*{NUM}\s*元",
    rf"全体居民和城乡居民人均可支配收入分别为\s*{NUM}[、，,]\s*{NUM}\s*和\s*{NUM}\s*元",
    rf"全体居民、城镇居民和农村居民人均可支配收入(?:分别)?为?\s*{NUM}[、，,]\s*{NUM}\s*和\s*{NUM}\s*元",
]
ALL_INCOME = [
    rf"(?:全国|全省|全市|全县)?居民人均可支配收入[^0-9]{{0,12}}{NUM}\s*元",
]

# GDP -- canonical unit = 亿元.  Bulletins sometimes inject footnote refs
# like "国内生产总值 [2][3] 1260582 亿元".  Allow ≥1 footnote brackets.
_FOOTS = r"(?:\s*\[\s*\d+\s*\])*"
GDP = [
    rf"(?:地区生产总值|国内生产总值){_FOOTS}\s*(?:\([^()]{{1,12}}\)|（[^（）]{{1,12}}）)?\s*(?:为|达|达到|约)?\s*{NUM}\s*亿元",
    rf"GDP[^0-9]{{0,10}}{NUM}\s*亿元",
    rf"实现地区生产总值{_FOOTS}\s*(?:\([^()]{{1,12}}\)|（[^（）]{{1,12}}）)?\s*(?:为|达|达到|约)?\s*{NUM}\s*亿元",
    rf"(?:全省|全市|全县|全国)\s*完成生产总值{_FOOTS}\s*(?:为|达|达到|约)?\s*{NUM}\s*亿元",
    rf"完成生产总值{_FOOTS}\s*(?:为|达|达到|约)?\s*{NUM}\s*亿元",
    rf"(?:全省|全市|全县|全国)\s*生产总值{_FOOTS}\s*(?:为|达|达到|约)?\s*{NUM}\s*亿元",
]

# Primary industry value added -- 亿元
PRIMARY = [
    rf"第一产业(?:增加值|完成增加值)[^0-9]{{0,15}}{NUM}\s*亿元",
    rf"农林牧渔业增加值[^0-9]{{0,15}}{NUM}\s*亿元",
    rf"第一产业[^0-9]{{0,15}}{NUM}\s*亿元",
]

# Agri-forestry-animal-fishery total output value -- 亿元
AGRI_OUTPUT = [
    rf"农林牧渔业(?:总产值|总产值达)[^0-9]{{0,15}}{NUM}\s*亿元",
    rf"农林牧渔业总产值[^0-9]{{0,15}}{NUM}\s*亿元",
]

# Population -- 万人 canonical.  Be careful: bulletins also mention
# "城镇常住人口", "乡村人口", "出生人口", "死亡人口", "净增人口" — none of
# those is the total.  We anchor on the strict total-population phrasings.
# Allow optional footnote ref like [1].
_FOOT = r"(?:\s*\[\s*\d+\s*\])*"
POP_TOTAL = [
    rf"年末(?:全省|全市|全县|全国)?(?:常住|户籍)?总人口{_FOOT}\s*{NUM}\s*万人",
    rf"年末(?:全省|全市|全县|全国)?常住人口{_FOOT}\s*(?:为|达到|约|是)?\s*{NUM}\s*万人",
    rf"年末(?:全省|全市|全县|全国)人口{_FOOT}\s*{NUM}\s*万人",
    rf"年末户籍人口{_FOOT}\s*{NUM}\s*万人",
    rf"(?:全省|全市|全县|全国)常住人口{_FOOT}\s*(?:为|达到|约|是)?\s*{NUM}\s*万人",
    rf"至年末\s*[，,]?(?:全省|全市|全县|全国)?常住人口(?:为|达|是)?\s*{NUM}\s*万人",
    rf"年末[^0-9。]{{0,15}}常住人口(?:为|达|是)?\s*{NUM}\s*万人",
    rf"年末[^0-9。]{{0,15}}总人口(?:为|达|是)?\s*{NUM}\s*万人",
]
POP_RURAL = [
    rf"(?:乡村|农村)常住人口{_FOOT}\s*{NUM}\s*万人",
    rf"乡村人口{_FOOT}\s*(?:为|约|达到|总数)?\s*{NUM}\s*万人",
    rf"农村人口{_FOOT}\s*(?:为|约|达到|总数)?\s*{NUM}\s*万人",
]

# Fiscal revenue / expenditure -- 亿元.  Province bulletins use "一般公共预算收入".
FISCAL_REV = [
    rf"一般公共预算收入[^0-9]{{0,15}}{NUM}\s*亿元",
    rf"地方一般公共预算收入[^0-9]{{0,15}}{NUM}\s*亿元",
    rf"财政总收入[^0-9]{{0,15}}{NUM}\s*亿元",
]
FISCAL_EXP = [
    rf"一般公共预算支出[^0-9]{{0,15}}{NUM}\s*亿元",
    rf"地方一般公共预算支出[^0-9]{{0,15}}{NUM}\s*亿元",
    rf"财政总支出[^0-9]{{0,15}}{NUM}\s*亿元",
]

TOURISM_REV = [
    rf"旅游(?:总)?(?:收入|总收入|综合收入)[^0-9]{{0,15}}{NUM}\s*亿元",
]

GRAIN = [
    rf"粮食(?:总)?产量[^0-9]{{0,15}}{NUM}\s*万吨",
    rf"粮食产量(?:为|达到|约)?[^0-9]{{0,10}}{NUM}\s*万吨",
]

FOREST_COVERAGE = [
    rf"森林覆盖率[^0-9]{{0,12}}{NUM}\s*%",
    rf"森林覆盖率[^0-9]{{0,12}}{NUM}\s*％",
]


# Optional alternative units (we down-convert to canonical):
GDP_TRILLION = [rf"(?:地区生产总值|国内生产总值)[^0-9]{{0,30}}{NUM}\s*万亿元"]
POP_PEOPLE = [rf"年末常住人口[^0-9]{{0,12}}{NUM}\s*人(?:\b|[^口万])"]


VARIABLE_RULES: dict[str, list[str]] = {
    "rural_disposable_income": RURAL_INCOME,
    "urban_disposable_income": URBAN_INCOME,
    "gdp": GDP,
    "primary_industry_value_added": PRIMARY,
    "agri_forestry_animal_fishery_output": AGRI_OUTPUT,
    "population": POP_TOTAL,
    "rural_population": POP_RURAL,
    "fiscal_revenue": FISCAL_REV,
    "fiscal_expenditure": FISCAL_EXP,
    "tourism_revenue": TOURISM_REV,
    "grain_output": GRAIN,
    "forest_coverage": FOREST_COVERAGE,
}

ALT_RULES_TRILLION: dict[str, list[str]] = {
    "gdp": GDP_TRILLION,
}


def _normalize_num(s: str) -> Optional[float]:
    s = s.replace(",", "").replace("，", "").strip()
    try:
        return float(s)
    except Exception:
        return None


def _text_window(text: str, m: re.Match) -> str:
    i = m.start(); j = m.end()
    snippet = text[max(0, i - 30): min(len(text), j + 50)]
    return re.sub(r"\s+", " ", snippet).strip()[:300]


# Pre-disqualifying-context terms for GDP / population (a match starting after
# one of these terms is rejected because it refers to a sub-region rather than
# the whole administrative unit).
_GDP_REJECT_LEFT = re.compile(
    r"([^。，,；；\s]{1,6}地区"            # *地区 — sub-region (湘南地区, 洞庭湖地区, …)
    r"|分区域|分地区|分市|地级市|分县市"
    r"|开发区|新区|经开区|主城|郊区|城区"
    r"|二级区|二级市|管委会|功能区"
    r"|大湘西|湘南|湘西|洞庭湖|川西|川东"
    r"|滇西|滇东|藏东|藏西|青南|青北|新东|新西"
    r"|皖北|皖南|苏北|苏南|鄂西|鄂东|赣南|赣北|粤东|粤西|粤北"
    # Sichuan economic-zone sub-totals (川):
    r"|环成都经济圈|成都平原经济区|川南经济区|川东北经济区|攀西经济区|川西北生态区"
    # minority autonomous prefectures / counties (Sichuan):
    r"|自治州和|自治州、|自治县和|自治县、)"
)


def extract(text: str) -> dict[str, dict]:
    """Return {var: {"value": float, "evidence": str, "pattern": str}}."""
    out: dict[str, dict] = {}
    text = re.sub(r"\s+", " ", text)

    SUBREGION_REJECT_VARS = {
        "gdp", "primary_industry_value_added", "fiscal_revenue", "fiscal_expenditure",
        "agri_forestry_animal_fishery_output", "tourism_revenue", "grain_output",
        "population", "rural_population",
    }

    def _find_first_clean(var_: str, pattern: str):
        """Return first match whose pre-context isn't a sub-region label."""
        for mm in re.finditer(pattern, text):
            pre = text[max(0, mm.start() - 25): mm.start()]
            if var_ in SUBREGION_REJECT_VARS and _GDP_REJECT_LEFT.search(pre):
                continue
            return mm
        return None

    for var, patterns in VARIABLE_RULES.items():
        for p in patterns:
            m = _find_first_clean(var, p)
            if m is None:
                continue
            val = _normalize_num(m.group(1))
            if val is None:
                continue
            # sanity: reject zero or implausibly huge values
            if var in ("rural_disposable_income", "urban_disposable_income"):
                if not (1000 <= val <= 200_000):
                    continue
            elif var == "gdp":
                if not (1 <= val <= 200_000):  # 亿元
                    continue
            elif var in ("population", "rural_population"):
                if not (1 <= val <= 200_000):  # 万人
                    continue
            elif var == "forest_coverage":
                if not (1 <= val <= 100):
                    continue
            out[var] = {
                "value": val,
                "evidence": _text_window(text, m),
                "pattern": p[:80],
            }
            break

    # alt-unit handling for GDP if matched in 万亿元 (rare, top-tier provinces only)
    if "gdp" not in out:
        for p in ALT_RULES_TRILLION["gdp"]:
            m = re.search(p, text)
            if m:
                val = _normalize_num(m.group(1))
                if val and 0.1 < val < 30:
                    out["gdp"] = {"value": val * 10000, "evidence": _text_window(text, m), "pattern": p[:80] + " [×10000]"}
                    break

    # Joint "三分别" form for incomes (Zhejiang-style).
    if "urban_disposable_income" not in out or "rural_disposable_income" not in out:
        for p in JOINT_INCOMES:
            m = re.search(p, text)
            if not m:
                continue
            try:
                _all = _normalize_num(m.group(1))
                _urb = _normalize_num(m.group(2))
                _rur = _normalize_num(m.group(3))
            except Exception:
                continue
            ev = _text_window(text, m)
            if _urb and 1000 <= _urb <= 200_000 and "urban_disposable_income" not in out:
                out["urban_disposable_income"] = {"value": _urb, "evidence": ev, "pattern": p[:80] + " [joint]"}
            if _rur and 1000 <= _rur <= 200_000 and "rural_disposable_income" not in out:
                out["rural_disposable_income"] = {"value": _rur, "evidence": ev, "pattern": p[:80] + " [joint]"}
            break

    return out


def main() -> int:
    import argparse, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    args = ap.parse_args()
    text = Path(args.path).read_text(encoding="utf-8", errors="replace")
    # strip tags if HTML
    if "<" in text and ">" in text:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    res = extract(text)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
