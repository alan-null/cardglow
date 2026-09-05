FROM python:3.12-slim AS base

LABEL org.opencontainers.image.title="cardglow"
LABEL org.opencontainers.image.description="Turn any logo (PNG/GIF/SVG) into a GitHub-OG-card-style social preview image"
LABEL org.opencontainers.image.source="https://github.com/alan-null/cardglow"
LABEL org.opencontainers.image.licenses="MIT"

# System libs required by cairosvg (SVG rasterization). Pillow/numpy need nothing extra.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

FROM base AS runtime-base

RUN pip install --no-cache-dir pillow cairosvg numpy

# Run as non-root
RUN useradd -m -u 1000 cardglow
COPY cardglow.py /usr/local/bin/cardglow
RUN chmod +x /usr/local/bin/cardglow

USER cardglow
WORKDIR /data

ENTRYPOINT ["python3", "/usr/local/bin/cardglow"]
CMD ["--help"]

# Development-only image target. The default/final runtime target does not
# include pytest.
FROM runtime-base AS test

USER root
RUN pip install --no-cache-dir pytest

USER cardglow

# Keep the published default image limited to runtime dependencies.
FROM runtime-base AS runtime
