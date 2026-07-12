# Babanuj ops extractors → Command Center Postgres.
#
# Minimal image to run the Python extractors (currently shopify-sync.py) as a
# one-shot container ON the bcc-prod-net network, so it can reach the INTERNAL
# `db` service (the prod Postgres publishes no host port).
#
#   docker build -t babanuj-ops:latest .
#   docker run --rm --network bcc-prod-net \
#     -e DATABASE_URL=postgres://bcc:<PW>@db:5432/bcc \
#     -v /opt/babanuj-ops/secrets/shopify.env:/root/.config/shopify-pp-cli/.env:ro \
#     babanuj-ops:latest shopify-sync.py --days 35 --verbose
#
# Secrets are NEVER baked into the image — creds are mounted at runtime, the
# DATABASE_URL is passed as an env var. Only stdlib + psycopg2 are needed for
# the Shopify path.
FROM python:3.12-slim
RUN pip install --no-cache-dir psycopg2-binary
WORKDIR /app
COPY lib ./lib
COPY shopify-sync.py ./
ENTRYPOINT ["python"]
