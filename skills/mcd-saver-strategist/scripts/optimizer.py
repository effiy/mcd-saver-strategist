#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门省钱精算师 · 确定性优惠组合优化器
==========================================

一个大模型不擅长、但代码很擅长的事情: 在「菜单 x 优惠券」的组合空间里,
穷举出**总价最低**的合规点餐方案。

设计原则
--------
1. 纯标准库, 零第三方依赖, 可直接在 WorkBuddy 沙箱里跑。
2. 确定性: 相同输入永远得到相同输出, 便于复核与写测试。
3. 数据与逻辑分离: 输入是 MCP 返回结果经归一化后的 JSON, 输出是结构化方案,
   负责「算」, 不负责「说」。文案由 Agent 依据本结果生成。

输入 JSON 契约
--------------
menu.json
    {
      "store_code": "SZ0001",
      "items": [
        {"code": "BIGMAC", "name": "巨无霸", "category": "burger",
         "price": 25.0, "calories": 550, "tags": ["beef", "classic"]}
      ]
    }

coupons.json  (所有券统一放在 coupons 数组里, 用 type 区分)
    {
      "coupons": [
        # 1) 单品改价券: 把某商品价格改成 override_price
        {"id": "C1", "type": "item_price", "title": "巨无霸立减",
         "item_codes": ["BIGMAC"], "override_price": 18.0, "stackable": false},
        # 2) 单品折扣券: 对匹配商品打 discount_pct 折 (0.8 = 8折)
        {"id": "C2", "type": "percent", "title": "小食 8 折",
         "item_codes": ["FRIES_M", "NUGGETS_5"], "discount_pct": 0.8, "stackable": false},
        # 3) 满减券: 小计 >= min_spend 时减 discount
        {"id": "C3", "type": "threshold", "title": "满 30 减 5",
         "min_spend": 30.0, "discount": 5.0, "stackable": true},
        # 4) 组合价券: 每组各挑 1 个, 打包价 price (如 1+1随心配)
        {"id": "C4", "type": "bundle_price", "title": "1+1 随心配",
         "groups": [["BIGMAC", "MCFLOWER"], ["FRIES_M", "COKE_M"]],
         "price": 12.9, "stackable": false},
        # 5) 赠品券: 满足 min_spend 后送 gift_codes
        {"id": "C5", "type": "free_gift", "title": "满 20 送派",
         "min_spend": 20.0, "gift_codes": ["PIE"], "stackable": true}
      ]
    }

  可选字段 channel 控制券的适用场景, 取值 "any"(默认) / "pickup" / "delivery"。
  例: 门店券通常仅到店可用 {"id": "S1", ..., "channel": "pickup"};
      外送券 {"id": "D1", ..., "channel": "delivery"}。

request.json
    {
      "wants": ["巨无霸", "薯条", "可乐"],   # 用户想吃的东西 (按名称模糊匹配)
      "budget": 45.0,                       # 可选, 总价上限 (含外送费)
      "max_calories": 1000,                 # 可选, 热量上限
      "max_items": 5,                       # 可选, 最多几件
      "allow_extras": true,                 # 是否允许为了用券而加购
      "dining_mode": "pickup",              # 可选, "pickup"(默认) / "delivery"
      "delivery_fee": 9.0                   # 可选, dining_mode=delivery 时计入总价
    }

输出
----
{"plans": [...], "baseline": {...}, "best": {...}}
每个 plan:
    {"items": [...], "lines": [...], "subtotal": 42.0, "coupon_saving": 12.6,
     "total": 29.4, "calories": 980, "coupons": [...], "gifts": [...],
     "saving_pct": 0.30, "notes": [...]}
