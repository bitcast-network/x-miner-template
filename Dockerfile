# syntax=docker/dockerfile:1.7
FROM python:3.12.11-slim AS builder

RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12.11-slim
RUN useradd --create-home --uid 10001 miner \
    && mkdir -p /var/lib/bitcast-x /var/lib/bitcast-wallets /home/miner/.bittensor/wallets \
    && chown -R miner:miner /var/lib/bitcast-x /var/lib/bitcast-wallets /home/miner
COPY --from=builder /install /usr/local
COPY --chmod=755 entrypoint.sh /entrypoint.sh
USER miner
EXPOSE 8095
VOLUME ["/var/lib/bitcast-x", "/var/lib/bitcast-wallets", "/home/miner/.bittensor/wallets"]
ENTRYPOINT ["/entrypoint.sh"]
