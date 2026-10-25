# Hugging Face Spaces variant of the AIBOX appliance.
#
# ? WHY A SEPARATE FILE: a Space's repo only carries its own files, not the
#   app source. This Dockerfile is identical to the root ../Dockerfile except
#   it CLONES the public GitHub repo at build time, and listens on 7860 -
#   the single public port Hugging Face serves for every Space.
#
# ? USER'S SPACE REPO NEEDS ONLY:
#     1. this file, saved as "Dockerfile" (exact name, no extension)
#     2. the auto-generated README.md that Hugging Face creates for the Space
#   Nothing else - no git, no terminal, no upload.
#
# Result: the full real platform (Odoo + FastAPI gateway + the Nova UI,
# built inside the image) on https://<owner>-<space>.hf.space, card-free
# and permanently free on HF's CPU Basic tier.

FROM python:3.12-bookworm

ARG AIBOX_REPO_URL=https://github.com/soheilsss-coder/aibox-odoo.git
ARG AIBOX_BRANCH=arena/01a0a69b-aibox-odoo

# build-essential/gcc/make compile pg_trgm and unaccent against the pgserver
# wheel's own pgxs; Odoo refuses to install without pg_trgm.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates xz-utils \
        build-essential gcc make \
        libxml2-dev libxslt1-dev zlib1g-dev libjpeg-dev \
        libsasl2-dev libldap2-dev libpq-dev \
        nginx \
    && rm -rf /var/lib/apt/lists/*

# Node 22 to build the frontend at image time.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

ENV AIBOX_WS=/opt/aibox-ws \
    AIBOX_PGDATA=/data/pgdata \
    AIBOX_REPO=/opt/aibox \
    AIBOX_ODOO_PORT=18069 \
    PYTHONWARNINGS=ignore \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/aibox
RUN git clone --depth 1 --branch "$AIBOX_BRANCH" "$AIBOX_REPO_URL" /opt/aibox

# Odoo and the LLM addon suite are separate upstreams; pin the same validated
# branches the root Dockerfile uses.
ARG ODOO_REPO=https://github.com/odoo/odoo.git
ARG ODOO_BRANCH=18.0
ARG ODOO_LLM_REPO=https://github.com/apexive/odoo-llm.git
ARG ODOO_LLM_BRANCH=18.0

RUN mkdir -p /opt/aibox-ws/src /data \
    && git clone --depth 1 --branch "$ODOO_BRANCH" "$ODOO_REPO" /opt/aibox-ws/src/odoo \
    && git clone --depth 1 --branch "$ODOO_LLM_BRANCH" "$ODOO_LLM_REPO" /opt/aibox-ws/src/odoo-llm \
    && cd /opt/aibox/frontend && npm ci --no-audit --no-fund \
    && npm run build \
    && rm -rf /opt/aibox/frontend/node_modules

# Hugging Face exposes EXACTLY port 7860 publicly for Docker Spaces.
EXPOSE 7860
ENV PORT=7860

# NOTE: a Space's build context contains only the user's two files - take the
# entrypoint and nginx template from the freshly cloned repo, not from COPY.
RUN cp /opt/aibox/docker/entrypoint.sh /usr/local/bin/entrypoint.sh \
    && cp /opt/aibox/docker/nginx.conf.template /etc/nginx/nginx.conf.template \
    && chmod +x /usr/local/bin/entrypoint.sh

# nginx serves /healthz from the first second, even while module install is
# still running, so the platform does not kill a slow first boot.
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
