# RailCall Discord support bot — stateless background worker (Render or any container host).
# Build context is this bot/ directory (see render.yaml: dockerContext ./bot).
FROM python:3.12-slim

# Pure-Python deps — no build toolchain needed.
RUN pip install --no-cache-dir "discord.py>=2.4,<3" "aiohttp>=3.9"

WORKDIR /app
COPY railcall_community_bot.py /app/railcall_community_bot.py

# Secrets are supplied ONLY via the environment — never baked into the image:
#   required:  DISCORD_BOT_TOKEN, GROQ_API_KEY
#   optional:  ESCALATE_MENTION, GROQ_MODELS, SUPPORT_CHANNELS, DENY_CHANNELS, WELCOME_CHANNEL
# PYTHONUNBUFFERED streams logs to the host immediately; the bot traps SIGTERM for clean redeploys.
ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "railcall_community_bot.py"]
