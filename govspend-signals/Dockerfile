FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -e ".[full,web]"

ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8000

EXPOSE 8000

CMD ["govspend", "web", "--host", "0.0.0.0", "--db", "/data/signals.db"]
