#!/bin/bash
# DEVELOPMENT ONLY. Drops the company_ai database completely so you can
# re-run 02_install_modules.sh from a clean slate. This is destructive
# and asks for confirmation - never run this against a server with
# real client data.
set -e

echo "⚠️  This will PERMANENTLY DELETE the 'company_ai' database and"
echo "    everything in it (users, documents, memory, all data)."
read -p "Type 'yes' to confirm: " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Cancelled, nothing was deleted."
    exit 0
fi

su - postgres -c "psql -c \"DROP DATABASE IF EXISTS company_ai;\""
echo "Database dropped. Run ./02_install_modules.sh to reinstall from scratch."
