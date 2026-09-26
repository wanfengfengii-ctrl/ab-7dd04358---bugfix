FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /srv

# 纯标准库应用，无第三方依赖
COPY app/ ./app/
COPY web/ ./web/
COPY tests/ ./tests/
COPY scripts/ ./scripts/

# 构建期校验：全部源码可编译
RUN python -m compileall -q app scripts

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+__import__('os').environ.get('PORT','8080')+'/healthz', timeout=3).status==200 else 1)"

CMD ["python3", "app/server.py"]
