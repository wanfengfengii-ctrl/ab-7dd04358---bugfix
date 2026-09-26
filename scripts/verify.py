#!/usr/bin/env python3
"""verify 一次性服务入口：代码测试 → 构建校验 → API 冒烟。

任一步失败立即以非零退出码结束，供 `docker compose run --rm verify`
（或 compose 中的 verify 服务）报告整体验证结果。
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(title: str, cmd: list) -> None:
    print(f"\n===== {title} =====")
    print("$ " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"❌ {title}失败（退出码 {result.returncode}）", flush=True)
        sys.exit(result.returncode)
    print(f"✅ {title}通过", flush=True)


def main() -> None:
    # 1. 代码测试（单元测试 + 对拍性质测试）
    run("代码测试",
        [sys.executable, "-m", "unittest", "discover",
         "-s", "tests", "-v"])

    # 2. 构建校验：全部源码可编译
    run("构建校验（compileall）",
        [sys.executable, "-m", "compileall", "-q", "app", "scripts"])

    # 3. API 冒烟（对运行中的 app 服务）
    url = os.environ.get("APP_URL", "http://127.0.0.1:8080")
    run("API 冒烟",
        [sys.executable, os.path.join("scripts", "smoke.py"), url])

    print("\n🎉 verify：测试、构建、冒烟全部通过", flush=True)


if __name__ == "__main__":
    main()
