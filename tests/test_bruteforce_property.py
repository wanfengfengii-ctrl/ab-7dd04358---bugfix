"""性质测试：在随机小实例上，求解器结果必须与暴力枚举完全一致。"""

import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from solver import solve  # noqa: E402


def brute_force(payload):
    """枚举 (边料, x, y) 全组合，返回与 solve 同口径的最优键或 None。"""
    damages = payload["damages"]
    remnants = payload["remnants"]

    cands = []
    for d in damages:
        opts = []
        for ri, r in enumerate(remnants):
            if d["width"] > r["width"] or d["height"] > r["height"]:
                continue
            plo = d.get("phaseRange", {}).get("lo", 0)
            phi = d.get("phaseRange", {}).get("hi", r["period"] - 1)
            if d.get("phaseRange") is None:
                plo, phi = 0, r["period"] - 1
            for x in range(r["width"] - d["width"] + 1):
                lp = (r["origin"] + x) % r["period"]
                rp = (r["origin"] + x + d["width"]) % r["period"]
                if not (plo <= lp <= phi and plo <= rp <= phi):
                    continue
                for y in range(r["height"] - d["height"] + 1):
                    opts.append((ri, x, y, lp, rp))
        cands.append(opts)
    if any(not c for c in cands):
        return None

    best_key = None
    for combo in itertools.product(*cands):
        used = {}
        ok = True
        for i, (ri, x, y, lp, rp) in enumerate(combo):
            r = remnants[ri]
            used.setdefault(ri, 0)
            used[ri] += 1
            if used[ri] > r["uses"]:
                ok = False
                break
            w, h = damages[i]["width"], damages[i]["height"]
            for (j, (rj, x2, y2, _, _)) in enumerate(combo[:i]):
                if rj == ri:
                    w2, h2 = damages[j]["width"], damages[j]["height"]
                    if (x < x2 + w2 and x2 < x + w and
                            y < y2 + h2 and y2 < y + h):
                        ok = False
            if i > 0 and combo[i - 1][4] != lp:
                ok = False
            if not ok:
                break
        if not ok:
            continue
        distinct = len(used)
        occupied = sum(remnants[ri]["width"] * remnants[ri]["height"]
                       for ri in used)
        cut = sum(d["width"] * d["height"] for d in damages)
        lex = tuple(v for c in combo for v in (c[0], c[1], c[2]))
        key = (distinct, occupied - cut, lex)
        if best_key is None or key < best_key:
            best_key = key
    return best_key


def random_instance(rng, with_ranges=False):
    nd = rng.randint(3, 4)
    nr = rng.randint(4, 5)
    damages = []
    for _ in range(nd):
        d = {"width": rng.randint(1, 2), "height": rng.randint(1, 2)}
        if with_ranges:
            p = rng.choice([2, 3, 4])
            a = rng.randint(0, p - 1)
            b = rng.randint(a, p - 1)
            d["_periodHint"] = p
            d["phaseRange"] = {"lo": a, "hi": b}
        damages.append(d)
    remnants = []
    for _ in range(nr):
        p = rng.choice([1, 2, 3])
        if with_ranges:
            p = rng.choice([2, 3, 4])
        remnants.append({
            "width": rng.randint(2, 4),
            "height": rng.randint(2, 4),
            "period": p,
            "origin": rng.randint(0, p - 1),
            "uses": rng.randint(1, 3),
        })
    for d in damages:
        d.pop("_periodHint", None)
    return {"damages": damages, "remnants": remnants}


class TestAgainstBruteForce(unittest.TestCase):
    def test_random_instances(self):
        rng = random.Random(20260926)
        n_trials = int(os.environ.get("BRUTE_TRIALS", "120"))
        checked = 0
        for k in range(n_trials):
            payload = random_instance(rng, with_ranges=(k % 2 == 0))
            expected = brute_force(payload)
            res = solve(payload)
            if expected is None:
                self.assertFalse(res["feasible"], payload)
                continue
            self.assertTrue(res["feasible"], payload)
            cut = sum(d["width"] * d["height"] for d in payload["damages"])
            lex = tuple(v for p in res["placements"]
                        for v in (p["remnant"], p["x"], p["y"]))
            actual = (res["distinctRemnantCount"], res["wasteArea"], lex)
            self.assertEqual(actual, expected, payload)
            # 废料口径交叉校验
            self.assertEqual(res["wasteArea"],
                             res["occupiedRemnantArea"] - cut)
            checked += 1
        self.assertGreater(checked, 40)  # 确保确实有大量可行实例被比较


class TestLargeStress(unittest.TestCase):
    def test_max_sized_instance_fast(self):
        # 业务上限规模：5 处破损、8 张大边料、高可用次数
        payload = {
            "damages": [{"width": 6, "height": 5},
                        {"width": 4, "height": 7},
                        {"width": 5, "height": 5},
                        {"width": 3, "height": 6},
                        {"width": 6, "height": 4}],
            "remnants": [
                {"width": 30, "height": 20, "period": 7, "origin": i,
                 "uses": 5} for i in range(8)
            ],
        }
        import time
        t0 = time.time()
        res = solve(payload)
        self.assertTrue(res["feasible"], res)
        self.assertLess(time.time() - t0, 10.0)
        # period 相同、origin 各异：全部可压在边料0 时字典序最小
        self.assertEqual(res["distinctRemnantCount"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
