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
COPY seed.py .
COPY --from=panel /panel/dist panel/dist

# Demo data on first boot if the DB doesn't exist yet
ENV PORT=8000
CMD ["sh", "-c", "[ -f qr_api.db ] || python seed.py; uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
