#!/bin/sh
set -eu
while :; do
  if [ ! -d "/etc/letsencrypt/live/${DOMAIN}" ]; then
    certbot certonly --webroot --webroot-path /var/www/certbot --non-interactive --agree-tos --email "$CERTBOT_EMAIL" -d "$DOMAIN" || true
  else
    certbot renew --webroot --webroot-path /var/www/certbot --quiet || true
  fi
  sleep 43200
done

