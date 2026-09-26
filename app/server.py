"""HTTP 服务：静态前端 + /api/solve 配片接口 + /healthz 健康检查。

仅依赖 Python 标准库，便于极简容器镜像与离线验证。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from solver import ValidationError, solve  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "RestorationServer/1.0"

    def log_message(self, fmt, *args):  # 统一走 logging
        logging.info("%s - %s", self.address_string(), fmt % args)

    # ---------------- 响应工具 ---------------- #

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, rel: str) -> None:
        # 防路径穿越
        target = (WEB_DIR / rel).resolve()
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type",
                         CONTENT_TYPES.get(target.suffix,
                                           "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---------------- 路由 ---------------- #

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/healthz", "/health", "/api/health"):
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/" or path == "":
            self._send_static("index.html")
            return
        if path.startswith("/api/"):
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
            return
        self._send_static(path.lstrip("/"))

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/solve":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 1_000_000:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"feasible": False,
                             "evidence": {"code": "INVALID_REQUEST",
                                          "message": "请求体为空或超过 1MB"}})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"feasible": False,
                             "evidence": {"code": "INVALID_JSON",
                                          "message": f"JSON 解析失败: {exc}"}})
            return
        try:
            result = solve(payload)
        except ValidationError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"feasible": False,
                             "evidence": exc.evidence.as_dict()})
            return
        except Exception as exc:  # 防御：求解器内部错误不拖垮服务
            logging.exception("solver failure")
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR,
                            {"feasible": False,
                             "evidence": {"code": "INTERNAL_ERROR",
                                          "message": str(exc)}})
            return
        self._send_json(HTTPStatus.OK, result)


def create_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    httpd = create_server(host, port)
    logging.info("古籍修复配片服务监听 %s:%s (web: %s)", host, port, WEB_DIR)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
