# syntax=docker/dockerfile:1.7
FROM python:3.12.11-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12.11-slim
RUN useradd --create-home --uid 10001 app
COPY --from=builder /install /usr/local
COPY --chmod=755 entrypoint.sh /entrypoint.sh
USER app
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
