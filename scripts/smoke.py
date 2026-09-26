#!/usr/bin/env python3
"""对运行中的服务执行 API 冒烟测试。

用法：python scripts/smoke.py [base_url]
全部断言通过则退出码 0，否则非零。
"""

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"


def request(method: str, path: str, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def check(cond: bool, name: str) -> None:
    print(("  ✓ " if cond else "  ✗ ") + name)
    if not cond:
        raise SystemExit(f"冒烟断言失败: {name}")


def main() -> None:
    print(f"冒烟目标: {BASE}")

    # 1. 健康检查
    status, body = request("GET", "/healthz")
    check(status == 200, f"GET /healthz → 200 (实际 {status})")
    check(json.loads(body)["status"] == "ok", "健康检查返回 status=ok")

    # 2. 前端首页
    status, body = request("GET", "/")
    check(status == 200 and "古籍补纸配片" in body, "GET / 返回前端首页")

    # 3. 可行配片：period=1 恒同相，一张大边料可容纳三片
    feasible_payload = {
        "damages": [
            {"width": 2, "height": 2},
            {"width": 3, "height": 2},
            {"width": 2, "height": 2},
        ],
        "remnants": [
            {"width": 12, "height": 6, "period": 1, "origin": 0, "uses": 3},
            {"width": 4, "height": 3, "period": 1, "origin": 0, "uses": 1},
            {"width": 5, "height": 4, "period": 1, "origin": 0, "uses": 1},
            {"width": 3, "height": 3, "period": 1, "origin": 0, "uses": 1},
        ],
    }
    status, body = request("POST", "/api/solve", feasible_payload)
    check(status == 200, f"可行请求 → 200 (实际 {status})")
    res = json.loads(body)
    check(res["feasible"] is True, "返回 feasible=true")
    check(len(res["placements"]) == 3, "逐处返回 3 个裁片")
    check(res["distinctRemnantCount"] == 1, "三级目标①：仅用 1 张边料")
    for p in res["placements"]:
        check(p["x"] + p["width"] <= 12 and p["y"] + p["height"] <= 6,
              f"破损{p['damage']+1} 裁片不越界")
        check("phaseLeft" in p and "phaseRight" in p,
              f"破损{p['damage']+1} 返回两侧相位")
    for i in range(2):
        check(res["placements"][i]["phaseRight"]
              == res["placements"][i + 1]["phaseLeft"],
              f"接缝 {i+1}-{i+2} 水印相位相等")
    rects = [(p["remnant"], p["x"], p["y"], p["width"], p["height"])
             for p in res["placements"]]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if rects[i][0] != rects[j][0]:
                continue
            _, ax, ay, aw, ah = rects[i]
            _, bx, by, bw, bh = rects[j]
            check(not (ax < bx+bw and bx < ax+aw and ay < by+bh
                       and by < ay+ah),
                  "同一边料上的裁片不重叠")

    # 4. 无解：接缝相位集合不相交
    infeasible_payload = {
        "damages": [
            {"width": 3, "height": 1, "phaseRange": {"lo": 0, "hi": 0}},
            {"width": 3, "height": 1, "phaseRange": {"lo": 1, "hi": 1}},
            {"width": 1, "height": 1},
        ],
        "remnants": [
            {"width": 9, "height": 2, "period": 3, "origin": 0, "uses": 3},
            {"width": 6, "height": 2, "period": 3, "origin": 0, "uses": 1},
            {"width": 6, "height": 2, "period": 3, "origin": 0, "uses": 1},
            {"width": 6, "height": 2, "period": 3, "origin": 0, "uses": 1},
        ],
    }
    status, body = request("POST", "/api/solve", infeasible_payload)
    res = json.loads(body)
    check(res["feasible"] is False, "无解请求返回 feasible=false")
    check(res["evidence"]["code"] == "PHASE_MISMATCH",
          f"首条约束证据为 PHASE_MISMATCH (实际 {res['evidence']['code']})")
    check(bool(res["evidence"]["message"]), "证据含中文说明")

    # 5. 输入校验
    bad_payload = {"damages": [{"width": 1, "height": 1}],
                   "remnants": [{"width": 2, "height": 2, "period": 1}] * 4}
    status, body = request("POST", "/api/solve", bad_payload)
    check(status == 400, f"非法请求 → 400 (实际 {status})")
    check(json.loads(body)["evidence"]["code"] == "INVALID_DAMAGE_COUNT",
          "破损数量越界被拒绝")

    print("全部冒烟断言通过 ✅")


if __name__ == "__main__":
    main()
