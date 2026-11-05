# syntax=docker/dockerfile:1.7
# Insight by 50N Systems. Proprietary; see LICENSE.

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
RUN python -m venv /opt/insight
COPY pyproject.toml README.md LICENSE ./
COPY insight ./insight
# An optional build secret supplies an extra CA bundle for build networks behind a TLS proxy.
# It is used only in this stage and never reaches the shipped image.
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    /opt/insight/bin/pip install .

FROM python:3.12-slim
ARG VERSION=0.1.0
LABEL org.opencontainers.image.title="Insight" \
      org.opencontainers.image.vendor="50N Systems" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="LicenseRef-50N-Proprietary" \
      org.opencontainers.image.description="On-board monitoring and diagnostics for yacht IT. Proprietary software of 50N Systems; copying prohibited."

# libcap2-bin provides setcap so the non-root process can bind 443/514 and send ICMP.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libcap2-bin \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 insight \
 && useradd --system --uid 10001 --gid insight --home-dir /data --shell /usr/sbin/nologin insight \
 && mkdir -p /data && chown insight:insight /data

COPY --from=build /opt/insight /opt/insight
RUN setcap cap_net_bind_service,cap_net_raw+ep "$(readlink -f /usr/local/bin/python3.12)"

ENV PATH="/opt/insight/bin:${PATH}" \
    INSIGHT_DATA_DIR=/data \
    PYTHONUNBUFFERED=1
USER insight
VOLUME ["/data"]
EXPOSE 443/tcp 80/tcp 514/udp

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD ["insight", "healthcheck"]

ENTRYPOINT ["insight"]
CMD ["serve"]
