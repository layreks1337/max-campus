#!/usr/bin/env bash
# Скачивает корневые сертификаты Минцифры и собирает бандл.
#
# Без них TLS-соединение до platform-api2.max.ru не поднимается:
# curl отдаёт SEC_E_UNTRUSTED_ROOT, Python — CERTIFICATE_VERIFY_FAILED.
#
# Тонкость: файлы приходят БЕЗ завершающего перевода строки, поэтому простой
# `cat a.pem b.pem > bundle.pem` склеивает "-----END-----BEGIN-----" в одну
# строку и бандл становится нечитаемым ([X509] PEM lib). Отсюда awk ниже.

set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p certs

ROOT_URL="https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer"
SUB_URL="https://gu-st.ru/content/Other/doc/russian_trusted_sub_ca.cer"

# -k нужен на первом шаге: сам gu-st.ru обслуживается тем же корнем,
# которого у нас ещё нет. Цепочка проверяется дальше, при обращении к API.
echo "Скачиваю корневой сертификат..."
curl -fsSLk -o certs/russian_trusted_root_ca.pem "$ROOT_URL"
echo "Скачиваю промежуточный..."
curl -fsSLk -o certs/russian_trusted_sub_ca.pem "$SUB_URL"

echo "Собираю бандл..."
awk 'FNR==1 && NR!=1 { print "" } { sub(/\r$/, ""); print }' \
    certs/russian_trusted_root_ca.pem \
    certs/russian_trusted_sub_ca.pem \
    > certs/russian_trusted_bundle.pem

COUNT=$(grep -c "BEGIN CERTIFICATE" certs/russian_trusted_bundle.pem)
echo "Сертификатов в бандле: $COUNT"
[ "$COUNT" -ge 2 ] || { echo "ОШИБКА: ожидалось минимум 2"; exit 1; }

if command -v openssl >/dev/null 2>&1; then
  openssl x509 -in certs/russian_trusted_bundle.pem -noout -subject >/dev/null \
    && echo "Бандл читается openssl: ок"
fi

echo "Проверяю соединение с MAX API..."
if curl -fsS -m 20 --cacert certs/russian_trusted_bundle.pem \
     "https://platform-api2.max.ru/me" -o /dev/null \
     -H "Authorization: ${MAX_BOT_TOKEN:-нет-токена}" 2>/dev/null; then
  echo "TLS до platform-api2.max.ru: ок"
else
  echo "TLS-проверка не прошла — возможно, не задан MAX_BOT_TOKEN (это нормально)."
  curl -sS -m 20 --cacert certs/russian_trusted_bundle.pem \
    "https://platform-api2.max.ru/me" -o /dev/null -w "  код ответа: %{http_code}\n" || true
fi

echo "Готово."
