# slurm-dashboard image.
#
# Two-stage build mirroring Olympus's Dockerfile:
#   1. frontend-build (node:20-alpine) — vite builds the SPA. We pass
#      VITE_BASE_PATH=/slurm/ so the bundle's asset URLs include the
#      Olympus reverse-proxy prefix. For standalone (no Olympus) builds,
#      override --build-arg VITE_BASE_PATH=/.
#   2. python:3.12-slim — installs slurmlib + slurm-mcp + slurm-dashboard,
#      copies the SPA into packages/slurm-dashboard/static/dist, exposes :8770.
#
# Build (standalone):
#   docker build -t slurm-dashboard:dev --build-arg VITE_BASE_PATH=/ .
#
# Build (under Olympus reverse proxy at /slurm/*):
#   docker build -t slurm-dashboard:dev .

ARG VITE_BASE_PATH=/slurm/

# ---------- stage 1: frontend ----------
FROM node:20-alpine AS frontend-build
ARG VITE_BASE_PATH
ENV VITE_BASE_PATH=${VITE_BASE_PATH}
WORKDIR /build
COPY packages/slurm-dashboard/frontend/package.json packages/slurm-dashboard/frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --silent; else npm install --silent; fi
COPY packages/slurm-dashboard/frontend/ ./
RUN npm run build
# Vite's outDir is ../static/dist (relative to the frontend cwd) →
# resolves to /static/dist in this layer. Re-copy to a known path.
RUN mkdir -p /spa && cp -r /static/dist/. /spa/

# ---------- stage 2: backend ----------
FROM python:3.12-slim
WORKDIR /opt/slurm-mgr

# OpenSSH client is needed at runtime for SSHRunner; paramiko handles
# its own SSH but jump-host config paths can shell out. Cheap to include.
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Source — copy after deps so layer cache survives most edits.
COPY packages packages

# Editable installs of all three sibling packages. paramiko comes in
# transitively as slurmlib's dep.
RUN pip install --no-cache-dir --no-deps -e ./packages/slurmlib \
 && pip install --no-cache-dir --no-deps -e ./packages/slurm-mcp \
 && pip install --no-cache-dir --no-deps -e ./packages/slurm-dashboard \
 && pip install --no-cache-dir 'paramiko>=3.4,<4'

# Drop the built SPA bundle in place. The Python server's
# DEFAULT_STATIC_DIR resolves to packages/slurm-dashboard/static/dist.
COPY --from=frontend-build /spa /opt/slurm-mgr/packages/slurm-dashboard/static/dist

ENV PYTHONUNBUFFERED=1
EXPOSE 8770
CMD ["slurm-dashboard", "--host=0.0.0.0", "--port=8770"]
