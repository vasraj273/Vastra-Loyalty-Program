# Build the React panel, then run the API which serves everything:
#   /            -> API (docs at /docs)
#   /panel       -> manufacturer admin panel
#   /web/generate, /web/scan -> webview pages for Vastra / YourApp

FROM node:22-slim AS panel
WORKDIR /panel
COPY panel/package.json panel/package-lock.json ./
RUN npm ci
COPY panel/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY seed.py bootstrap_admin.py ./
COPY --from=panel /panel/dist panel/dist

# AWS Lambda Web Adapter. FastAPI speaks ASGI and Lambda invokes a handler, so
# without this the image cannot run on Lambda at all. The adapter runs as a
# Lambda extension and proxies each invocation to uvicorn on $PORT over plain
# HTTP, which leaves this image byte-identical in behaviour everywhere else --
# it still runs the same way locally, on Render, or on ECS.
#
# response_stream raises the Lambda response cap from 6 MB (buffered) to 20 MB;
# a 2,000-sticker print PDF is 10.3 MB, so the buffered cap is not enough. The
# Function URL must also be created with invoke mode RESPONSE_STREAM to match.
# Pinned, not :latest, so a rebuild cannot silently change the adapter.
# See docs/integration/AWS_LAMBDA_DEPLOY.md.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 \
     /lambda-adapter /opt/extensions/lambda-adapter
ENV AWS_LWA_INVOKE_MODE=response_stream

# The app creates tables on startup if missing (CREATE TABLE IF NOT EXISTS)
# but never seeds automatically, so MySQL data persists across deploys.
# A fresh database therefore has no accounts: create the first one with
#   python bootstrap_admin.py --admin-user admin      (non-destructive)
# `seed.py` is destructive and for scratch/demo databases only.
# See docs/integration/MYSQL_SETUP.md and docs/integration/AWS_LAMBDA_DEPLOY.md.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
