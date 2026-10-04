FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Run as a non-root user (uid 1000)
RUN useradd -m -u 1000 user && mkdir -p /home/user/app && chown user:user /home/user/app
USER user
ENV HOME=/home/user \
    PATH=/home/user/app/.venv/bin:/home/user/.local/bin:$PATH \
    UV_LINK_MODE=copy
WORKDIR /home/user/app

COPY --chown=user pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=user *.py ./
COPY --chown=user static ./static
# Mount point for the returns database (a volume in production)
RUN mkdir -p data

EXPOSE 7860
# Render sets PORT; default 7860 for local runs
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
