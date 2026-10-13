FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    gnucobol gcc make python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY Makefile ./
COPY src/ src/
COPY native/ native/
COPY copybooks/ copybooks/
RUN make all

FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcob4 python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 meridian \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app meridian \
    && mkdir -p /app/build /data \
    && chown meridian:meridian /data \
    && chmod 0700 /data
WORKDIR /app
COPY --from=builder /src/build/meridian build/meridian
COPY tools/ tools/
COPY web/ web/
USER 10001:10001
ENV MERIDIAN_DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import os,urllib.request; r=urllib.request.Request('http://127.0.0.1:8080/ready',headers={'Authorization':'Bearer '+os.environ.get('MERIDIAN_API_TOKEN','')}); urllib.request.urlopen(r,timeout=4).read()"
CMD ["python3", "tools/server.py", "--host", "0.0.0.0", "--port", "8080"]
