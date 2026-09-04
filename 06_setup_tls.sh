#!/usr/bin/env bash
# Native TLS provisioning for a real customer hostname. Docker is not used;
# nginx terminates TLS and certbot renews the certificate through systemd.
set -euo pipefail
umask 077

: "${DOMAIN:?Set DOMAIN to the customer fully-qualified HTTPS hostname}"
: "${EMAIL:?Set EMAIL to the certificate renewal contact}"
: "${NGINX_SITE:=/etc/nginx/sites-available/odoo}"
: "${CERTBOT_WEBROOT:=/var/www/certbot}"

[[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || { echo "Invalid DOMAIN" >&2; exit 1; }
[[ "$DOMAIN" != *..* ]] || { echo "Invalid DOMAIN" >&2; exit 1; }
[[ "$EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || { echo "Invalid EMAIL" >&2; exit 1; }
[[ "${EUID}" -eq 0 ]] || { echo "TLS setup must run as root" >&2; exit 1; }
command -v nginx >/dev/null || { echo "nginx is required; install it natively before TLS setup" >&2; exit 1; }
command -v certbot >/dev/null || { echo "certbot is required; install it natively before TLS setup" >&2; exit 1; }

install -d -m 0755 "$CERTBOT_WEBROOT/.well-known/acme-challenge"
cat > "$NGINX_SITE" <<NGINX
server {
    listen 80;
    server_name ${DOMAIN};
    location ^~ /.well-known/acme-challenge/ {
        root ${CERTBOT_WEBROOT};
    }
    location / {
        return 404;
    }
}
NGINX
ln -sfn "$NGINX_SITE" /etc/nginx/sites-enabled/odoo
nginx -t
systemctl enable --now nginx
systemctl reload nginx

certbot certonly --webroot --webroot-path "$CERTBOT_WEBROOT" \
  --non-interactive --agree-tos --keep-until-expiring \
  --email "$EMAIL" --domains "$DOMAIN"

CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
[[ -s "$CERT_DIR/fullchain.pem" && -s "$CERT_DIR/privkey.pem" ]] || {
  echo "Certificate files were not created" >&2; exit 1;
}
openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -checkend 86400 >/dev/null || {
  echo "Issued certificate is not valid for the next 24 hours" >&2; exit 1;
}
if systemctl list-unit-files certbot.timer >/dev/null 2>&1; then
  systemctl enable --now certbot.timer
else
  echo "certbot.timer is not installed; automatic renewal is not configured" >&2
  exit 1
fi

echo "TLS_CERTIFICATE_READY: ${DOMAIN}; renewal is delegated to certbot.timer."
echo "A browser/API regression check is still required after the frontend site is installed."
