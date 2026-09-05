#!/bin/bash
# =============================================================================
# Builds the React frontend into real static HTML/CSS/JS files and serves
# them - this is the missing piece between "I have frontend source code"
# and "I have a website a person can open in a browser".
#
# Two modes:
#
#   A) QUICK LOOK RIGHT NOW (no domain, no nginx, just see it work):
#        ./17_setup_frontend.sh --dev
#      Starts Vite's own dev server on http://127.0.0.1:5173, already
#      configured (frontend/vite.config.js) to proxy /api/* to Odoo on
#      127.0.0.1:8069. Open that URL in a browser on THIS machine, or
#      SSH-tunnel port 5173 to your own laptop:
#        ssh -L 5173:127.0.0.1:5173 you@your-server
#      then open http://127.0.0.1:5173 in YOUR OWN browser.
#
#   B) REAL DELIVERY (production build, served by nginx, one real URL):
#        DOMAIN=app.yourbrand.example ./17_setup_frontend.sh
#      Builds static files (npm run build) and adds an nginx server
#      block that serves them at https://DOMAIN/ while still proxying
#      /api/* and /telegram/* to Odoo on the SAME domain - so the
#      frontend's default same-origin API calls (vite.config.js's
#      comment explains this) just work with no extra configuration.
#      Run 06_setup_tls.sh for this DOMAIN first if you haven't -
#      this script edits the same nginx site file TLS created.
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="${SCRIPT_DIR}/frontend"

if [ "$1" = "--dev" ]; then
  echo "=== Quick-look mode: Vite dev server ==="
  cd "$FRONTEND_DIR"
  if [ ! -d node_modules ]; then
    echo "Installing frontend dependencies (first run only, ~15s)..."
    npm install --no-audit --no-fund
  fi
  echo ""
  echo "Starting dev server on http://0.0.0.0:5173 ..."
  echo "(Ctrl+C to stop. In a managed preview, use the assigned preview URL."
  echo " For a remote server, SSH-tunnel port 5173 if needed:"
  echo " ssh -L 5173:127.0.0.1:5173 you@this-server, then open"
  echo " http://127.0.0.1:5173 in the browser on YOUR OWN computer.)"
  echo ""
  npm run dev -- --host 0.0.0.0
  exit 0
fi

if [ -z "$DOMAIN" ]; then
  echo "Usage:"
  echo "  ./17_setup_frontend.sh --dev              (quick look, no domain needed)"
  echo "  DOMAIN=app.yourbrand.example ./17_setup_frontend.sh   (real production build)"
  exit 1
fi

echo "=== [1/3] Building the frontend (npm install + npm run build) ==="
cd "$FRONTEND_DIR"
npm install --no-audit --no-fund
npm run build
echo "Build output: ${FRONTEND_DIR}/dist"

DEPLOY_DIR="/var/www/${DOMAIN}"
echo ""
echo "=== [2/3] Copying built files to ${DEPLOY_DIR} ==="
mkdir -p "$DEPLOY_DIR"
rm -rf "${DEPLOY_DIR:?}"/*
cp -r dist/* "$DEPLOY_DIR"/

echo ""
echo "=== [3/3] Rewriting the nginx site for ${DOMAIN} ==="
echo "    (regenerates the FULL site file, using certbot's standard cert"
echo "    paths - safer than trying to patch the existing file blindly,"
echo "    since it can't accidentally leave two conflicting 'location /'"
echo "    blocks, which nginx would refuse to load at all)"
NGINX_SITE="/etc/nginx/sites-available/odoo"
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
if [ ! -d "$CERT_DIR" ]; then
  echo "ERROR: ${CERT_DIR} not found - run 06_setup_tls.sh with this same"
  echo "DOMAIN first (it must succeed and issue a real certificate),"
  echo "THEN run this script."
  exit 1
fi

cat > "$NGINX_SITE" << NGINXEOF
server {
    listen 80;
    server_name ${DOMAIN};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name ${DOMAIN};

    ssl_certificate ${CERT_DIR}/fullchain.pem;
    ssl_certificate_key ${CERT_DIR}/privkey.pem;

    # --- Odoo's OWN backend (admin/technical work: Settings, Role
    # Templates Summary, AI Approvals, Documents backend, etc.) - kept
    # reachable under /odoo/ for whoever needs the raw Odoo UI, most
    # end users never need this path.
    location /odoo/ {
        rewrite ^/odoo/(.*)\$ /\$1 break;
        proxy_pass http://127.0.0.1:8069;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 720s;
    }
    location /web/ {
        proxy_pass http://127.0.0.1:8069;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 720s;
    }

    # --- This product's own API surface (roadmap #43-44 semantic
    # layer + admin console + telegram webhook) - what the React
    # frontend and the Telegram bridge actually call.
    location /api/ {
        proxy_pass http://127.0.0.1:8069;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 720s;
    }
    location /telegram/ {
        proxy_pass http://127.0.0.1:8069;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    location /longpolling/ {
        proxy_pass http://127.0.0.1:8072;
        proxy_set_header Host \$host;
        proxy_read_timeout 3600s;
    }

    # --- The actual product: the React frontend, static files, with
    # SPA fallback so client-side routing (react-router) works on a
    # hard refresh of any page, not just "/".
    root ${DEPLOY_DIR};
    index index.html;
    location / {
        try_files \$uri /index.html;
    }
}
NGINXEOF

nginx -t
systemctl reload nginx

echo ""
echo "=== Done ==="
echo "https://${DOMAIN} now serves the actual product frontend."
echo "https://${DOMAIN}/api/... and /telegram/... still go to Odoo, unchanged."
echo ""
echo "To update after a code change: re-run this same command - it"
echo "rebuilds and re-copies dist/, nginx config is only touched once."
