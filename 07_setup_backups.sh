#!/usr/bin/env bash
# Native PostgreSQL + filestore backup installation. The backup runs as a
# dedicated systemd service and never writes credentials into the repository.
set -euo pipefail
umask 077

: "${ODOO_DB:=company_ai}"
: "${ODOO_DATA_DIR:=/var/lib/odoo}"
: "${BACKUP_DIR:=/var/backups/ai-box}"
: "${BACKUP_RETENTION_DAYS:=14}"
: "${BACKUP_GPG_RECIPIENT:=}"
: "${BACKUP_SERVICE:=ai-box-backup.service}"
: "${BACKUP_TIMER:=ai-box-backup.timer}"

[[ "${EUID}" -eq 0 ]] || { echo "Backup setup must run as root" >&2; exit 1; }
[[ "$ODOO_DB" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]] || { echo "Invalid ODOO_DB" >&2; exit 1; }
[[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ && "$BACKUP_RETENTION_DAYS" -ge 7 ]] || {
  echo "BACKUP_RETENTION_DAYS must be an integer >= 7" >&2; exit 1;
}
for command_name in pg_dump runuser sha256sum flock tar; do
  command -v "$command_name" >/dev/null || { echo "$command_name is required" >&2; exit 1; }
done
if [[ -n "$BACKUP_GPG_RECIPIENT" ]]; then
  command -v gpg >/dev/null || { echo "gpg is required when BACKUP_GPG_RECIPIENT is set" >&2; exit 1; }
fi

install -d -m 0700 "$BACKUP_DIR"
cat > /usr/local/sbin/ai-box-backup <<'BACKUP'
#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${ODOO_DB:?ODOO_DB is required}"
: "${ODOO_DATA_DIR:?ODOO_DATA_DIR is required}"
: "${BACKUP_DIR:?BACKUP_DIR is required}"
: "${BACKUP_RETENTION_DAYS:?BACKUP_RETENTION_DAYS is required}"
LOCK_FILE="${BACKUP_DIR}/.backup.lock"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d "${BACKUP_DIR}/.partial-${STAMP}.XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "another backup is already running" >&2; exit 1; }

runuser -u postgres -- pg_dump --format=custom --no-owner --file "$WORK/${ODOO_DB}.dump" "$ODOO_DB"
if [[ -d "${ODOO_DATA_DIR}/filestore/${ODOO_DB}" ]]; then
  tar --sort=name --mtime='1970-01-01' --numeric-owner \
    -C "${ODOO_DATA_DIR}/filestore" -czf "$WORK/${ODOO_DB}-filestore.tar.gz" "$ODOO_DB"
fi
sha256sum "$WORK"/* > "$WORK/SHA256SUMS"
if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
  for file in "$WORK"/${ODOO_DB}.dump "$WORK"/${ODOO_DB}-filestore.tar.gz; do
    [[ -f "$file" ]] || continue
    gpg --batch --yes --trust-model always --recipient "$BACKUP_GPG_RECIPIENT" --encrypt "$file"
    rm -f "$file"
  done
  rm -f "$WORK/SHA256SUMS"
  sha256sum "$WORK"/* > "$WORK/SHA256SUMS"
fi
FINAL="${BACKUP_DIR}/ai-box-${STAMP}"
mv "$WORK" "$FINAL"
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'ai-box-*' -mtime "+${BACKUP_RETENTION_DAYS}" -exec rm -rf {} +
ln -sfn "$FINAL" "${BACKUP_DIR}/latest"
echo "BACKUP_CREATED: $FINAL"
BACKUP
chmod 0750 /usr/local/sbin/ai-box-backup
chown root:root /usr/local/sbin/ai-box-backup

cat > /etc/ai-box/backup.env <<EOF
ODOO_DB=${ODOO_DB}
ODOO_DATA_DIR=${ODOO_DATA_DIR}
BACKUP_DIR=${BACKUP_DIR}
BACKUP_RETENTION_DAYS=${BACKUP_RETENTION_DAYS}
BACKUP_GPG_RECIPIENT=${BACKUP_GPG_RECIPIENT}
EOF
chmod 0600 /etc/ai-box/backup.env
cat > "/etc/systemd/system/${BACKUP_SERVICE}" <<EOF
[Unit]
Description=AI Box encrypted PostgreSQL and filestore backup
After=postgresql.service
[Service]
Type=oneshot
User=root
EnvironmentFile=/etc/ai-box/backup.env
ExecStart=/usr/local/sbin/ai-box-backup
PrivateTmp=true
EOF
cat > "/etc/systemd/system/${BACKUP_TIMER}" <<EOF
[Unit]
Description=Daily AI Box backup schedule
[Timer]
OnCalendar=*-*-* 02:30:00 UTC
Persistent=true
RandomizedDelaySec=900
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now "$BACKUP_TIMER"
/usr/local/sbin/ai-box-backup
[[ -L "${BACKUP_DIR}/latest" && -s "${BACKUP_DIR}/latest/SHA256SUMS" ]] || {
  echo "Initial backup verification failed" >&2; exit 1;
}
if [[ -z "$BACKUP_GPG_RECIPIENT" ]]; then
  echo "WARNING: backup is access-controlled but not encrypted at rest; set BACKUP_GPG_RECIPIENT before production sale" >&2
fi
echo "BACKUP_READY: $BACKUP_DIR; restore evidence is still required before production delivery."
