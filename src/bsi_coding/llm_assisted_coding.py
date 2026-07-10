"""Dual-pass model-assisted BSI coding.

Strategy:
1) Pass A — call the primary OpenAI-compatible model endpoint for all cases.
2) Pass B — optionally call a secondary compatible proxy with a model cascade.
3) Merge into cases_bsi_llm.jsonl + cases_bsi_llm.csv.

Both passes resume from existing jsonl, so this script can be re-run safely.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from openai import OpenAI

PROJECT_ROOT = Path("/home/user/projects/epvr-replication")
PROCESSED = PROJECT_ROOT / "data" / "processed"

PRIMARY_LLM_BASE_URL = os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
PRIMARY_LLM_MODEL = os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL")
SECONDARY_LLM_PROXY = os.environ.get("SECONDARY_LLM_PROXY_URL") or os.environ.get("ANTHROPIC_PROXY_URL", "")
SECONDARY_LLM_MODELS = [
    m.strip()
    for m in (
        os.environ.get("SECONDARY_LLM_MODELS")
        or os.environ.get("ANTHROPIC_MODEL_CASCADE")
        or ""
    ).split(",")
    if m.strip()
]


def _estimate_cost_usd(
    in_tok: int,
    out_tok: int,
    *,
    in_env: str = "LLM_INPUT_PRICE_PER_1K",
    out_env: str = "LLM_OUTPUT_PRICE_PER_1K",
) -> float:
    """Optional cost estimate; returns 0 when prices are not configured."""
    try:
        in_price = float(os.environ.get(in_env, "0"))
        out_price = float(os.environ.get(out_env, "0"))
    except ValueError:
        return 0.0
    return (in_tok / 1000) * in_price + (out_tok / 1000) * out_price


def _primary_api_key() -> str | None:
    return os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")

POSITIVE_KEYS = [
    "farmer_dividend", "collective_dividend", "cooperative_participation",
    "eco_job", "guaranteed_purchase", "land_or_resource_rent",
    "eco_compensation", "poverty_or_low_income_targeting",
    "green_credit_inclusion",
]
NEGATIVE_KEYS = [
    "firm_dominated_no_distribution", "elite_or_large_household_only",
    "conservation_restriction_no_compensation",
]
ALL_KEYS = POSITIVE_KEYS + NEGATIVE_KEYS

SYSTEM_PROMPT = """你是严谨的中国乡村经济政策编码员。我会给你一段关于生态产品价值实现 (EPVR) 的中文案例文本。请对 12 个 BSI 指标各输出 0 或 1。

【硬性规则】文本必须明确支持才打 1；模糊或仅政策口号一律打 0。仅根据给定文本判断，不要根据常识推测。

请只返回严格的 JSON 对象，结构：
{
  "farmer_dividend": 0或1,
  "collective_dividend": 0或1,
  "cooperative_participation": 0或1,
  "eco_job": 0或1,
  "guaranteed_purchase": 0或1,
  "land_or_resource_rent": 0或1,
  "eco_compensation": 0或1,
  "poverty_or_low_income_targeting": 0或1,
  "green_credit_inclusion": 0或1,
  "firm_dominated_no_distribution": 0或1,
  "elite_or_large_household_only": 0或1,
  "conservation_restriction_no_compensation": 0或1,
  "evidence": {12个指标各一行原文证据句，没证据就用空字符串""},
  "confidence": "high|medium|low",
  "case_type_guess": "1_green_agriculture_premium|2_ecological_tourism|3_forest_or_understory_economy|4_carbon_sink_or_ecological_rights|5_water_or_watershed_compensation|6_land_restoration_or_land_quota|7_green_finance|8_village_collective_ecological_asset_operation|9_mixed_model|unknown"
}

