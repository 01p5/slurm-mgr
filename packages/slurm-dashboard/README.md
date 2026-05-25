# slurm-dashboard

The web UI. Two pieces:

- **Backend** (`src/slurm_dashboard/`) — stdlib `http.server`, no FastAPI dep. Routes are `/clusters/...` for cluster CRUD + every `s*` operation under each cluster.
- **Frontend** (`frontend/`) — React + Vite + TypeScript + Tailwind. Dark "security console" palette + Outfit/JetBrains Mono pair, lifted from Olympus's dashboard so the two feel like siblings.

## Run

```bash
# backend (:8770)
pip install -e ../slurmlib -e .
python -m slurm_dashboard.server

# frontend dev server (:5174, proxies to :8770)
cd frontend
npm install
npm run dev
```

`npm run build` writes the SPA into `../static/dist/`, which the backend serves at `/` when no API route matches.
