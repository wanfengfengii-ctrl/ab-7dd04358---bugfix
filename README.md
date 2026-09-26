# 古籍补纸配片服务

修复室录入 3–5 处按阅读方向排列的破损（每处所需宽高、水印相位范围）与
4–8 张边料（可裁区域、纹样周期、相位原点、可用次数），服务端为每处破损
恰选一张边料与整数裁切起点，并在多个可行方案中按以下固定优先级择优：

1. **使用边料张数最少**；
2. **裁切废料总面积最小**（占用边料可裁面积 − 实际补入面积）；
3. 按破损输入顺序展开的 `(边料序号, 起点x, 起点y)` **字典序最小**。

## 硬约束

- 每处破损恰选一张边料，裁切宽高等于所需宽高，起点为非负整数；
- 裁片完全位于边料可裁区域内（不越界）；
- 同一边料上的多个裁片轴对齐矩形不得重叠（边界相接允许）；
- 边料使用次数不得超过其可用次数；
- 相邻破损裁片接缝处水印相位按各自纹样周期折算后必须相等：
  `phase_right(i) == phase_left(i+1)`，其中
  `phase = (边料相位原点 + 绝对x坐标) mod 纹样周期`；
- 每处破损裁片的起、止两侧相位都必须落在其声明的水印相位范围内。

## 技术栈

- 后端：Python 3.11 **标准库**（`http.server` + 自研 CSP 求解器），零第三方依赖；
- 前端：原生 HTML/CSS/JavaScript，无需构建；
- 求解器（两阶段精确算法）：
  1. 按 (张数, 可裁面积和) 升序枚举边料子集，用 MRV 回溯 + 次数容量/
     相位链可达性预筛判定可行性，收集所有达到 (最优张数, 最优面积)
     的可行子集；
  2. 在这些子集的并集上按破损输入顺序、候选 (边料,x,y) 升序 DFS，
     约束张数与面积不越最优值，第一条完整路径即全局字典序最小方案；
  另对候选做水印相位链的前/后向可达传播（弧一致性过滤）；
- 交付：Dockerfile、Docker Compose（健康检查、可配置宿主机端口、`verify` 一次性验证服务）。

## 目录结构

```
app/solver.py    配片求解核心（输入校验、候选生成、回溯优化、无解证据）
app/server.py    HTTP 服务（静态前端 + /api/solve + /healthz）
web/             前端页面
tests/           单元测试 + 随机实例对拍性质测试
scripts/smoke.py API 冒烟
scripts/verify.py 测试 → 构建校验 → 冒烟 的一次性入口
Dockerfile
docker-compose.yml
```

## 本地运行（无需 Docker）

```bash
python3 app/server.py            # 默认 0.0.0.0:8080
PORT=9090 python3 app/server.py  # 自定义端口
```

浏览器打开 <http://localhost:8080>，调整破损/边料草稿后点击“发起配片”。

## Docker 运行

```bash
docker compose up --build -d     # 宿主机端口默认 8080
HOST_PORT=9090 docker compose up --build -d   # 自定义宿主机端口
curl http://localhost:8080/healthz
```

容器自带 `HEALTHCHECK`，Compose 亦配置了等价健康检查。

## 一次性验证服务 verify

`verify` 服务会等待 `app` 健康后，依次执行 **代码测试 → 构建校验 → API 冒烟**，
并以退出码报告结果：

```bash
docker compose run --build --rm verify
echo $?    # 0 表示全部通过
```

也可在宿主上直接跑：

```bash
python3 -m unittest discover -s tests -v   # 单元测试 + 对拍
python3 scripts/smoke.py http://127.0.0.1:8080
```

## API

### `GET /healthz`

```json
{"status": "ok"}
```

### `POST /api/solve`

请求体：

```json
{
  "damages": [
    {"width": 2, "height": 2, "phaseRange": {"lo": 0, "hi": 3}},
    {"width": 3, "height": 2, "phaseRange": {"lo": 0, "hi": 3}},
    {"width": 2, "height": 2, "phaseRange": {"lo": 0, "hi": 3}}
  ],
  "remnants": [
    {"width": 6, "height": 5, "period": 4, "origin": 0, "uses": 3},
    {"width": 5, "height": 4, "period": 4, "origin": 1, "uses": 1},
    {"width": 7, "height": 6, "period": 4, "origin": 2, "uses": 1},
    {"width": 4, "height": 3, "period": 4, "origin": 0, "uses": 1}
  ]
}
```

可行时返回（裁片位置、两侧相位逐处给出）：

```json
{
  "feasible": true,
  "distinctRemnantCount": 1,
  "usedRemnants": [0],
  "cutArea": 20,
  "occupiedRemnantArea": 30,
  "wasteArea": 10,
  "totalRemnantArea": 30,
  "placements": [
    {"damage": 0, "remnant": 0, "x": 0, "y": 0, "width": 2, "height": 2,
     "phaseLeft": 0, "phaseRight": 2}
  ]
}
```

不可行时返回**首条约束证据**（按破损阅读方向核验）：

```json
{
  "feasible": false,
  "evidence": {
    "code": "PHASE_MISMATCH",
    "damage": 1,
    "message": "破损1裁片右缘与破损2裁片左缘的水印相位……",
    "detail": {"seam": [0, 1], "rightPhases": [0], "leftPhases": [1]}
  }
}
```

证据代码：`OUT_OF_BOUNDS`（不越界）、`PHASE_RANGE_UNATTAINABLE`（相位范围
无法满足）、`PHASE_MISMATCH`（接缝不衔接）、`OVERLAP`（同料重叠）、
`USES_EXHAUSTED`（可用次数耗尽）、`NO_SOLUTION`（组合不可行）；
输入非法返回 HTTP 400 及 `INVALID_*` 证据。

## 测试

- `tests/test_solver.py`：输入校验、不越界/不重叠/次数/接缝相位/相位范围、
  三级优化目标、无解证据；
- `tests/test_bruteforce_property.py`：120 组随机小实例与全枚举暴力求解
  逐案对拍（含/不含相位范围两族），并含一个 5 破损 × 8 边料的规模压力测试。