【指标定义】
1) farmer_dividend：普通农户获得分红/股份收益/利润分配。
2) collective_dividend：村集体获得项目收入并返还农户或用于公共品。
3) cooperative_participation：农民合作社为核心经营或分润主体。
4) eco_job：村民获得生态保护/巡护/修复/旅游/管护等岗位。
5) guaranteed_purchase：保底收购/优质优价/订单农业。
6) land_or_resource_rent：农户或集体获得土地/林地/水域/房屋租金或资源使用费。
7) eco_compensation：生态补偿直接支付给农户或村集体。
8) poverty_or_low_income_targeting：明确优先低收入户/脱贫户/残疾户/妇女/少数民族。
9) green_credit_inclusion：小农户/合作社/集体获绿色信贷/保险/金融服务。
10) firm_dominated_no_distribution：文本只描述企业/景区/平台运营，无任何分享机制。
11) elite_or_large_household_only：收益主要给大户/龙头/精英。
12) conservation_restriction_no_compensation：描述生产/捕捞/砍伐限制，但无补偿/岗位/租金。

不要 markdown，不要解释。
"""


def _empty(reason: str) -> dict:
    return {
        **{k: 0 for k in ALL_KEYS},
        "evidence": {k: "" for k in ALL_KEYS},
        "confidence": "low",
        "case_type_guess": "unknown",
        "error": reason,
    }


def _strip_codefence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s


def _parse_json(text: str) -> dict | None:
    text = _strip_codefence(text)
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            fixed = re.sub(r",(\s*[}\]])", r"\1", m.group(0))
            return json.loads(fixed)
        except Exception:
            return None


def _validate(rec: dict) -> dict:
    out = {k: 0 for k in ALL_KEYS}
    ev = {k: "" for k in ALL_KEYS}
    for k in ALL_KEYS:
        v = rec.get(k, 0)
        try:
            out[k] = int(bool(int(v)))
        except Exception:
            out[k] = 0
    rev = rec.get("evidence") or {}
    if isinstance(rev, dict):
        for k in ALL_KEYS:
            ev[k] = str(rev.get(k, ""))[:400]
    out["evidence"] = ev
    out["confidence"] = rec.get("confidence", "low") if rec.get("confidence") in {"high", "medium", "low"} else "low"
    out["case_type_guess"] = rec.get("case_type_guess", "unknown")
    return out


# ---------------------------------------------------------------------------
# Model callers.
# ---------------------------------------------------------------------------

def call_openai(client: OpenAI, text: str) -> tuple[dict, float, dict]:
    if not PRIMARY_LLM_MODEL:
        return _empty("primary_model_not_configured"), 0.0, {}
    try:
        r = client.chat.completions.create(
            model=PRIMARY_LLM_MODEL,
            max_completion_tokens=1800,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text[:6000]},
            ],
        )
    except Exception as e:
        return _empty(f"openai_error:{type(e).__name__}:{str(e)[:80]}"), 0.0, {}
    raw = (r.choices[0].message.content or "").strip()
    parsed = _parse_json(raw) or _empty("openai_unparseable")
    val = _validate(parsed) if "error" not in parsed else parsed
    in_tok = r.usage.prompt_tokens
    out_tok = r.usage.completion_tokens
    usd = _estimate_cost_usd(in_tok, out_tok)
    return val, usd, {"in": in_tok, "out": out_tok, "raw": raw[:500]}


def _anthropic_post(model: str, text: str, max_tokens: int = 1100) -> tuple[int, str, dict]:
    if not SECONDARY_LLM_PROXY:
        return 0, "SECONDARY_LLM_PROXY_URL not configured", {}
    body = {"model": model, "max_tokens": max_tokens, "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": text[:5000]}]}
    try:
        r = requests.post(
            SECONDARY_LLM_PROXY, json=body,
            headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01"},
            timeout=120,
        )
    except Exception as e:
        return 0, f"{type(e).__name__}:{str(e)[:80]}", {}
    try:
        data = r.json()
    except Exception:
        data = {}
    return r.status_code, r.text[:200], data


def call_anthropic(text: str) -> tuple[dict, float, dict]:
    if not SECONDARY_LLM_MODELS:
        return _empty("secondary_models_not_configured"), 0.0, {}
    # Adaptive cascade: try each configured model once, on 429 immediately
    # fall through to the next. Only retry within a single model on 5xx errors.
    last_status = 0
    last_body = ""
    data: dict = {}
    used_model = SECONDARY_LLM_MODELS[0]
    for model in SECONDARY_LLM_MODELS:
        used_model = model
        s, b, data = _anthropic_post(model, text)
        last_status, last_body = s, b
        if s == 200:
            break
        if s == 429:
            time.sleep(1.5)  # brief pause and try next model
            continue
        if 500 <= s < 600:
            time.sleep(5)
            s, b, data = _anthropic_post(model, text)
            last_status, last_body = s, b
            if s == 200:
                break
            continue
        break
    # If the whole cascade returns 429, wait and retry the last configured model once.
    if last_status == 429:
        time.sleep(30)
        used_model = SECONDARY_LLM_MODELS[-1]
        s, b, data = _anthropic_post(used_model, text)
        last_status, last_body = s, b
    if last_status != 200:
        return _empty(f"anthropic_giveup_{last_status}"), 0.0, {"raw": last_body, "model": used_model}
    content = data.get("content", [])
    text_out = "".join(c.get("text", "") for c in content if c.get("type") == "text")
    parsed = _parse_json(text_out) or _empty("anthropic_unparseable")
    val = _validate(parsed) if "error" not in parsed else parsed
    usage = data.get("usage", {})
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    usd = _estimate_cost_usd(
        in_tok,
        out_tok,
        in_env="SECONDARY_LLM_INPUT_PRICE_PER_1K",
        out_env="SECONDARY_LLM_OUTPUT_PRICE_PER_1K",
    )
    return val, usd, {"in": in_tok, "out": out_tok, "raw": text_out[:500], "model": used_model}


# ---------------------------------------------------------------------------
# IO helpers — resume-safe.
# ---------------------------------------------------------------------------

OAI_CACHE = PROCESSED / "_oai_cache.jsonl"
ANT_CACHE = PROCESSED / "_ant_cache.jsonl"


def _load_cache(p: Path) -> dict:
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            out[r["case_id"]] = r
        except Exception:
            pass
    return out


def _append_cache(p: Path, rec: dict) -> None:
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-usd", type=float, default=15.0)
    ap.add_argument("--soft-budget-usd", type=float, default=5.0)
    ap.add_argument("--limit", type=int, default=10000)
    ap.add_argument(
        "--phase",
        choices=["both", "primary", "secondary", "openai", "anthropic", "merge"],
        default="both",
    )
    args = ap.parse_args()
    phase = {"openai": "primary", "anthropic": "secondary"}.get(args.phase, args.phase)

    src = PROCESSED / "cases_dedup.csv"
    if not src.exists():
        print(f"missing {src}; run parse_html_pdf.py first"); return 1
    with src.open(encoding="utf-8") as f:
        cases = list(csv.DictReader(f))[: args.limit]
    print(f"llm_assisted_coding: {len(cases)} cases to code")

    oai_cache = _load_cache(OAI_CACHE)
    ant_cache = _load_cache(ANT_CACHE)
    print(f"  resume: oai_cached={len(oai_cache)} ant_cached={len(ant_cache)}")

    total_usd = 0.0
    if phase in ("both", "primary"):
        api_key = _primary_api_key()
        if not api_key:
            print("missing LLM_API_KEY"); return 1
        if not PRIMARY_LLM_MODEL:
            print("missing LLM_MODEL"); return 1
        client_kwargs = {"api_key": api_key}
        if PRIMARY_LLM_BASE_URL:
            client_kwargs["base_url"] = PRIMARY_LLM_BASE_URL
        client = OpenAI(**client_kwargs)
        for i, row in enumerate(cases):
            cid = row["case_id"]
            if cid in oai_cache:
                total_usd += oai_cache[cid].get("usd", 0)
                continue
            text = row.get("raw_text", "") or ""
            if not text or len(text) < 100:
                continue
            t0 = time.time()
            oai, oai_usd, oai_meta = call_openai(client, text)
            total_usd += oai_usd
            rec = {"case_id": cid, "openai": oai, "usd": oai_usd, "elapsed_s": round(time.time() - t0, 1)}
            _append_cache(OAI_CACHE, rec)
            oai_cache[cid] = rec
            if (i + 1) % 10 == 0:
                print(f"  [oai {i+1}/{len(cases)}] usd_total={total_usd:.3f}")
            if total_usd >= args.budget_usd:
                print("BUDGET HARD CAP HIT"); break
            time.sleep(0.2)
        print(f"  oai done; total usd ≈ {total_usd:.3f}")

    if phase in ("both", "secondary"):
        if not SECONDARY_LLM_PROXY:
            print("missing SECONDARY_LLM_PROXY_URL"); return 1
        if not SECONDARY_LLM_MODELS:
            print("missing SECONDARY_LLM_MODELS"); return 1
        for i, row in enumerate(cases):
            cid = row["case_id"]
            if cid in ant_cache:
                total_usd += ant_cache[cid].get("usd", 0)
                continue
            text = row.get("raw_text", "") or ""
            if not text or len(text) < 100:
                continue
            t0 = time.time()
            ant, ant_usd, ant_meta = call_anthropic(text)
            total_usd += ant_usd
            rec = {"case_id": cid, "anthropic": ant, "usd": ant_usd, "model": ant_meta.get("model", ""),
                   "elapsed_s": round(time.time() - t0, 1)}
            _append_cache(ANT_CACHE, rec)
            ant_cache[cid] = rec
            if (i + 1) % 5 == 0:
                print(f"  [ant {i+1}/{len(cases)}] usd_total={total_usd:.3f} last_model={ant_meta.get('model')}")
            if total_usd >= args.budget_usd:
                print("BUDGET HARD CAP HIT"); break
            time.sleep(0.5)
        print(f"  ant done; total usd ≈ {total_usd:.3f}")

    # Merge.
    out_jsonl = PROCESSED / "cases_bsi_llm.jsonl"
    out_csv = PROCESSED / "cases_bsi_llm.csv"
    rows_out = []
    with out_jsonl.open("w", encoding="utf-8") as f:
        for row in cases:
            cid = row["case_id"]
            o = oai_cache.get(cid, {})
            a = ant_cache.get(cid, {})
            if not o and not a:
                continue
            rec = {
                "case_id": cid,
                "case_type_rule": row.get("case_type", ""),
                "province": row.get("province", ""),
                "county": row.get("county", ""),
                "year": row.get("case_year", ""),
                "openai": o.get("openai", _empty("openai_missing")),
                "anthropic": a.get("anthropic", _empty("anthropic_missing")),
                "openai_usd": round(o.get("usd", 0), 5),
                "anthropic_usd": round(a.get("usd", 0), 5),
                "anthropic_model_used": a.get("model", ""),
                "elapsed_oai_s": o.get("elapsed_s", 0),
                "elapsed_ant_s": a.get("elapsed_s", 0),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            rows_out.append(rec)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["case_id"]
        for src_name in ("oai", "ant"):
            for k in ALL_KEYS:
                fieldnames.append(f"{src_name}_{k}")
            fieldnames.append(f"{src_name}_confidence")
            fieldnames.append(f"{src_name}_case_type")
        fieldnames += ["llm_agreement_flag", "llm_disagree_indicators", "anthropic_model_used"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for rec in rows_out:
            row = {"case_id": rec["case_id"]}
            for k in ALL_KEYS:
                row[f"oai_{k}"] = rec["openai"].get(k, 0)
                row[f"ant_{k}"] = rec["anthropic"].get(k, 0)
            row["oai_confidence"] = rec["openai"].get("confidence", "low")
            row["oai_case_type"] = rec["openai"].get("case_type_guess", "unknown")
            row["ant_confidence"] = rec["anthropic"].get("confidence", "low")
            row["ant_case_type"] = rec["anthropic"].get("case_type_guess", "unknown")
            disagree = [k for k in ALL_KEYS if rec["openai"].get(k, 0) != rec["anthropic"].get(k, 0)]
            row["llm_agreement_flag"] = int(not disagree)
            row["llm_disagree_indicators"] = ",".join(disagree)
            row["anthropic_model_used"] = rec.get("anthropic_model_used", "")
            w.writerow(row)
    print(f"merge: wrote {out_jsonl} ({len(rows_out)} rows)")
    print(f"merge: wrote {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
