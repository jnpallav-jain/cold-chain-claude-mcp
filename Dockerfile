FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/app HF_HUB_CACHE=/models HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
    DEMO_MODE=true
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unixodbc libgomp1 \
    && curl -fsSLo /tmp/packages-microsoft-prod.deb https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb && rm /tmp/packages-microsoft-prod.deb \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements.lock.txt pyproject.toml ./
RUN python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.13.0 \
    && python -m pip install --no-cache-dir -r requirements.lock.txt
COPY src ./src
COPY scripts ./scripts
COPY .streamlit ./.streamlit
COPY data/sample ./data/sample
RUN python -m pip install --no-cache-dir --no-deps . \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /app/data/cache /app/data/control /models \
    && chown -R app:app /app/data /home/app
USER 10001:10001
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=3)"
ENTRYPOINT ["python", "-m", "scripts.launch_demo", "--bind", "0.0.0.0"]