"""

from __future__ import annotations

import json
import os
import sys
from itertools import combinations, product
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MAX_COMBO_COUPONS = 3          # 单方案最多叠加几张券, 控制搜索规模
MAX_CANDIDATES_PER_WANT = 4    # 每个"想要的"最多保留几个候选商品
TOP_N_PLANS = 5


# --------------------------------------------------------------------------- #
# 载入与工具函数
# --------------------------------------------------------------------------- #
def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def item_index(items: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {it["code"]: it for it in items}


def normalize_name(text: str) -> str:
    return (text or "").strip().lower().replace(" ", "")


def match_want(want: str, items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按名称/标签模糊匹配用户想要的东西, 返回候选商品列表。"""
    key = normalize_name(want)
    hits: List[Tuple[int, Dict[str, Any]]] = []
    for it in items:
        name = normalize_name(it.get("name", ""))
        tags = [normalize_name(t) for t in it.get("tags", [])]
        code = normalize_name(it.get("code", ""))
        score = -1
        if key == name or key == code:
            score = 100
        elif key and (key in name or name in key):
            score = 80
        elif any(key in t or t in key for t in tags):
            score = 60
        if score >= 0:
            hits.append((score, it))
    hits.sort(key=lambda x: (-x[0], x[1]["price"]))
    return [it for _, it in hits]


def filter_coupons_for_mode(
    coupons: Sequence[Dict[str, Any]], dining_mode: str
) -> List[Dict[str, Any]]:
    """按用餐场景过滤券: channel 为 any 或与当前场景一致者可用。

    该字段是可选扩展; 未标 channel 的券视为 any, 保持向后兼容。
    """
    mode = (dining_mode or "pickup").strip().lower()
    out: List[Dict[str, Any]] = []
    for c in coupons:
        ch = str(c.get("channel", "any")).strip().lower() or "any"
        if ch in ("any", mode):
            out.append(c)
    return out


# --------------------------------------------------------------------------- #
# 券的可适用性 & 计价
# --------------------------------------------------------------------------- #
def _bucket_codes(items: Sequence[Dict[str, Any]]) -> List[str]:
    return [it["code"] for it in items]


