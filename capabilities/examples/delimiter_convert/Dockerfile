# Artifact contract (see AGENTS.md):
#   * /work is the writable working directory and must be owned by 65534
#     before the anonymous volume is initialised from the image;
#   * the process runs as uid 65534 with no capabilities and no network;
#   * inputs arrive in /work, outputs are whatever the run leaves there.
FROM python:3.13-slim

RUN mkdir -p /work && chown 65534:65534 /work
COPY main.py /app/main.py

USER 65534:65534
WORKDIR /work
ENTRYPOINT []
CMD ["python", "/app/main.py"]
