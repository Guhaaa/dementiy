FROM node:22-bookworm-slim

ARG CODEX_VERSION=0.166.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @openai/codex@${CODEX_VERSION} \
    && npm cache clean --force

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    CODEX_HOME=/home/node/.codex

COPY maxim_bot.py maxim_style.py maxim_overrides.py maxim_proactive.py maxim_sessions.py ./

# Пользователь node (uid 1000) уже есть в базовом образе
RUN mkdir -p /home/node/.codex /app/data && chown node:node /home/node/.codex /app/data
USER node

CMD ["python3", "maxim_bot.py"]