def coupon_conflict(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """判断两张券是否互斥 (不可同时使用)。"""
    if not a.get("stackable", False) or not b.get("stackable", False):
        return True
    # 两张满减/赠品类券可以叠加(一般不同门槛), 但针对同一商品的券互斥
    ta, tb = a["type"], b["type"]
    if ta in ("threshold", "free_gift") and tb in ("threshold", "free_gift"):
        return False
    ca = set(a.get("item_codes", [])) | {c for g in a.get("groups", []) for c in g}
    cb = set(b.get("item_codes", [])) | {c for g in b.get("groups", []) for c in g}
    return bool(ca & cb)


def price_with_basket(
    basket: Sequence[Dict[str, Any]],
    coupon_ids: Sequence[str],
    coupons_by_id: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """给定菜篮 + 一组券, 计算合法则返回明细, 非法返回 None。"""
    basket_codes = _bucket_codes(basket)
    code2item = {it["code"]: it for it in basket}

    price_overrides: Dict[str, float] = {}
    percent_overrides: Dict[str, float] = {}
    bundle_lines: List[Dict[str, Any]] = []
    consumed: set = set()

    for cid in coupon_ids:
        cp = coupons_by_id[cid]
        ct = cp["type"]

        if ct == "item_price":
            usable = [c for c in cp["item_codes"] if c in code2item]
            if not usable:
                return None
            for c in usable:
                price_overrides[c] = min(
                    price_overrides.get(c, float("inf")), float(cp["override_price"])
                )

        elif ct == "percent":
            usable = [c for c in cp["item_codes"] if c in code2item]
            if not usable:
                return None
            for c in usable:
                percent_overrides[c] = min(
                    percent_overrides.get(c, 1.0), float(cp["discount_pct"])
                )

        elif ct == "bundle_price":
            picked: List[str] = []
            for group in cp["groups"]:
                cand = [c for c in group if c in code2item and c not in consumed]
                if not cand:
                    return None
                cand.sort(key=lambda c: code2item[c]["price"], reverse=True)
                picked.append(cand[0])
                consumed.add(cand[0])
            bundle_lines.append({"coupon": cid, "title": cp.get("title", cid),
                                 "codes": picked, "price": float(cp["price"])})

        elif ct == "threshold":
            pass  # 满减在商品小计算完后统一处理

        elif ct == "free_gift":
            pass  # 赠品在门槛校验后统一处理

    # 先算商品小计
    lines: List[Dict[str, Any]] = []
    subtotal = 0.0
    for it in basket:
        code = it["code"]
        if code in consumed:
            continue  # 已被组合价券打包
        base = float(it["price"])
        eff = base
        tag = ""
        if code in price_overrides:
            eff = min(eff, price_overrides[code]); tag = "单品券价"
        if code in percent_overrides:
            eff = min(eff, round(base * percent_overrides[code], 2)); tag = "折扣"
        subtotal += eff
        lines.append({"code": code, "name": it["name"], "price": eff, "tag": tag})

    for bl in bundle_lines:
        subtotal += bl["price"]
        lines.append({"code": "+".join(bl["codes"]), "name": bl["title"],
                      "price": bl["price"], "tag": "组合价"})

    # 满减: 基于当前小计, 取满足门槛的最大抵扣
    applied_threshold = None
    best_discount = 0.0
    for cid in coupon_ids:
        cp = coupons_by_id[cid]
        if cp["type"] == "threshold" and subtotal >= float(cp["min_spend"]):
            if float(cp["discount"]) > best_discount:
                best_discount = float(cp["discount"])
                applied_threshold = cid
    threshold_discount = best_discount

    # 赠品: 门槛校验
    valid_gifts: List[str] = []
    for cid in coupon_ids:
        cp = coupons_by_id[cid]
        if cp["type"] == "free_gift" and subtotal >= float(cp.get("min_spend", 0)):
            valid_gifts.extend(cp.get("gift_codes", []))

    total = round(max(subtotal - threshold_discount, 0.0), 2)
    return {
        "lines": lines,
        "subtotal": round(subtotal, 2),
        "threshold_coupon": applied_threshold,
        "threshold_discount": round(threshold_discount, 2),
        "total": total,
        "gifts": sorted(set(valid_gifts)),
    }


def best_coupon_plan(
    basket: Sequence[Dict[str, Any]],
    coupons: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """在菜篮上搜索最优用券组合。"""
    coupons_by_id = {c["id"]: c for c in coupons}
    ids = list(coupons_by_id.keys())

    # 先筛出至少可能适用的券, 减少组合规模
    basket_codes = set(_bucket_codes(basket))
    pool: List[str] = []
    for cid in ids:
        cp = coupons_by_id[cid]
        if cp["type"] == "threshold":
            pool.append(cid)
        elif cp["type"] == "free_gift":
            pool.append(cid)
        elif set(cp.get("item_codes", [])) & basket_codes:
            pool.append(cid)
        elif cp["type"] == "bundle_price":
            if all(set(g) & basket_codes for g in cp.get("groups", [])):
                pool.append(cid)

    best: Optional[Dict[str, Any]] = None
    best_total = float("inf")

    for r in range(0, min(MAX_COMBO_COUPONS, len(pool)) + 1):
        for combo in combinations(pool, r):
            # 互斥检查
            ok = True
            for a, b in combinations(combo, 2):
                if coupon_conflict(coupons_by_id[a], coupons_by_id[b]):
                    ok = False
                    break
            if not ok:
                continue
            res = price_with_basket(basket, combo, coupons_by_id)
            if res is None:
                continue
            if res["total"] < best_total:
                best_total = res["total"]
                best = res
                best["coupon_ids"] = list(combo)

    if best is None:
        best = price_with_basket(basket, [], coupons_by_id)
        best["coupon_ids"] = []
    return best


# --------------------------------------------------------------------------- #
# 菜篮生成
# --------------------------------------------------------------------------- #
def build_baskets(
    request: Dict[str, Any],
    items: Sequence[Dict[str, Any]],
) -> Iterable[List[Dict[str, Any]]]:
    """根据用户"想要的"生成候选菜篮。"""
    wants: List[str] = request.get("wants", []) or []
    max_items = int(request.get("max_items", 5))
    allow_extras = bool(request.get("allow_extras", True))

    want_candidates: List[List[Dict[str, Any]]] = []
    locked_codes: set = set()
    for w in wants:
        cands = match_want(w, items)[:MAX_CANDIDATES_PER_WANT]
        if not cands:
            continue
        want_candidates.append(cands)
        locked_codes.update(it["code"] for it in cands)

    if not want_candidates:
        # 没给明确想吃的, 就用最便宜的几件兜底
        cheapest = sorted(items, key=lambda x: x["price"])[:MAX_CANDIDATES_PER_WANT]
        yield from ([it] for it in cheapest)
        return

    extras_pool = [it for it in sorted(items, key=lambda x: x["price"])
                   if it["code"] not in locked_codes][:6] if allow_extras else []

    for combo in product(*want_candidates):
        codes = [it["code"] for it in combo]
        if len(set(codes)) != len(codes):
            continue
        if len(combo) > max_items:
            continue
        # 基础菜篮
        yield list(combo)
        # 加购 1 件: 往往是为了凑满减门槛
        if allow_extras and len(combo) < max_items:
            for extra in extras_pool:
                yield list(combo) + [extra]
        # 加购 2 件
        if allow_extras and len(combo) + 1 < max_items:
            for e1, e2 in combinations(extras_pool, 2):
                if {e1["code"], e2["code"]} & set(codes):
                    continue
                yield list(combo) + [e1, e2]


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def optimize(
    menu: Dict[str, Any],
    coupons_payload: Dict[str, Any],
    request: Dict[str, Any],
) -> Dict[str, Any]:
    items = menu["items"]
    all_coupons = coupons_payload.get("coupons", [])
    mode = (request.get("dining_mode") or "pickup").strip().lower()
    coupons = filter_coupons_for_mode(all_coupons, mode)
    delivery_fee = float(request.get("delivery_fee", 0) or 0) if mode == "delivery" else 0.0
    idx = item_index(items)

    # 无券基线: 用户想要的最便宜直选
    baseline_basket: List[Dict[str, Any]] = []
    for w in request.get("wants", []) or []:
        cands = match_want(w, items)
        if cands:
            baseline_basket.append(cands[0])
    baseline_total = round(sum(it["price"] for it in baseline_basket), 2)

    plans: List[Dict[str, Any]] = []
    seen: set = set()

    for basket in build_baskets(request, items):
        codes = tuple(sorted(it["code"] for it in basket))
        res = best_coupon_plan(basket, coupons)

        cal = sum(int(it.get("calories", 0)) for it in basket)
        for gift_code in res.get("gifts", []):
            if gift_code in idx:
                cal += int(idx[gift_code].get("calories", 0))

        total = round(res["total"] + delivery_fee, 2)
        if request.get("budget") is not None and total > float(request["budget"]):
            continue
        if request.get("max_calories") is not None and cal > int(request["max_calories"]):
            continue

        key = (codes, total)
        if key in seen:
            continue
        seen.add(key)

        raw = sum(it["price"] for it in basket)
        saving = round(raw - res["total"], 2)
        plans.append({
            "items": [{"code": it["code"], "name": it["name"], "category": it.get("category", "")}
                      for it in basket],
            "lines": res["lines"],
            "gifts": [{"code": g, "name": idx[g]["name"]} for g in res.get("gifts", []) if g in idx],
            "coupons": [{"id": cid, "title": next((c["title"] for c in coupons if c["id"] == cid), cid)}
                        for cid in res.get("coupon_ids", [])],
            "subtotal": res["subtotal"],
            "threshold_discount": res.get("threshold_discount", 0.0),
            "delivery_fee": round(delivery_fee, 2),
            "total": total,
            "raw_total": round(raw, 2),
            "coupon_saving": saving,
            "saving_pct": round(saving / raw, 4) if raw else 0.0,
            "calories": cal,
            "item_count": len(basket),
        })

    plans.sort(key=lambda p: (p["total"], p["calories"]))
    for p in plans:
        p["notes"] = _make_notes(p, baseline_total, request)

    return {
        "store_code": menu.get("store_code", ""),
        "currency": menu.get("currency", "CNY"),
        "dining_mode": mode,
        "delivery_fee": round(delivery_fee, 2),
        "baseline": {"items": [it["name"] for it in baseline_basket], "total": baseline_total},
        "plans": plans[:TOP_N_PLANS],
        "plan_pool_size": len(plans),
    }


def _make_notes(plan: Dict[str, Any], baseline_total: float, request: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    vs_base = round(baseline_total - plan["total"], 2)
    if vs_base > 0:
        notes.append(f"比「直接按想吃的点」省 {vs_base:.2f} 元")
    elif vs_base < 0:
        notes.append(f"比原意向贵 {abs(vs_base):.2f} 元 (为使用优惠券加购)")
    if plan["saving_pct"] >= 0.25:
        notes.append(f"折扣力度 {plan['saving_pct']*100:.0f}%, 属于强力优惠组合")
    if plan["threshold_discount"] > 0:
        notes.append(f"触发满减, 立减 {plan['threshold_discount']:.2f} 元")
    if plan["gifts"]:
        notes.append("达成赠品条件: " + "、".join(g["name"] for g in plan["gifts"]))
    if plan.get("delivery_fee", 0) > 0:
        notes.append(f"已含外送费 {plan['delivery_fee']:.2f} 元")
    if request.get("budget") is not None:
        notes.append(f"预算 {request['budget']} 元内 ✓")
    return notes


# --------------------------------------------------------------------------- #
# 命令行入口
# --------------------------------------------------------------------------- #
def format_report(result: Dict[str, Any], request: Dict[str, Any]) -> str:
    cur = result.get("currency", "CNY")
    sym = "¥" if cur == "CNY" else cur + " "
    out: List[str] = []
    out.append("=" * 60)
    out.append("  麦门省钱精算师 · 优化结果")
    out.append("=" * 60)
    base = result["baseline"]
    mode = result.get("dining_mode", "pickup")
    mode_cn = {"pickup": "到店自取", "delivery": "外送"}.get(mode, mode)
    out.append(f"门店: {result.get('store_code','')}   场景: {mode_cn}   想吃的: {'、'.join(base['items']) or '(未指定)'}")
    out.append(f"不使用优惠券的话, 直选约 {sym}{base['total']:.2f}")
    out.append("-" * 60)
    if not result["plans"]:
        out.append("在给定预算/热量约束下没有可行方案, 建议放宽条件。")
        return "\n".join(out)
    for i, p in enumerate(result["plans"], 1):
        medal = ["🥇", "🥈", "🥉", "④", "⑤"][i - 1] if i <= 5 else str(i)
        out.append(f"{medal} 方案 {i}   到手价 {sym}{p['total']:.2f}   "
                   f"(原价 {sym}{p['raw_total']:.2f}, 省 {sym}{p['coupon_saving']:.2f} / "
                   f"{p['saving_pct']*100:.0f}%)   约 {p['calories']} kcal")
        for ln in p["lines"]:
            tag = f"  [{ln['tag']}]" if ln.get("tag") else ""
            out.append(f"      · {ln['name']}  {sym}{ln['price']:.2f}{tag}")
        if p["threshold_discount"] > 0:
            out.append(f"      · 满减抵扣  -{sym}{p['threshold_discount']:.2f}")
        if p.get("delivery_fee", 0) > 0:
            out.append(f"      · 外送费    +{sym}{p['delivery_fee']:.2f}")
        if p["gifts"]:
            out.append("      🎁 赠品: " + "、".join(g["name"] for g in p["gifts"]))
        if p["coupons"]:
            out.append("      🎟️  用券: " + "、".join(c["title"] for c in p["coupons"]))
        for n in p["notes"]:
            out.append(f"      ℹ️  {n}")
        out.append("")
    out.append("-" * 60)
    out.append(f"共评估 {result['plan_pool_size']} 个可行方案, 展示前 {len(result['plans'])} 名。")
    return "\n".join(out)


def main(argv: List[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    args = argv[1:]

    base: Optional[str] = None
    flags: Dict[str, Any] = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                flags[k] = v
                i += 1
            elif i + 1 < len(args) and not args[i + 1].startswith("--"):
                flags[key] = args[i + 1]
                i += 2
            else:
                flags[key] = True
                i += 1
        else:
            if base is None:
                base = a
            i += 1

    if base is None:
        base = os.path.join(here, "sample_data")  # 默认样例, 支持从任意目录运行

    menu = load_json(os.path.join(base, "menu.json"))
    coupons = load_json(os.path.join(base, "coupons.json"))
    request = load_json(os.path.join(base, "request.json"))

    # 命令行覆盖: --mode delivery|pickup  --fee 9  --budget 30  --max-calories 800
    if "mode" in flags:
        request["dining_mode"] = flags["mode"]
    if "fee" in flags:
        request["delivery_fee"] = float(flags["fee"])
    if "budget" in flags:
        request["budget"] = float(flags["budget"])
    if "max-calories" in flags:
        request["max_calories"] = int(flags["max-calories"])

    result = optimize(menu, coupons, request)
    print(format_report(result, request))
    if flags.get("json"):
        print("\n--- JSON ---")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
