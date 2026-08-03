#!/bin/sh
set -eu
mkdir -p /etc/nginx/fallback /etc/nginx/tls
if [ ! -f /etc/nginx/fallback/fullchain.pem ]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 2 -subj "/CN=${DOMAIN}" -keyout /etc/nginx/fallback/privkey.pem -out /etc/nginx/fallback/fullchain.pem >/dev/null 2>&1
fi
render_tls() {
  cert_dir="/etc/letsencrypt/live/${DOMAIN}"
  if [ -f "${cert_dir}/fullchain.pem" ]; then use_dir="$cert_dir"; else use_dir="/etc/nginx/fallback"; fi
  printf 'ssl_certificate %s/fullchain.pem;\nssl_certificate_key %s/privkey.pem;\n' "$use_dir" "$use_dir" > /etc/nginx/tls/certificate.conf
  envsubst '${DOMAIN}' < /etc/nginx/templates/direct.conf.template > /etc/nginx/conf.d/default.conf
}
render_tls
(while sleep 300; do render_tls; nginx -s reload || true; done) &
exec nginx -g 'daemon off;'

