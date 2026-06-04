# Deploying ShelfSense (free)

ShelfSense is a Docker Compose stack. The **default `docker compose up` (replay path)** is light —
`api + postgres + frontend + replayer + prometheus + grafana`, **no GPU and no CV models** — so it
runs on a small, free host. The committed `data/events/behavior.jsonl` is replayed into the API, so
the dashboard populates in ~20 s with no extra setup.

> **Why the single-host option is simplest:** the React dashboard resolves the API at
> `http://<same-host>:8000` at runtime. So the least-friction deploy puts the API and dashboard on
> **one host** with ports **8080** (dashboard) and **8000** (API) open — **no code changes needed**.
> That's Option A, and what we recommend for a review demo.

---

## Option A — Free cloud VM (recommended: truly free, always-on, zero code changes)

**Oracle Cloud "Always Free"** gives an Arm VM (up to 4 OCPU / 24 GB RAM) **free indefinitely** — far
more than this stack needs. (AWS / GCP free tiers also work but expire after 12 months or are tiny.)

1. **Create the VM.** Sign up at <https://cloud.oracle.com> → *Compute → Instances → Create*. Pick an
   **Always-Free-eligible** shape (`VM.Standard.A1.Flex`, e.g. 2 OCPU / 12 GB), image **Ubuntu 22.04**.
   Save the SSH key.
2. **Open the ports.** In the instance's **VCN → Security List**, add ingress rules (source
   `0.0.0.0/0`) for **TCP 8080** and **8000** (optionally **3000** Grafana, **9090** Prometheus).
3. **SSH in and install Docker:**
   ```bash
   ssh -i your-key.key ubuntu@<VM_PUBLIC_IP>
   curl -fsSL https://get.docker.com | sudo sh
   sudo apt-get install -y docker-compose-plugin git
   ```
4. **Open the ports at the OS level too** — Oracle's Ubuntu images ship a restrictive iptables:
   ```bash
   sudo iptables -I INPUT -p tcp --dport 8080 -j ACCEPT
   sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT
   sudo netfilter-persistent save     # persist across reboots
   ```
5. **Clone and run:**
   ```bash
   git clone <your-repo-url> && cd ShelfSense
   sudo docker compose up -d --build      # default profile = fast replay, no models
   ```
   *(Optional: drop the POS CSV into `docs/raw/` for ST1008's POS KPIs — the demo works without it.)*
6. **Open** `http://<VM_PUBLIC_IP>:8080` — the live dashboard. API at `:8000/docs`, Grafana at `:3000`.

Update later with `git pull && sudo docker compose up -d --build`; stop with `sudo docker compose down`.

---

## Option B — Managed PaaS with an HTTPS URL (Render / Railway / Fly.io)

These give a tidy `https://…` URL but run each service **separately** (not `docker compose`), so you
wire the pieces by hand and make **one code change**: the dashboard's API base must become an env var
(today it assumes `<host>:8000`). On **Render**, for example:

1. **Postgres** — create a free Render PostgreSQL; note host / db / user / password.
2. **API** — *New → Web Service* from the repo, Dockerfile `services/api/Dockerfile`. Set
   `POSTGRES_HOST/PORT/DB/USER/PASSWORD` to the Render DB and `CORS_ALLOW_ORIGINS=*`. Seed the demo
   events by running the replayer once as a *Job*:
   `python scripts/ingest_events.py --api <api-url> --events data/events/behavior.jsonl`.
3. **Dashboard** — build the SPA (`npm run build` in `frontend/`) as a *Static Site*, pointing it at
   the API URL (set the API base at build time instead of `<host>:8000`).

> Free PaaS web services usually **sleep after ~15 min idle** (a ~30 s cold start on first hit) —
> fine for a review window, but Option A stays always-on.

**Quick alternative (no real deploy):** run `docker compose up` locally and expose it with a tunnel —
`cloudflared tunnel --url http://localhost:8080` (or `ngrok http 8080`) — for a temporary public URL.

---

## Notes

- **Data:** `data/events/behavior.jsonl` is committed and drives the replay demo. CCTV clips and the
  POS CSV live in `docs/raw/` (gitignored) and are only needed to *re-generate* events
  (`docker compose --profile detect up`), **not** for the hosted demo.
- **Resources:** the replay stack is comfortable on ~2 vCPU / 4 GB. Only the optional
  `--profile detect` (YOLO) wants more.
- **Security:** this is a demo (open ports; Grafana defaults to `admin`/`admin`). For anything beyond
  review, put it behind HTTPS + auth and tighten the security-list source ranges.
