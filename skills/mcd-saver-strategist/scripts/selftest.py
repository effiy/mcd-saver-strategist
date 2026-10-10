#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门省钱精算师 · 自测用例

运行:  python selftest.py
覆盖:  组合价券 / 单品券 / 满减 / 赠品 / 预算过滤 / 热量过滤 / 确定性 /
       叠加策略 / 券渠道过滤 / 外送费结算 / 场景影响券可用性
"""

from __future__ import annotations

import copy
import sys

from optimizer import (
    optimize,
    price_with_basket,
    coupon_conflict,
    filter_coupons_for_mode,
)

MENU = {
    "store_code": "T",
    "currency": "CNY",
    "items": [
        {"code": "BURGER", "name": "汉堡", "category": "burger", "price": 20.0, "calories": 500, "tags": ["汉堡"]},
        {"code": "FRIES", "name": "薯条", "category": "side", "price": 12.0, "calories": 340, "tags": ["薯条"]},
        {"code": "COKE", "name": "可乐", "category": "drink", "price": 9.0, "calories": 150, "tags": ["可乐"]},
        {"code": "PIE", "name": "派", "category": "dessert", "price": 7.0, "calories": 230, "tags": ["派"]},
    ],
}
COUPONS = {"coupons": [
    {"id": "B1", "type": "item_price", "title": "汉堡特价", "item_codes": ["BURGER"], "override_price": 15.0, "stackable": False},
    {"id": "T1", "type": "threshold", "title": "满30减8", "min_spend": 30.0, "discount": 8.0, "stackable": True},
    {"id": "T2", "type": "threshold", "title": "满20减3", "min_spend": 20.0, "discount": 3.0, "stackable": True},
    {"id": "U1", "type": "bundle_price", "title": "1+1", "groups": [["BURGER"], ["FRIES", "COKE"]], "price": 13.0, "stackable": False},
    {"id": "G1", "type": "free_gift", "title": "满20送派", "min_spend": 20.0, "gift_codes": ["PIE"], "stackable": True},
]}

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  {detail}")


def idx(codes):
    by = {i["code"]: i for i in MENU["items"]}
    return [by[c] for c in codes]


def main() -> int:
    print("== 1. 单品改价券 ==")
    r = price_with_basket(idx(["BURGER", "FRIES"]), ["B1"], {"B1": COUPONS["coupons"][0]})
    check("汉堡被改价到 15", r is not None and r["total"] == 27.0, str(r))

    print("== 2. 满减券 ==")
    r = price_with_basket(idx(["BURGER", "FRIES"]), ["T1"], {"T1": COUPONS["coupons"][1]})
    check("满30减8 生效", r["total"] == 24.0, str(r))
    r = price_with_basket(idx(["COKE"]), ["T1"], {"T1": COUPONS["coupons"][1]})
    check("小计未达门槛不减免", r["total"] == 9.0, str(r))

    print("== 3. 组合价券 ==")
    r = price_with_basket(idx(["BURGER", "FRIES"]), ["U1"], {"U1": COUPONS["coupons"][3]})
    check("1+1 打包价 13", r["total"] == 13.0, str(r))

    print("== 4. 赠品券门槛 ==")
    r = price_with_basket(idx(["BURGER"]), ["G1"], {"G1": COUPONS["coupons"][4]})
    check("满20送派", r["gifts"] == ["PIE"], str(r))
    r = price_with_basket(idx(["PIE"]), ["G1"], {"G1": COUPONS["coupons"][4]})
    check("未达门槛无赠品", r["gifts"] == [], str(r))

    print("== 5. 叠加策略(不可叠券互斥) ==")
    check("单品券与满减互斥", coupon_conflict(COUPONS["coupons"][0], COUPONS["coupons"][1]) is True)
    check("两张满减可叠加", coupon_conflict(COUPONS["coupons"][1], COUPONS["coupons"][2]) is False)

    print("== 6. 端到端: 挑出最低价 ==")
    base_req = {"wants": ["汉堡", "薯条", "可乐"], "max_items": 3, "allow_extras": True}
    res = optimize(MENU, COUPONS, base_req)
    best = res["plans"][0]
    # 1+1 打包(13) + 剩余可乐(9) = 22; 或 汉堡特价15+薯条12+可乐9-... 单品券不可与满减叠
    check("最优价 = 22.0", best["total"] == 22.0, str(best))
    check("最优方案用了组合券", any(c["id"] == "U1" for c in best["coupons"]), str(best))

    print("== 7. 预算过滤 ==")
    req = copy.deepcopy(base_req); req["budget"] = 15.0
    res = optimize(MENU, COUPONS, req)
    check("预算15元内无可严格满足的方案或均超预算", all(p["total"] <= 15.0 for p in res["plans"]), str(res["plans"][:1]))

    print("== 8. 热量过滤 ==")
    req = copy.deepcopy(base_req); req["max_calories"] = 400
    res = optimize(MENU, COUPONS, req)
    check("热量上限400时过滤掉高卡组合", all(p["calories"] <= 400 for p in res["plans"]), str([p["calories"] for p in res["plans"]]))

    print("== 9. 确定性 ==")
    a = optimize(MENU, COUPONS, base_req)
    b = optimize(MENU, COUPONS, base_req)
    check("相同输入结果一致", a == b)

    print("== 10. 券渠道过滤 ==")
    ch_coupons = [
        {"id": "P1", "type": "threshold", "title": "到店券", "min_spend": 10.0, "discount": 2.0, "stackable": True, "channel": "pickup"},
        {"id": "D1", "type": "threshold", "title": "外送券", "min_spend": 10.0, "discount": 3.0, "stackable": True, "channel": "delivery"},
        {"id": "A1", "type": "threshold", "title": "通用券", "min_spend": 10.0, "discount": 1.0, "stackable": True},
    ]
    pick = filter_coupons_for_mode(ch_coupons, "pickup")
    dlv = filter_coupons_for_mode(ch_coupons, "delivery")
    check("到店场景保留到店券+通用券", {c["id"] for c in pick} == {"P1", "A1"}, str([c["id"] for c in pick]))
    check("外送场景保留外送券+通用券", {c["id"] for c in dlv} == {"D1", "A1"}, str([c["id"] for c in dlv]))

    print("== 11. 外送费计入总价 ==")
    req_d = {"wants": ["汉堡", "薯条"], "max_items": 3, "allow_extras": True,
             "dining_mode": "delivery", "delivery_fee": 6.0}
    res_d = optimize(copy.deepcopy(MENU), {"coupons": []}, req_d)
    best_d = res_d["plans"][0]
    check("总价 = 商品原价 + 外送费", abs(best_d["total"] - (best_d["raw_total"] + 6.0)) < 1e-9, str(best_d))
    check("结果标记场景与外送费", res_d["dining_mode"] == "delivery" and res_d["delivery_fee"] == 6.0, str(res_d["dining_mode"]))

    print("== 12. 场景影响券可用性 ==")
    mixed = {"coupons": [
        {"id": "P9", "type": "item_price", "title": "到店汉堡特价",
         "item_codes": ["BURGER"], "override_price": 10.0, "stackable": False, "channel": "pickup"},
    ]}
    req_p = {"wants": ["汉堡"], "max_items": 2, "allow_extras": False, "dining_mode": "pickup"}
    req_d2 = {"wants": ["汉堡"], "max_items": 2, "allow_extras": False, "dining_mode": "delivery"}
    res_p = optimize(copy.deepcopy(MENU), mixed, req_p)
    res_d2 = optimize(copy.deepcopy(MENU), mixed, req_d2)
    check("到店场景可用到店券(汉堡 10 元)", res_p["plans"][0]["lines"][0]["price"] == 10.0, str(res_p["plans"][0]["lines"]))
    check("外送场景排除到店券(汉堡原价 20)", res_d2["plans"][0]["lines"][0]["price"] == 20.0, str(res_d2["plans"][0]["lines"]))

    print(f"\n结果: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
