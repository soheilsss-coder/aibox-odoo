# AIBOX all-in-one appliance image.
#
# One container runs the whole product: PostgreSQL (from the `pgserver` wheel),
# Redis (from the `redislite` wheel), Odoo 18, and nginx serving the built
# React frontend while proxying /api/* to Odoo. Deliberately no apt postgres
# and no apt redis: sandbox/aibox_local.sh already proved the wheel-based
# servers work, so the container reuses that exact path instead of inventing a
# second one.
#
# The platform only has to expose ONE port (it arrives as $PORT); nginx owns it.
#
# NOTE ON WHAT IS AND IS NOT VERIFIED
#   The install/seed/start logic below is delegated to sandbox/aibox_local.sh,
#   which was exercised end to end (124 modules installed, demo data seeded,
#   /api/login + /api/chat answering). The container packaging itself could not
#   be built in the workspace that produced it - no Docker daemon was available
#   there - so treat the first platform build as the real test.

FROM python:3.12-bookworm

# build-essential/gcc/make are needed to compile pg_trgm and unaccent against
# the pgserver wheel's own pgxs (the wheel ships no contrib modules, and Odoo
# 18 refuses to install without pg_trgm).
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates xz-utils \
        build-essential gcc make \
        libxml2-dev libxslt1-dev zlib1g-dev libjpeg-dev \
        libsasl2-dev libldap2-dev libpq-dev \
        nginx \
    && rm -rf /var/lib/apt/lists/*

# Node 22 to build the frontend at image time (matches the version the
# workspace used: v22.22.3).
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# AIBOX_WS holds the venv, sources and logs; it is baked into the image so a
# volume mount cannot shadow it. Only the database directory is pointed at
# /data, which is the one thing worth persisting - mount a volume there and a
# restart comes back in seconds instead of re-installing 124 modules.
# (The variable is AIBOX_WS, not AIBOX_WORKSPACE; see sandbox/aibox_local.sh.)
ENV AIBOX_WS=/opt/aibox-ws \
    AIBOX_PGDATA=/data/pgdata \
    AIBOX_REPO=/opt/aibox \
    AIBOX_ODOO_PORT=18069 \
    PYTHONWARNINGS=ignore \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/aibox
COPY . /opt/aibox

# Odoo and the LLM addon suite are separate upstreams; pin the branches the
# installer already uses so the image matches a validated combination.
ARG ODOO_REPO=https://github.com/odoo/odoo.git
ARG ODOO_BRANCH=18.0
ARG ODOO_LLM_REPO=https://github.com/apexive/odoo-llm.git
ARG ODOO_LLM_BRANCH=18.0

# Cloned into the image (not under /data) so a volume mounted at /data cannot
# shadow them. cmd_install skips the clone when the directory already exists.
RUN mkdir -p /opt/aibox-ws/src /data \
    && git clone --depth 1 --branch "$ODOO_BRANCH" "$ODOO_REPO" /opt/aibox-ws/src/odoo \
    && git clone --depth 1 --branch "$ODOO_LLM_BRANCH" "$ODOO_LLM_REPO" /opt/aibox-ws/src/odoo-llm \
    && cd /opt/aibox/frontend && npm ci --no-audit --no-fund \
    && npm run build \
    && rm -rf /opt/aibox/frontend/node_modules

# Ports: nginx is the only listener the platform needs to know about. Render and
# Railway both inject $PORT; the entrypoint writes it into the nginx config.
EXPOSE 8080
ENV PORT=8080

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/nginx.conf.template /etc/nginx/nginx.conf.template
RUN chmod +x /usr/local/bin/entrypoint.sh

# Health: nginx answers from the first second, even while Odoo is still
# installing modules, so the platform does not kill a slow first boot.
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
