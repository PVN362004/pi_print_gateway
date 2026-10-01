#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
    echo "Run this installer with sudo."
    exit 1
fi

pi_gateway_source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pi_gateway_install_dir="/opt/pi-print-gateway"
pi_gateway_config_dir="/etc/pi-print-gateway"
pi_gateway_spool_dir="/var/lib/pi-print-gateway/jobs"

apt-get update
apt-get install -y cups cups-client python3 python3-venv python3-pip openssl

if ! id pi-print >/dev/null 2>&1; then
    useradd --system --user-group --home-dir "${pi_gateway_install_dir}" --shell /usr/sbin/nologin pi-print
fi

install -d -m 0755 "${pi_gateway_install_dir}" "${pi_gateway_config_dir}"
install -d -o pi-print -g pi-print -m 0750 "${pi_gateway_spool_dir}"
cp -R "${pi_gateway_source_dir}/pi_print_gateway" "${pi_gateway_install_dir}/"
cp "${pi_gateway_source_dir}/requirements.txt" "${pi_gateway_install_dir}/requirements.txt"

python3 -m venv "${pi_gateway_install_dir}/.venv"
"${pi_gateway_install_dir}/.venv/bin/pip" install --upgrade pip
"${pi_gateway_install_dir}/.venv/bin/pip" install -r "${pi_gateway_install_dir}/requirements.txt"

if [ ! -f "${pi_gateway_config_dir}/config.yml" ]; then
    pi_gateway_key="$(openssl rand -hex 32)"
    cp "${pi_gateway_source_dir}/config.example.yml" "${pi_gateway_config_dir}/config.yml"
    sed -i "s/CHANGE_THIS_TO_A_LONG_RANDOM_KEY/${pi_gateway_key}/" "${pi_gateway_config_dir}/config.yml"
    chmod 0640 "${pi_gateway_config_dir}/config.yml"
    chown root:pi-print "${pi_gateway_config_dir}/config.yml"
    echo "Generated API key: ${pi_gateway_key}"
    echo "Save this key in the Odoo gateway configuration."
fi

if getent group lp >/dev/null 2>&1; then
    usermod -a -G lp pi-print
fi
if getent group lpadmin >/dev/null 2>&1; then
    usermod -a -G lpadmin pi-print
fi

cp "${pi_gateway_source_dir}/systemd/pi-print-gateway.service" /etc/systemd/system/pi-print-gateway.service
systemctl daemon-reload
systemctl enable --now cups
systemctl enable pi-print-gateway
systemctl restart pi-print-gateway

echo "Installation complete."
echo "Edit ${pi_gateway_config_dir}/config.yml and set the real CUPS queues."
echo "Then run: sudo systemctl restart pi-print-gateway"
