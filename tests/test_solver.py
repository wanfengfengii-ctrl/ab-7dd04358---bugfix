"""求解器单元测试：硬约束、优化目标、证据定位。

运行：python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from solver import (  # noqa: E402
    ValidationError, parse_request, solve, build_candidates,
)


def dmg(w, h, plo=None, phi=None):
    d = {"width": w, "height": h}
    if plo is not None:
        d["phaseRange"] = {"lo": plo, "hi": phi if phi is not None else plo}
    return d


def rem(w, h, p, o=0, uses=1):
    return {"width": w, "height": h, "period": p, "origin": o, "uses": uses}


def req(damages, remnants):
    return {"damages": damages, "remnants": remnants}


class TestValidation(unittest.TestCase):
    def test_counts(self):
        with self.assertRaises(ValidationError) as cm:
            solve(req([dmg(1, 1)] * 2, [rem(2, 2, 1)] * 4))
        self.assertEqual(cm.exception.evidence.code, "INVALID_DAMAGE_COUNT")
        with self.assertRaises(ValidationError):
            solve(req([dmg(1, 1)] * 3, [rem(2, 2, 1)] * 3))

    def test_type_and_nonpositive(self):
        with self.assertRaises(ValidationError):
            parse_request(req([dmg(0, 1)] * 3, [rem(2, 2, 1)] * 4))
        with self.assertRaises(ValidationError):
            parse_request(req([dmg("2", 1)] * 3, [rem(2, 2, 1)] * 4))
        with self.assertRaises(ValidationError):
            parse_request(req([dmg(1, 1)] * 3, [rem(2, 2, 0)] * 4))

    def test_phase_range_order(self):
        with self.assertRaises(ValidationError):
            parse_request(
                req([dmg(1, 1, 3, 2)] + [dmg(1, 1)] * 2,
                    [rem(2, 2, 4)] * 4))


class TestBasicFeasible(unittest.TestCase):
    def test_simple_chain_same_sheet(self):
        # period 1 → 所有相位恒为 0；一张大边料可放三片，uses=3
        r = solve(req(
            [dmg(2, 2), dmg(2, 2), dmg(2, 2)],
            [rem(10, 10, 1, uses=3)] + [rem(2, 2, 1)] * 3))
        self.assertTrue(r["feasible"], r)
        # 三级目标第一级：只需 1 张边料
        self.assertEqual(r["distinctRemnantCount"], 1)
        self.assertEqual(r["usedRemnants"], [0])
        ps = r["placements"]
        # 字典序：首片 (0,0,0)，第二片紧挨不重叠
        self.assertEqual((ps[0]["remnant"], ps[0]["x"], ps[0]["y"]),
                         (0, 0, 0))
        for p in ps:
            self.assertLessEqual(p["x"] + p["width"], 10)
            self.assertLessEqual(p["y"] + p["height"], 10)
        # 不重叠
        rects = [(p["x"], p["y"], p["width"], p["height"]) for p in ps]
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ax, ay, aw, ah = rects[i]
                bx, by, bw, bh = rects[j]
                self.assertFalse(
                    ax < bx + bw and bx < ax + aw and ay < by + ah
                    and by < ay + ah, "同一边料上的裁片重叠")

    def test_phase_continuity_across_remnants(self):
        # 破损宽 2，period 3：右缘相位 = origin + x + 2 (mod 3)
        sheet = [rem(3, 1, 3, o=0), rem(3, 1, 3, o=1),
                 rem(3, 1, 3, o=2), rem(3, 1, 3, o=0)]
        r = solve(req(
            [dmg(2, 1), dmg(2, 1), dmg(2, 1)], sheet))
        self.assertTrue(r["feasible"], r)
        ps = r["placements"]
        for i in range(2):
            self.assertEqual(ps[i]["phaseRight"], ps[i + 1]["phaseLeft"],
                             "接缝水印相位必须相等")
        for p in ps:
            s = sheet[p["remnant"]]
            self.assertEqual(p["phaseLeft"],
                             (s["origin"] + p["x"]) % s["period"])
            self.assertEqual(p["phaseRight"],
                             (s["origin"] + p["x"] + p["width"])
                             % s["period"])

    def test_returns_both_edge_phases(self):
        r = solve(req(
            [dmg(2, 3), dmg(3, 2), dmg(1, 1)],
            [rem(8, 8, 5, o=2, uses=3)] + [rem(4, 4, 5)] * 3))
        self.assertTrue(r["feasible"])
        for p in r["placements"]:
            self.assertIn("phaseLeft", p)
            self.assertIn("phaseRight", p)


class TestOutOfBounds(unittest.TestCase):
    def test_damage_larger_than_all_remnants(self):
        r = solve(req(
            [dmg(9, 9), dmg(1, 1), dmg(1, 1)],
            [rem(2, 2, 1)] * 4))
        self.assertFalse(r["feasible"])
        self.assertEqual(r["evidence"]["code"], "OUT_OF_BOUNDS")
        self.assertEqual(r["evidence"]["damage"], 0)
        self.assertEqual(r["evidence"]["remnant"], 0)

    def test_height_exceeded_reported(self):
        r = solve(req(
            [dmg(1, 1), dmg(1, 5), dmg(1, 1)],
            [rem(3, 3, 1)] * 4))
        self.assertFalse(r["feasible"])
        self.assertEqual(r["evidence"]["code"], "OUT_OF_BOUNDS")
        self.assertEqual(r["evidence"]["damage"], 1)


class TestPhaseRange(unittest.TestCase):
    def test_unattainable_single_point(self):
        # period 4, damage width 2: 右相位 = x+2 mod4 ∈ {2,3,...}随x；
        # 要求左右都等于固定值只有 width ≡ 0 mod period 才可能。
        r = solve(req(
            [dmg(2, 1, 0, 0), dmg(1, 1), dmg(1, 1)],
            [rem(8, 2, 4, uses=3)] + [rem(4, 2, 4)] * 3))
        self.assertFalse(r["feasible"])
        self.assertEqual(r["evidence"]["code"], "PHASE_RANGE_UNATTAINABLE")
        self.assertEqual(r["evidence"]["damage"], 0)

    def test_range_restricts_start(self):
        # width = period=4 → 左右同相；范围 [1,2] 允许 x∈{1,2}，
        # 接缝连续要求整链同相，字典序最小 → 全部 x=1、相位 1
        r = solve(req(
            [dmg(4, 1, 1, 2), dmg(4, 1, 1, 2), dmg(4, 1, 1, 2)],
            [rem(6, 2, 4, o=0, uses=3)] + [rem(6, 2, 4, o=0)] * 3))
        self.assertTrue(r["feasible"], r)
        for p in r["placements"]:
            self.assertEqual(p["phaseLeft"], 1)
            self.assertEqual(p["phaseRight"], 1)
            self.assertEqual(p["x"], 1)


class TestOverlapAndUses(unittest.TestCase):
    def test_uses_limit_forces_extra_sheet(self):
        # 三张破损都只能用边料0（其余太小），但 uses=1 且单片铺满 → 无解
        r = solve(req(
            [dmg(4, 4), dmg(4, 4), dmg(4, 4)],
            [rem(4, 4, 1, uses=1)] + [rem(3, 3, 1)] * 3))
        self.assertFalse(r["feasible"])
        self.assertIn(r["evidence"]["code"],
                      ("USES_EXHAUSTED", "OVERLAP", "NO_SOLUTION"))
        self.assertEqual(r["evidence"]["damage"], 1)

    def test_nonoverlap_edge_touch_allowed(self):
        # 边料 6×2，三片 2×2 横排恰好相接，uses=3 → 可行
        r = solve(req(
            [dmg(2, 2), dmg(2, 2), dmg(2, 2)],
            [rem(6, 2, 1, uses=3)] + [rem(2, 2, 1)] * 3))
        self.assertTrue(r["feasible"], r)
        self.assertEqual(r["distinctRemnantCount"], 1)
        xs = sorted(p["x"] for p in r["placements"])
        self.assertEqual(xs, [0, 2, 4])

    def test_overlap_forces_two_sheets(self):
        # 边料0 只能横放两片（4×2 放两片 2×2），第三片必须去边料1
        r = solve(req(
            [dmg(2, 2), dmg(2, 2), dmg(2, 2)],
            [rem(4, 2, 1, uses=3), rem(2, 2, 1, uses=1),
             rem(2, 2, 1), rem(2, 2, 1)]))
        self.assertTrue(r["feasible"], r)
        self.assertEqual(r["distinctRemnantCount"], 2)


class TestPhaseMismatchEvidence(unittest.TestCase):
    def test_pairwise_seams_ok_but_no_global_chain(self):
        # period 5、原点0：
        # 破损0 宽5、相位点0 → 右缘只能是 0；
        # 破损1 宽1、相位范围[0,3] → 左∈{0,1,2}、右=左+1∈{1,2,3}，
        #   能承接 0 时右缘只能是 1；
        # 破损2 左缘只接受 3。
        # 逐接缝看：接缝0 {0}∩{0,1,2} 非空；接缝1 {1,2,3}∩{3} 非空，
        # 但能贯通的右缘只有 1，接不住破损2 → 无全局链。
        damages = [
            dmg(5, 1, 0, 0),
            dmg(1, 1, 0, 3),
            dmg(5, 1, 3, 3),
        ]
        r = solve(req(
            damages,
            [rem(12, 3, 5, o=0, uses=3)] + [rem(10, 3, 5)] * 3))
        self.assertFalse(r["feasible"])
        self.assertEqual(r["evidence"]["code"], "PHASE_MISMATCH")
        self.assertEqual(r["evidence"]["detail"]["seam"], [1, 2])

    def test_seam_never_matches(self):
        # period 3 下：破损0 宽3 且相位范围 [0,0]（左右恒为 0）；
        # 破损1 宽3 且相位范围 [1,1]（左右恒为 1）。
        # 各自都能放置，但接缝相位集合 {0} 与 {1} 永不相交。
        damages = [
            dmg(3, 1, 0, 0),
            dmg(3, 1, 1, 1),
            dmg(1, 1),
        ]
        r = solve(req(
            damages,
            [rem(9, 2, 3, o=0, uses=3)] + [rem(6, 2, 3)] * 3))
        self.assertFalse(r["feasible"])
        self.assertEqual(r["evidence"]["code"], "PHASE_MISMATCH")
        self.assertEqual(r["evidence"]["detail"]["seam"], [0, 1])
        self.assertEqual(r["evidence"]["detail"]["rightPhases"], [0])
        self.assertEqual(r["evidence"]["detail"]["leftPhases"], [1])


class TestOptimizationOrder(unittest.TestCase):
    def test_min_distinct_beats_waste(self):
        # 方案A：1 张大边料放三片（占用面积 100）
        # 方案B：3 张小边料各一片（占用 3*9=27，废料更少但张数多）
        r = solve(req(
            [dmg(3, 3), dmg(3, 3), dmg(3, 3)],
            [rem(10, 10, 1, uses=3),
             rem(3, 3, 1), rem(3, 3, 1), rem(3, 3, 1)]))
        self.assertTrue(r["feasible"])
        self.assertEqual(r["distinctRemnantCount"], 1)
        self.assertEqual(r["occupiedRemnantArea"], 100)

    def test_waste_tiebreak(self):
        # 张数都为 1 时，选可裁面积最小的边料
        r = solve(req(
            [dmg(2, 2), dmg(2, 2), dmg(2, 2)],
            [rem(10, 10, 1, uses=3),   # 大
             rem(6, 1, 1, uses=3),     # 放不下（高1）
             rem(2, 6, 1, uses=3),     # 6*2=12，可竖排三片
             rem(8, 8, 1, uses=3)]))   # 大
        self.assertTrue(r["feasible"])
        self.assertEqual(r["distinctRemnantCount"], 1)
        self.assertEqual(r["occupiedRemnantArea"], 12)

    def test_lexicographic_tiebreak(self):
        # 两张完全等大、同周期、同原点的边料，uses 充足：
        # 字典序最小 → 全部使用边料0，起点从 (0,0) 起
        r = solve(req(
            [dmg(1, 1), dmg(1, 1), dmg(1, 1)],
            [rem(4, 4, 1, uses=3), rem(4, 4, 1, uses=3),
             rem(4, 4, 1), rem(4, 4, 1)]))
        self.assertTrue(r["feasible"])
        seq = [(p["remnant"], p["x"], p["y"]) for p in r["placements"]]
        # (remnant, x, y) 字典序：y 先递增
        self.assertEqual(seq, [(0, 0, 0), (0, 0, 1), (0, 0, 2)])


class TestWasteAccounting(unittest.TestCase):
    def test_waste_formula(self):
        r = solve(req(
            [dmg(2, 2), dmg(2, 2), dmg(2, 2)],
            [rem(6, 2, 1, uses=3)] + [rem(2, 2, 1)] * 3))
        self.assertTrue(r["feasible"])
        self.assertEqual(r["cutArea"], 12)
        self.assertEqual(r["occupiedRemnantArea"], 12)
        self.assertEqual(r["wasteArea"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
