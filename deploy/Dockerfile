FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip cache purge

COPY app/ /app/app/
COPY prompts/ /app/prompts/
COPY run.py .

RUN useradd -r -s /usr/sbin/nologin agent
USER agent

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8787/healthz')"

ENTRYPOINT ["python", "run.py"]
