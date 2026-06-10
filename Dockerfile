FROM docker.io/tonychi/carla:0.9.16 AS carla-runtime

FROM sys511613/pcla@sha256:698fb44c2b9b3a142304f37761a8c1c05dd7cf0a2983736657980c577e72326d

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libfontconfig1 \
    libgl1 \
    libglib2.0-0 \
    libjpeg8 \
    libpng16-16 \
    libsm6 \
    libtiff5 \
    libvulkan1 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=carla-runtime /opt/carla /opt/carla
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
ENV UV_PROJECT_ENVIRONMENT=/opt/conda/envs/PCLA
RUN uv sync --locked --no-dev --inexact

COPY PCLA-wrapper/PCLA/dist/carla-0.9.16-cp38-cp38-linux_x86_64.whl /tmp/
RUN uv pip install --python /opt/conda/envs/PCLA/bin/python \
    /tmp/carla-0.9.16-cp38-cp38-linux_x86_64.whl \
    && rm /tmp/carla-0.9.16-cp38-cp38-linux_x86_64.whl

COPY . /app
RUN test -f /app/PCLA-wrapper/PCLA/PCLA.py \
    && chmod +x /app/entrypoint.sh /app/carla_server.sh

ENV PORT=50051
ENV CARLA_HOST=localhost
ENV CARLA_PORT=2000
ENV CARLA_TIMEOUT=120
ENV CARLA_TM_PORT=8000

ENTRYPOINT ["/app/entrypoint.sh"]
