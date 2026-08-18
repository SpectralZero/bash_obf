FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --no-install-recommends --yes bash \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin obfush

WORKDIR /opt/obfush
COPY . .
RUN python -m pip install --no-cache-dir ".[gui]" \
    && chown -R obfush:obfush /opt/obfush

USER obfush
ENTRYPOINT ["obfush"]
CMD ["--help"]
