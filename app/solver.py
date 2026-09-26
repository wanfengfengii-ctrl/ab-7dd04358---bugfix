"""古籍补纸配片求解核心。

为按阅读方向排列的每一处破损，从给定边料的可裁区域中选择一张边料与
整数裁切起点，并满足：

* 每处破损恰选一张边料；裁片宽高等于破损所需宽高，裁切起点为非负整数；
* 裁片完全位于边料可裁区域内（不越界）；
* 同一张边料上的多个裁片矩形不得重叠（仅边界相接允许）；
* 相邻破损裁片接缝处的水印相位按纹样周期折算后必须相等：
      phase(m, x_i + w_i) == phase(n, x_{i+1})  (mod 周期)
* 每处破损的裁切区间还必须落在其声明的水印相位范围内（起、止两侧都在内）。

存在多个可行方案时，依次最小化：
  1. 使用边料张数（不同边料序号的数量）；
  2. 裁切废料总面积（Σ 被占用边料可裁面积 − Σ 破损所需面积）；
  3. 按破损输入顺序展开的（边料序号, 裁切起点 x, y）字典序。

无解时返回逐处核验的首条约束证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# 防止把整个坐标空间当候选枚举；手工补纸边料尺寸（毫米）远小于此。
MAX_DIMENSION = 200


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IntRange:
    """水印相位允许范围，端点按周期折算后包含。"""

    lo: int
    hi: int


@dataclass(frozen=True)
class Damage:
    idx: int
    width: int
    height: int
    phase_lo: Optional[int]
    phase_hi: Optional[int]


@dataclass(frozen=True)
class Remnant:
    idx: int
    width: int
    height: int
    period: int
    origin: int
    uses: int


@dataclass(frozen=True)
class Placement:
    damage: int
    remnant: int
    x: int
    y: int
    width: int
    height: int
    phase_left: int
    phase_right: int


@dataclass
class Evidence:
    """无法采用时的首条约束证据。"""

    code: str
    damage: Optional[int]
    remnant: Optional[int]
    message: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        d = {"code": self.code, "message": self.message}
        if self.damage is not None:
            d["damage"] = self.damage
        if self.remnant is not None:
            d["remnant"] = self.remnant
        if self.detail:
            d["detail"] = self.detail
        return d


class ValidationError(Exception):
    def __init__(self, message: str, code: str = "INVALID_REQUEST",
                 damage: Optional[int] = None, remnant: Optional[int] = None,
                 detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.evidence = Evidence(code, damage, remnant, message, detail or {})


# --------------------------------------------------------------------------- #
# 输入解析与校验
# --------------------------------------------------------------------------- #


def _as_pos_int(v: Any, name: str, code: str,
                damage: Optional[int] = None,
                remnant: Optional[int] = None) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValidationError(f"{name} 必须为正整数", code, damage, remnant,
                              {"got": repr(v)})
    if v <= 0:
        raise ValidationError(f"{name} 必须为正整数", code, damage, remnant,
                              {"got": v})
    if v > MAX_DIMENSION:
        raise ValidationError(f"{name}不得超过 {MAX_DIMENSION}", code, damage,
                              remnant, {"got": v, "max": MAX_DIMENSION})
    return v


def _as_int(v: Any, name: str, code: str,
            damage: Optional[int] = None,
            remnant: Optional[int] = None) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValidationError(f"{name} 必须为整数", code, damage, remnant,
                              {"got": repr(v)})
    return v


def _as_phase_range(spec: Dict[str, Any], damage: Damage) -> IntRange:
    raw = spec.get("phaseRange", spec.get("phase_range"))
    if raw is None:
        return None  # type: ignore[return-value]
    if not isinstance(raw, dict):
        raise ValidationError("水印相位范围必须为对象 {lo, hi}",
                              "INVALID_PHASE_RANGE", damage.idx)
    lo = _as_int(raw.get("lo"), "相位范围下限", "INVALID_PHASE_RANGE",
                 damage.idx)
    hi = _as_int(raw.get("hi"), "相位范围上限", "INVALID_PHASE_RANGE",
                 damage.idx)
    if lo < 0 or hi < 0:
        raise ValidationError("相位范围端点必须为非负整数",
                              "INVALID_PHASE_RANGE", damage.idx,
                              detail={"lo": lo, "hi": hi})
    if lo > hi:
        raise ValidationError("相位范围下限不得大于上限",
                              "INVALID_PHASE_RANGE", damage.idx,
                              detail={"lo": lo, "hi": hi})
    return IntRange(lo, hi)


def parse_request(payload: Any) -> Tuple[List[Damage], List[Remnant]]:
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须为 JSON 对象")
    dmg_raw = payload.get("damages")
    rem_raw = payload.get("remnants")
    if not isinstance(dmg_raw, list) or not (3 <= len(dmg_raw) <= 5):
        raise ValidationError("破损数量必须为 3 至 5 处", "INVALID_DAMAGE_COUNT")
    if not isinstance(rem_raw, list) or not (4 <= len(rem_raw) <= 8):
        raise ValidationError("边料数量必须为 4 至 8 张", "INVALID_REMNANT_COUNT")

    damages: List[Damage] = []
    for i, d in enumerate(dmg_raw):
        if not isinstance(d, dict):
            raise ValidationError("破损定义必须为对象", "INVALID_DAMAGE", i)
        w = _as_pos_int(d.get("width"), f"破损{i+1}宽度", "INVALID_DAMAGE", i)
        h = _as_pos_int(d.get("height"), f"破损{i+1}高度", "INVALID_DAMAGE", i)
        base = Damage(i, w, h, 0, 0)
        pr = _as_phase_range(d, base)
        damages.append(Damage(i, w, h,
                              pr.lo if pr else None,
                              pr.hi if pr else None))

    remnants: List[Remnant] = []
    for i, r in enumerate(rem_raw):
        if not isinstance(r, dict):
            raise ValidationError("边料定义必须为对象", "INVALID_REMNANT",
                                  remnant=i)
        w = _as_pos_int(r.get("width"), f"边料{i+1}可裁宽度",
                        "INVALID_REMNANT", remnant=i)
        h = _as_pos_int(r.get("height"), f"边料{i+1}可裁高度",
                        "INVALID_REMNANT", remnant=i)
        p = _as_pos_int(r.get("period"), f"边料{i+1}纹样周期",
                        "INVALID_REMNANT", remnant=i)
        o = _as_int(r.get("origin", 0), f"边料{i+1}相位原点",
                    "INVALID_REMNANT", remnant=i)
        uses = _as_pos_int(r.get("uses", 1), f"边料{i+1}可用次数",
                           "INVALID_REMNANT", remnant=i)
        remnants.append(Remnant(i, w, h, p, o, uses))

    return damages, remnants


# --------------------------------------------------------------------------- #
# 候选生成
# --------------------------------------------------------------------------- #


def _in_range(phase: int, pr: Optional[IntRange]) -> bool:
    if pr is None:
        return True
    return pr.lo <= phase <= pr.hi


def build_candidates(damages: List[Damage],
                     remnants: List[Remnant]
                     ) -> Tuple[List[List[Tuple[Remnant, int, int, int, int]]],
                                Optional[Evidence]]:
    """为每处破损生成候选 (边料, x, y, 左相位, 右相位)，按裁片字典序排列。

    候选同时满足：不越界、破损自身的起/止水印相位范围。
    若某破损无任何候选，返回首个无候选破损的证据。
    """
    all_cands: List[List[Tuple[Remnant, int, int, int, int]]] = []
    for d in damages:
        pr = IntRange(d.phase_lo, d.phase_hi) if d.phase_lo is not None else None
        cands: List[Tuple[Remnant, int, int, int, int]] = []
        first_oob: Optional[Evidence] = None
        fits_dimensionally = False
        for r in remnants:
            if d.width > r.width or d.height > r.height:
                if first_oob is None:
                    first_oob = Evidence(
                        "OUT_OF_BOUNDS", d.idx, r.idx,
                        f"破损{d.idx+1}需要 {d.width}×{d.height}，"
                        f"超过边料{r.idx+1}可裁区域 {r.width}×{r.height}",
                        {"needed": [d.width, d.height],
                         "remnantSize": [r.width, r.height]})
                continue
            fits_dimensionally = True
            max_x = r.width - d.width
            max_y = r.height - d.height
            for x in range(max_x + 1):
                lp = (r.origin + x) % r.period
                rp = (r.origin + x + d.width) % r.period
                if not _in_range(lp, pr) or not _in_range(rp, pr):
                    continue
                for y in range(max_y + 1):
                    cands.append((r, x, y, lp, rp))
        if not cands:
            if not fits_dimensionally:
                return [], first_oob
            return [], Evidence(
                "PHASE_RANGE_UNATTAINABLE", d.idx, None,
                f"破损{d.idx+1}在尺寸可容纳的边料上都无法同时满足其"
                f"水印相位范围（含起、止两侧）"
                + (f"[{d.phase_lo}, {d.phase_hi}]"
                   if d.phase_lo is not None else ""))
        # 按 (边料序号, x, y) 排序，保证字典序目标与回溯剪枝一致
        cands.sort(key=lambda c: (c[0].idx, c[1], c[2]))
        all_cands.append(cands)
    return all_cands, None


# --------------------------------------------------------------------------- #
# 几何：轴对齐矩形重叠
# --------------------------------------------------------------------------- #


def _overlap(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


# --------------------------------------------------------------------------- #
# 水印相位链的弧一致性过滤
# --------------------------------------------------------------------------- #


def phase_chain_filter(
    cands: List[List[Tuple[Remnant, int, int, int, int]]]
) -> Tuple[List[List[Tuple[Remnant, int, int, int, int]]], List[set]]:
    """把候选裁剪为"可能位于某条全局连续相位链上"的子集。

    沿破损链做前向/后向相位可达传播（接缝是等值约束的弧）：
      * fwd_left[i]：从首处出发能传播到破损 i 左缘的相位集合；
      * bwd_right[i]：破损 i 右缘能继续传播到末处的相位集合。
    候选仅当 lp∈fwd_left[i] 且 rp∈bwd_right[i] 时才可能出现在解中。
    """
    n = len(cands)
    fwd_left: List[set] = [set() for _ in range(n)]
    fwd_left[0] = {c[3] for c in cands[0]}
    for i in range(1, n):
        reach_right = {c[4] for c in cands[i - 1] if c[3] in fwd_left[i - 1]}
        fwd_left[i] = reach_right & {c[3] for c in cands[i]}

    bwd_right: List[set] = [set() for _ in range(n)]
    bwd_right[n - 1] = {c[4] for c in cands[n - 1]}
    for i in range(n - 2, -1, -1):
        need_left = {c[3] for c in cands[i + 1]
                     if c[4] in bwd_right[i + 1]}
        bwd_right[i] = need_left & {c[4] for c in cands[i]}

    filtered = [
        [c for c in cands[i] if c[3] in fwd_left[i] and c[4] in bwd_right[i]]
        for i in range(n)
    ]
    return filtered, fwd_left


# --------------------------------------------------------------------------- #
# 求解
# --------------------------------------------------------------------------- #




@dataclass
class _State:
    assignments: List[int]           # 每处破损选中的候选下标
    used_count: List[int]            # 每边料已用次数
    rects: List[List[Tuple[int, int, int, int]]]  # 每边料上已放矩形
    distinct: int                    # 已使用的不同边料张数
    waste: int                       # 当前废料面积（占用边料可裁面积之和）


def solve(payload: Any) -> Dict[str, Any]:
    damages, remnants = parse_request(payload)
    cands, evidence = build_candidates(damages, remnants)
    if evidence is not None:
        return {"feasible": False, "evidence": evidence.as_dict()}

    n_d = len(damages)
    n_r = len(remnants)
    remnant_area = [r.width * r.height for r in remnants]

    # 水印相位链弧一致性过滤：剔除不可能位于全局连续链上的候选。
    raw_seam_right = [{c[4] for c in cands[k]} for k in range(n_d - 1)]
    raw_seam_left = [{c[3] for c in cands[k + 1]} for k in range(n_d - 1)]
    cands, fwd_left = phase_chain_filter(cands)
    # 断裂位置以前向传播首个无法到达的破损为准
    break_i = next((i for i in range(n_d) if not fwd_left[i]), -1)
    if break_i > 0:
        seam = break_i - 1
        return {"feasible": False,
                "evidence": Evidence(
                    "PHASE_MISMATCH", break_i, None,
                    f"破损{break_i}裁片右缘与破损{break_i+1}裁片左缘的"
                    f"水印相位无法形成贯通全部 {n_d} 处破损的连续链",
                    {"seam": [seam, seam + 1],
                     "rightPhases": sorted(raw_seam_right[seam]),
                     "leftPhases": sorted(raw_seam_left[seam])}).as_dict()}
    if any(not cs for cs in cands):
        return {"feasible": False,
                "evidence": Evidence(
                    "PHASE_MISMATCH", None, None,
                    f"不存在贯通全部 {n_d} 处破损的连续水印相位链",
                    {}).as_dict()}

    # ------------------------------------------------------------------ #
    # 阶段一：枚举边料子集 U，按 (张数, 可裁面积和) 升序，用 MRV 回溯
    # 判定"只使用 U 中边料"是否可行。边料 ≤ 8（最多 255 个非空子集）、
    # 破损 ≤ 5，且按张数从小到大通常在 D=1..3 即命中。
    # 收集所有达到 (最优张数, 最优面积) 的可行子集，供阶段二求字典序
    # 最优；严格更差（张数更多或同张数面积更大）的子集直接停止。
    # ------------------------------------------------------------------ #

    subsets: List[Tuple[int, int, Tuple[int, ...]]] = []
    for mask in range(1, 1 << n_r):
        idxs = tuple(b for b in range(n_r) if mask & (1 << b))
        subsets.append((len(idxs), sum(remnant_area[b] for b in idxs), idxs))
    subsets.sort(key=lambda t: (t[0], t[1], t[2]))

    def feasible_on(allowed: Tuple[int, ...]) -> Optional[List[int]]:
        """MRV 回溯判定 allowed 边料集上是否可行；可行返回某完整分配。"""
        aset = set(allowed)
        # 预筛 1：次数总容量
        if sum(remnants[r].uses for r in aset) < n_d:
            return None
        local: List[List[int]] = [
            [ci for ci in range(len(cands[i]))
             if cands[i][ci][0].idx in aset]
            for i in range(n_d)
        ]
        # 预筛 2：每处破损在该子集上至少有候选
        if any(not local[i] for i in range(n_d)):
            return None
        # 预筛 3：在该子集上重算水印相位链可达性，只保留链安全候选
        fwd: List[set] = [{cands[0][ci][3] for ci in local[0]}]
        for i in range(1, n_d):
            rr = {cands[i - 1][ci][4] for ci in local[i - 1]
                  if cands[i - 1][ci][3] in fwd[-1]}
            fwd.append(rr & {cands[i][ci][3] for ci in local[i]})
            if not fwd[-1]:
                return None
        bwd: List[set] = [set() for _ in range(n_d)]
        bwd[n_d - 1] = {cands[n_d - 1][ci][4]
                        for ci in local[n_d - 1]}
        for i in range(n_d - 2, -1, -1):
            need = {cands[i + 1][ci][3] for ci in local[i + 1]
                    if cands[i + 1][ci][4] in bwd[i + 1]}
            bwd[i] = need & {cands[i][ci][4] for ci in local[i]}
            if not bwd[i]:
                return None
        for i in range(n_d):
            local[i] = [ci for ci in local[i]
                        if cands[i][ci][3] in fwd[i]
                        and cands[i][ci][4] in bwd[i]]
            if not local[i]:
                return None
        assign = [-1] * n_d
        used_count = [0] * n_r
        rects: List[List[Tuple[int, int, int, int]]] = [[] for _ in range(n_r)]

        def ok(i: int, ci: int) -> bool:
            r, x, y, lp, rp = cands[i][ci]
            if used_count[r.idx] >= r.uses:
                return False
            d = damages[i]
            rect = (x, y, d.width, d.height)
            if any(_overlap(rect, q) for q in rects[r.idx]):
                return False
            if i > 0 and assign[i - 1] >= 0 \
                    and cands[i - 1][assign[i - 1]][4] != lp:
                return False
            if i < n_d - 1 and assign[i + 1] >= 0 \
                    and rp != cands[i + 1][assign[i + 1]][3]:
                return False
            return True

        def mrv_backtrack() -> bool:
            mrv_i = -1
            mrv_opts: List[int] = []
            mrv_n = 10 ** 12
            for i in range(n_d):
                if assign[i] >= 0:
                    continue
                opts = [ci for ci in local[i] if ok(i, ci)]
                if not opts:
                    return False
                if len(opts) < mrv_n:
                    mrv_n, mrv_i, mrv_opts = len(opts), i, opts
            if mrv_i < 0:
                return True
            i = mrv_i
            d = damages[i]
            # 先试复用边料（张数紧时更快撞出解）
            opts = sorted(
                mrv_opts,
                key=lambda ci: (1 if used_count[cands[i][ci][0].idx] == 0
                                else 0, cands[i][ci][0].idx,
                                cands[i][ci][1], cands[i][ci][2]))
            for ci in opts:
                r, x, y, _, _ = cands[i][ci]
                rect = (x, y, d.width, d.height)
                assign[i] = ci
                used_count[r.idx] += 1
                rects[r.idx].append(rect)
                if mrv_backtrack():
                    return True
                rects[r.idx].pop()
                used_count[r.idx] -= 1
                assign[i] = -1
            return False

        return assign if mrv_backtrack() else None

    chosen_area: Optional[int] = None
    chosen_dim: Optional[int] = None
    feasible_subsets: List[Tuple[int, ...]] = []
    for dim, area, idxs in subsets:
        if chosen_dim is not None and (dim > chosen_dim
                                       or (dim == chosen_dim
                                           and area > chosen_area)):
            break  # 子集按 (张数, 面积) 升序，更差的无需再试
        if feasible_on(idxs) is not None:
            if chosen_dim is None:
                chosen_dim, chosen_area = dim, area
            if dim == chosen_dim and area == chosen_area:
                feasible_subsets.append(idxs)

    if chosen_dim is None:
        ev = _infeasibility_evidence(damages, remnants, cands)
        return {"feasible": False, "evidence": ev.as_dict()}

    # ------------------------------------------------------------------ #
    # 阶段二：在所有达到 (最优张数, 最优面积) 的可行子集的并集上，按
    # 破损输入顺序、候选 (边料,x,y) 升序 DFS，约束最终张数=D*、占用
    # 面积=A*。第一条完整可行路径即全局字典序最小方案。
    # ------------------------------------------------------------------ #
    aset = {b for idxs in feasible_subsets for b in idxs}
    ordered_local: List[List[int]] = [
        [ci for ci, c in enumerate(cands[i]) if c[0].idx in aset]
        for i in range(n_d)
    ]
    # cands[i] 已按 (边料序号, x, y) 排序，ordered_local 保序。
    final_assign = [-1] * n_d
    used_count = [0] * n_r
    used_area = 0
    rects2: List[List[Tuple[int, int, int, int]]] = [[] for _ in range(n_r)]

    def lex_backtrack(i: int, distinct: int, used_area: int) -> bool:
        # 张数/面积不得越过最优值
        if distinct > chosen_dim or used_area > chosen_area:
            return False
        if i == n_d:
            return distinct == chosen_dim and used_area == chosen_area
        d = damages[i]
        prev_rp = cands[i - 1][final_assign[i - 1]][4] if i > 0 else None
        for ci in ordered_local[i]:
            r, x, y, lp, rp = cands[i][ci]
            if prev_rp is not None and lp != prev_rp:
                continue
            fresh = used_count[r.idx] == 0
            if fresh and distinct + 1 > chosen_dim:
                continue
            if used_count[r.idx] >= r.uses:
                continue
            new_area = used_area + (remnant_area[r.idx] if fresh else 0)
            if new_area > chosen_area:
                continue
            rect = (x, y, d.width, d.height)
            if any(_overlap(rect, q) for q in rects2[r.idx]):
                continue
            final_assign[i] = ci
            used_count[r.idx] += 1
            rects2[r.idx].append(rect)
            if lex_backtrack(i + 1,
                             distinct + (1 if fresh else 0), new_area):
                return True
            rects2[r.idx].pop()
            used_count[r.idx] -= 1
            final_assign[i] = -1
        return False

    if not lex_backtrack(0, 0, 0):
        # 理论上不会发生（阶段一已证至少一个子集可行且面积达标）
        ev = _infeasibility_evidence(damages, remnants, cands)
        return {"feasible": False, "evidence": ev.as_dict()}

    final_state = _State(
        assignments=final_assign,
        used_count=[0] * n_r,
        rects=[[] for _ in range(n_r)],
        distinct=0, waste=0)
    for i, ci in enumerate(final_assign):
        r, x, y, _, _ = cands[i][ci]
        final_state.used_count[r.idx] += 1
        final_state.rects[r.idx].append(
            (x, y, damages[i].width, damages[i].height))
    final_state.distinct = sum(1 for n in final_state.used_count if n > 0)
    final_state.waste = sum(remnant_area[r]
                            for r, n in enumerate(final_state.used_count)
                            if n > 0)

    return _materialize(final_assign, cands, damages, remnants, final_state)


def _materialize(assignments: List[int],
                 cands: List[List[Tuple[Remnant, int, int, int, int]]],
                 damages: List[Damage], remnants: List[Remnant],
                 state: _State) -> Dict[str, Any]:
    placements: List[Dict[str, Any]] = []
    for i, ci in enumerate(assignments):
        r, x, y, lp, rp = cands[i][ci]
        d = damages[i]
        placements.append({
            "damage": i,
            "remnant": r.idx,
            "x": x,
            "y": y,
            "width": d.width,
            "height": d.height,
            "phaseLeft": lp,
            "phaseRight": rp,
        })
    used = [idx for idx, n in enumerate(state.used_count) if n > 0]
    occupied = sum(remnants[idx].width * remnants[idx].height for idx in used)
    cut_area = sum(d.width * d.height for d in damages)
    return {
        "feasible": True,
        "placements": placements,
        "usedRemnants": used,
        "distinctRemnantCount": len(used),
        "cutArea": cut_area,
        "occupiedRemnantArea": occupied,
        # 裁切废料总面积 = 占用边料可裁面积 − 实际补入面积；
        # cutArea 对所有方案为常数，故直接按占用面积优化等价。
        "wasteArea": occupied - cut_area,
        "totalRemnantArea": occupied,
    }


# --------------------------------------------------------------------------- #
# 无解证据：逐处核验，返回首条
# --------------------------------------------------------------------------- #


def _infeasibility_evidence(damages: List[Damage], remnants: List[Remnant],
                            cands: List[List[Tuple[Remnant, int, int, int, int]]]
                            ) -> Evidence:
    """候选本身都合法（不越界/相位范围），不可行只可能来自组合约束。

    按破损阅读方向逐接缝、逐处核验，返回最先发现的约束证据：
      1. 接缝两侧不存在任何相位可衔接的候选对；
      2. 贪心构造中首个因次数耗尽 / 同料重叠而无法放置的破损。
    """
    n_d = len(damages)

    # 逐接缝：是否存在左右候选对相位相等
    for i in range(n_d - 1):
        right_set = {ca[4] for ca in cands[i]}
        left_set = {cb[3] for cb in cands[i + 1]}
        if right_set.isdisjoint(left_set):
            return Evidence(
                "PHASE_MISMATCH", i + 1, None,
                f"破损{i+1}裁片右缘与破损{i+2}裁片左缘的水印相位"
                f"在任何整数裁切起点下都无法按周期折算相等",
                {"seam": [i, i + 1],
                 "rightPhases": sorted(right_set),
                 "leftPhases": sorted(left_set)})

    # 报告构造中首个无法放置的破损及其直接原因
    ev = _greedy_first_failure(damages, remnants, cands)
    if ev is not None:
        return ev

    return Evidence(
        "NO_SOLUTION", None, None,
        "所有硬约束（次数、不重叠、接缝相位）无法同时满足")


def _greedy_first_failure(damages: List[Damage], remnants: List[Remnant],
                          cands: List[List[Tuple[Remnant, int, int, int, int]]]
                          ) -> Optional[Evidence]:
    """定位首个资源类失败的破损。

    先做水印相位链的前/后向可达传播，选出"链安全"候选（既能承接前序
    相位、又能把相位延续到末处）。在链安全候选上按阅读顺序贪心放置；
    若某破损失败，则必为边料次数或同料重叠所致，归因不会误伤相位。
    """
    n_d = len(damages)
    left_sets = [{c[3] for c in cands[i]} for i in range(n_d)]

    # 前向可达：F[i] = 破损 i 可承接的左缘相位集合
    fwd: List[set] = [set(left_sets[0])]
    for i in range(1, n_d):
        reachable_right = {c[4] for c in cands[i - 1] if c[3] in fwd[-1]}
        fwd.append(reachable_right & left_sets[i])
        if not fwd[-1]:
            return Evidence(
                "PHASE_MISMATCH", i, None,
                f"破损{i+1}的左缘水印相位无法与前 {i} 处破损形成"
                f"连续链（虽存在两两相等的接缝，但无法贯通）",
                {"seam": [i - 1, i]})

    # 后向可达：safe 候选的右缘必须能被尾链接住
    can_finish_right: List[set] = [set()] * n_d
    can_finish_right[n_d - 1] = {c[4] for c in cands[n_d - 1]}
    for i in range(n_d - 2, -1, -1):
        tail_left = {c[3] for c in cands[i + 1]
                     if c[4] in can_finish_right[i + 1]}
        can_finish_right[i] = {c[4] for c in cands[i] if c[3] in fwd[i]
                               and c[4] in tail_left}

    used_count = [0] * len(remnants)
    rects: List[List[Tuple[int, int, int, int]]] = [[] for _ in remnants]
    prev_rp: Optional[int] = None

    for i, d in enumerate(damages):
        n_uses = n_overlap = 0
        block_rem: Optional[int] = None
        placed = False
        for (r, x, y, lp, rp) in cands[i]:
            if lp not in fwd[i] or rp not in can_finish_right[i]:
                continue
            if prev_rp is not None and lp != prev_rp:
                continue
            if used_count[r.idx] >= r.uses:
                n_uses += 1
                block_rem = block_rem if block_rem is not None else r.idx
                continue
            rect = (x, y, d.width, d.height)
            if any(_overlap(rect, q) for q in rects[r.idx]):
                n_overlap += 1
                block_rem = block_rem if block_rem is not None else r.idx
                continue
            used_count[r.idx] += 1
            rects[r.idx].append(rect)
            prev_rp = rp
            placed = True
            break
        if not placed:
            if n_uses > 0 and n_overlap == 0:
                return Evidence(
                    "USES_EXHAUSTED", i, block_rem,
                    f"破损{i+1}所有可衔接水印相位的边料可用次数均已耗尽")
            if n_overlap > 0 and n_uses == 0:
                return Evidence(
                    "OVERLAP", i, block_rem,
                    f"破损{i+1}在可衔接边料上的所有整数裁切起点均与"
                    f"同料既有裁片重叠")
            return Evidence(
                "USES_EXHAUSTED" if n_uses >= n_overlap else "OVERLAP",
                i, block_rem,
                f"破损{i+1}无法放置：可衔接边料次数耗尽"
                f"（{n_uses}个候选）或与同料裁片重叠（{n_overlap}个候选）")
    return None
