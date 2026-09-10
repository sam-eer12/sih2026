# Deployment — AVR-25D on a free cloud VM

**Audience:** whoever is putting the submission link up. Assumes you have the repo
running locally already.

This deploys the whole stack — Next.js app, FastAPI pipeline server, TLS — as three
Docker containers on one virtual machine, for **₹0**. MongoDB Atlas (M0) and Firebase
Auth (Spark) stay as managed free services.

> **Read §2 before choosing a provider.** This project streams 1.9 MB per frame. That
> single number eliminates most free tiers, and it is not obvious until the demo stalls.

---

## 1. What gets deployed

```
                        Internet
                           │
                    :80 ┌──┴──┐ :443
                        │ TLS │  Let's Encrypt, auto-renewed
  ┌─────────────────────┴─────┴──────────────────────────────┐
  │  VM (Oracle Ampere A1 · 4 OCPU · 24 GB · Always Free)     │
  │                                                           │
  │   ┌─────────┐   /stream    ┌──────────────────────────┐   │
  │   │  caddy  │─────────────►│ backend  : FastAPI :8000 │   │
  │   │         │              │  --replay demo.log       │   │
  │   │         │   /*         └──────────────────────────┘   │
  │   │         │─────────────►┌──────────────────────────┐   │
  │   └─────────┘              │ frontend : Next.js :3000 │   │
  │                            └──────────────────────────┘   │
  └───────────────────────────────┬───────────────────┬───────┘
                                  │                   │
                        MongoDB Atlas M0      Firebase Auth
                         (free forever)        (Spark, free)
```

| File | Purpose |
|---|---|
| `deploy/docker-compose.yml` | The three services and how they wire together |
| `deploy/Dockerfile.backend` | Python 3.13-slim + `backend/requirements.txt` + `model/` |
| `deploy/Dockerfile.frontend` | Node 22 → `next build` → standalone runtime |
| `deploy/Caddyfile` | TLS termination and the `/stream` split |
| `deploy/.env.example` | Every variable, documented. Copy to `deploy/.env` |

### FR-41 is not violated by this

FR-41 says *"the browser shall connect directly to the FastAPI WebSocket; Next.js shall
not proxy, buffer or re-serialise frame data."*

Caddy is not Next.js. `/stream` is split at the edge and routed straight to the backend
container — no Node process, no route handler, no re-serialisation in the frame path.
T-W6's assertion still holds, and §8 gives you the command to prove it on the deployed
host. If you are asked about this by a judge, that is the answer: the requirement
forbids a Next.js hop, not a TLS terminator.

---

## 2. The two constraints that decide everything

### 2.1 An HTTPS page cannot open `ws://` — NFR-9

This is why `README.md` says the demo runs from localhost. A page served over HTTPS is
blocked by every browser from opening a plaintext WebSocket, so a deployed site needs
`wss://`, which needs TLS in front of FastAPI. That is Caddy's entire job here.

The frontend already handles the client half. `lib/ws.ts:resolveStreamUrl()` upgrades
the scheme to `wss://` automatically for any non-loopback host, while keeping loopback
on `ws://` (a local server has no TLS terminator, so `wss://localhost:8000` could never
connect). You do not have to do anything for this — but it is the function that makes a
cloud deployment possible at all, so do not "simplify" it.

### 2.2 Bandwidth is the real limit — measured, not estimated

Measured on this repo at `f479024`, streaming from the real pipeline:

| | Value |
|---|---|
| Mean frame (real KITTI, seq 04) | **1.93 MB** |
| Mean frame (`--fixtures`) | 1.14 MB |
| Raw stream | **90 Mbit/s** |
| Same frames, deflate level 6 | 34 % → **31 Mbit/s** |
| Egress per viewer-hour (compressed) | **~14 GB** |

Now put that against the free tiers:

| Provider | Free CPU / RAM | Free egress | Viewer-hours before you are billed |
|---|---|---|---|
| **Oracle Cloud Always Free** | 4 ARM OCPU / 24 GB | **10 TB/mo** | **~720 h** ✅ |
| AWS Free Tier | 1 vCPU / 1 GB (12 mo) | 100 GB/mo | ~7 h ⚠️ |
| Azure Free | 1 vCPU / 1 GB (12 mo) | 100 GB/mo | ~7 h ⚠️ |
| GCP Free Tier | 2 vCPU burst / 1 GB | **1 GB/mo** | **~4 minutes** ❌ |

**Use Oracle Cloud.** It is the only free tier whose egress allowance survives contact
with this workload, and it is Always Free rather than a 12-month trial. AWS or Azure
will work for a short judged demo if Oracle has no ARM capacity in your region, but
watch the meter.

---

## 3. Prerequisites

- Oracle Cloud account (needs a card for identity verification; Always Free resources
  are not charged)
- A free DuckDNS subdomain — https://www.duckdns.org
- The Firebase and Atlas values you already have in `frontend/.env.local`
- An SSH key pair

```bash
# On your Mac, if you do not already have one
ssh-keygen -t ed25519 -C "avr25d-deploy" -f ~/.ssh/avr25d
```

---

## 4. Create the VM

Oracle Cloud console → **Compute → Instances → Create instance**.

| Field | Value |
|---|---|
| Image | **Canonical Ubuntu 24.04** |
| Shape | **Ampere · VM.Standard.A1.Flex** |
| OCPUs / Memory | **4 / 24 GB** (the whole Always Free ARM allowance) |
| Boot volume | 50 GB (200 GB total is free) |
| SSH key | paste `~/.ssh/avr25d.pub` |

> **"Out of host capacity"** is common on A1 in busy regions. Retry, try a different
> availability domain, or fall back to **VM.Standard.E2.1.Micro** (x86, 1 core, 1 GB) —
> which is also Always Free but too small to build the frontend image on. If you take
> the micro shape, build images on your Mac and push them to GHCR instead (§13).

Note the **public IP** when it boots.

```bash
ssh -i ~/.ssh/avr25d ubuntu@<PUBLIC_IP>
```

---

## 5. Open the firewall — both of them

This is the step that wastes an afternoon. Oracle blocks ports in **two** independent
places and fixing only one looks identical to fixing neither.

**5.1 — Security list (the cloud-side firewall).** Console → Networking → Virtual Cloud
Networks → your VCN → Subnets → your subnet → Security Lists → Default → **Add Ingress
Rules**:

| Source CIDR | Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

**5.2 — iptables on the instance itself.** Oracle's Ubuntu images ship a default REJECT
rule that `ufw` does not manage:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

Verify from your Mac — this must connect (refused is fine, *timeout* means still blocked):

```bash
nc -vz <PUBLIC_IP> 80
```

---

## 6. Point DNS at it

Register a subdomain at https://www.duckdns.org and set its IP to your VM's public IP.

Use DuckDNS rather than an `nip.io`-style wildcard: `duckdns.org` is on the Public
Suffix List, so your subdomain gets its own Let's Encrypt rate-limit bucket. Wildcard
DNS services share one bucket across every user and it is frequently exhausted.

```bash
# Confirm it resolves before going further — Caddy cannot get a certificate otherwise
dig +short avr25d.duckdns.org
```

---

## 7. Install Docker on the VM

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
     -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
     docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER && newgrp docker
docker run --rm hello-world      # must succeed before continuing
```

---

## 8. Get the code and the frame data onto the VM

```bash
git clone https://github.com/sam-eer12/sih2026.git
cd sih2026
```

The dataset is **not** in git (`model/.gitignore` excludes `data/*`) and you do not want
2.2 GB of KITTI on the VM anyway. Three options, in order of preference:

### Option A — a recorded replay log (recommended)

Deterministic, needs no dataset, and cannot fail differently on the VM than it did when
you recorded it. This is also the R-7 demo fallback, so recording it is work you owe
anyway.

**On your Mac**, with KITTI present:

```bash
cd model
mkdir -p data/logs
../backend/.venv/bin/python -m avr25d.server.app \
    --infer geometric --seq 04 --data data/kitti \
    --port 8000 --record data/logs/demo.log
# let it run through the sequence, then Ctrl-C
gzip -6 data/logs/demo.log          # measured: 54 MB → 22 MB
```

Ship it:

```bash
scp -i ~/.ssh/avr25d model/data/logs/demo.log.gz ubuntu@<PUBLIC_IP>:~/sih2026/model/data/logs/
ssh -i ~/.ssh/avr25d ubuntu@<PUBLIC_IP> \
    'cd ~/sih2026/model/data/logs && gunzip -f demo.log.gz'
```

> **`--record` only works with the real pipeline.** `--fixtures --record` silently
> records nothing — `main()` passes `record_path` to `PipelineWorker` only on the
> `--infer` branch (`server/app.py`). If your log is 0 bytes, that is why.

### Option B — fixtures

Zero data, schema-valid frames, runs instantly. Fine to get the link live while you
record a proper log. Change the backend `command:` in `docker-compose.yml` to
`--fixtures`.

### Option C — the label cache

Highest fidelity but you must ship `model/data/cache/network` (~1 GB) and the KITTI
scans. Only worth it if the deployed site has to show live pipeline numbers rather than
a replay. Command becomes `--infer cached --seq 04 --cache data/cache/network`.

---

## 9. Configure

```bash
cp deploy/.env.example deploy/.env
nano deploy/.env
```

Fill in `DOMAIN` plus the Firebase and Mongo values from your local
`frontend/.env.local`. `deploy/.env` is gitignored.

**Two classes of variable, and mixing them up is the most common failure:**

| | Where it goes | Why |
|---|---|---|
| `NEXT_PUBLIC_*` | **Build args** | Inlined into the JS bundle at build time. `proxy.ts` reads them at module scope to decide whether the auth gate is live at all. |
| `FIREBASE_SERVICE_ACCOUNT`, `MONGODB_URI` | **Run-time env** | Credentials. A build arg is readable forever via `docker history`. |

`NEXT_PUBLIC_WS_URL` is derived by compose as `wss://${DOMAIN}/stream` so it cannot
drift from `DOMAIN`.

**Atlas:** add the VM's public IP under **Network Access**, or every write path fails
with a server-selection timeout that looks nothing like a firewall problem.

**Firebase:** add your domain under **Authentication → Settings → Authorized domains**,
or Google sign-in returns `auth/unauthorized-domain`.

---

## 10. Build and run

```bash
cd ~/sih2026/deploy
docker compose build          # ~8-12 min on 4 ARM OCPUs, first time only
docker compose up -d
docker compose logs -f
```

Caddy requests a certificate on first boot. Watch for `certificate obtained
successfully` in the logs. If it fails, it is almost always §5 (port 80 unreachable) or
§6 (DNS not propagated).

---

## 11. Verify the deployment

Run all five. The last two are the ones that matter for the requirements.

```bash
# 1. TLS and the backend are both alive
curl https://avr25d.duckdns.org/health
# → {"status":"ok","n_cells":705771}

# 2. Certificate is real, not Caddy's internal fallback
echo | openssl s_client -connect avr25d.duckdns.org:443 2>/dev/null \
     | grep -E 'issuer|subject'

# 3. The app shell renders
curl -sI https://avr25d.duckdns.org | head -1

# 4. The wss:// stream actually carries frames (run on your Mac)
python3 - <<'PY'
import asyncio, websockets
async def main():
    async with websockets.connect(
        'wss://avr25d.duckdns.org/stream', max_size=None) as ws:
        for i in range(3):
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            print(f'frame {i}: {len(raw)/1e6:.2f} MB')
asyncio.run(main())
PY

# 5. T-W6 — Next.js is not in the frame path.
#    Kill the frontend; the stream must keep flowing.
docker compose stop frontend
#    ...re-run check 4: it still delivers frames...
docker compose start frontend
```

Then open `https://avr25d.duckdns.org/dashboard` in a browser, sign in, and confirm the
HUD populates and the viewer renders. Check DevTools → Network → WS: the socket should
be `wss://avr25d.duckdns.org/stream` with no Next.js handler in the trace.

**Seed the scene registry** (FR-40) once, with a valid ID token:

```bash
curl -X POST https://avr25d.duckdns.org/api/scenes \
     -H "Authorization: Bearer <FIREBASE_ID_TOKEN>" \
     -H 'Content-Type: application/json' \
     --data @model/data/scenes_registry.json
```

---

## 12. Tuning for the network you will actually have

Defaults are tuned for localhost, where 90 Mbit/s is free. Over the internet they are
not. Both levers below are worth applying before a judged demo.

### 12.1 Turn on WebSocket compression — 3× less traffic

`uvicorn` supports per-message deflate but `server/app.py` does not pass it. One line:

```python
# model/avr25d/server/app.py — in main(), the uvicorn.run(...) call
    uvicorn.run(
        app,
        host      = args.host,
        port      = args.port,
        log_level = args.log_level,
        ws_per_message_deflate = True,     # 90 Mbit/s → 31 Mbit/s, measured
    )
```

Costs CPU on the server to save bandwidth. On 4 ARM OCPUs serving a handful of viewers
that is the right trade; on the `E2.1.Micro` fallback shape it may not be.

A reverse proxy **cannot** do this for you — `permessage-deflate` is negotiated per
WebSocket connection, and Caddy's `encode` directive does not apply to upgraded
connections.

### 12.2 Cap the frame rate

`model/avr25d/config.yaml`:

```yaml
runtime:
  target_fps: 30      # localhost default
```

For a remote demo, 10–12 is plenty — the eye cannot tell on a projected screen, and it
is a linear cut in bandwidth. Mount an override rather than editing the baked-in file,
so the committed config keeps describing the machine `make bench` runs on:

```bash
# On the VM — a full copy, because a bind mount replaces the whole file
cp ../model/avr25d/config.yaml config.cloud.yaml
sed -i 's/^  target_fps: 30/  target_fps: 12/' config.cloud.yaml
```

```yaml
# docker-compose.yml, backend service
    volumes:
      - ../model/data:/app/model/data
      - ./config.cloud.yaml:/app/model/avr25d/config.yaml:ro
```

`config.cloud.yaml` is a copy and will drift as `config.yaml` changes. Re-copy it after
any change to thresholds, or you will be demoing last week's tuning.

> **Do not regenerate `results.json` from a VM run.** `RESULTS.md` latency figures are
> machine-specific and the authoritative numbers come from `make bench` on a known
> machine (NFR-5, PRD §11). A slower VM number is not a new result; it is a different
> machine.

---

## 13. Alternatives

### 13.1 Cloudflare Tunnel — no open ports, no DNS, no certificates

If §5 defeats you, this bypasses it entirely. The tunnel dials **out** from the VM, so
no ingress rule is needed and TLS is Cloudflare's problem.

```bash
docker run -d --name tunnel --network deploy_default \
  cloudflare/cloudflared:latest tunnel --no-autoupdate \
  --url http://caddy:80
docker logs tunnel      # prints a https://<random>.trycloudflare.com URL
```

Trade-offs: the quick-tunnel hostname is random and changes on restart (fine for a
submission link recorded the same day, bad for anything durable), and Cloudflare's free
plan proxies WebSockets but is not built for a sustained 30 Mbit/s stream. Use a named
tunnel with your own domain if you go this route for real.

### 13.2 Frontend on Vercel, backend on the VM

Arguably the better free architecture: Vercel serves the Next.js app on its CDN for
free with HTTPS, and the VM only runs FastAPI + Caddy. Less VM CPU, faster page loads,
and the `runs`/`decisions` API routes run on Vercel's serverless functions.

- Deploy `frontend/` to Vercel; set every `NEXT_PUBLIC_*` plus `FIREBASE_SERVICE_ACCOUNT`
  and `MONGODB_URI` in the Vercel project's environment variables
- Set `NEXT_PUBLIC_WS_URL=wss://avr25d.duckdns.org/stream`
- On the VM, run only the `caddy` and `backend` services:
  `docker compose up -d caddy backend`
- Atlas Network Access must then allow `0.0.0.0/0`, because Vercel's function IPs are
  not fixed

### 13.3 Building images on your Mac

If the VM is too small to build (the `E2.1.Micro` fallback), build for ARM on your Mac
and push to GitHub Container Registry — free for public images:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u <user> --password-stdin
docker buildx build --platform linux/arm64 \
  -f deploy/Dockerfile.backend -t ghcr.io/<user>/avr25d-backend:latest --push .
```

Then replace `build:` with `image:` in `docker-compose.yml` on the VM.

---

## 14. Operations

```bash
cd ~/sih2026/deploy

docker compose ps                      # what is running
docker compose logs -f backend         # follow one service
docker compose restart backend         # restart without rebuilding
docker compose down                    # stop everything (certs survive)
docker compose up -d --build           # after a git pull
docker stats                           # CPU/memory per container

# Deploy a new commit
cd ~/sih2026 && git pull && cd deploy && docker compose up -d --build
```

**Do not `docker compose down -v`.** The `-v` deletes the `caddy_data` volume with your
certificates in it, and Let's Encrypt allows only 5 duplicate certificates per week.

---

## 15. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Browser: "connection refused" on `wss://` | Ports blocked | Both halves of §5 — security list *and* iptables |
| Caddy log: "could not get certificate" | Port 80 unreachable, or DNS not propagated | `nc -vz <IP> 80`; `dig +short <domain>` |
| Cert is `CN=Caddy Local Authority` | Caddy fell back to internal CA | `DOMAIN` unset or not a public hostname |
| Dashboard loads but never streams | `NEXT_PUBLIC_WS_URL` baked wrong | Rebuild, do not restart: `docker compose build --no-cache frontend` |
| Anyone can reach `/dashboard` | Auth gate inert | `NEXT_PUBLIC_FIREBASE_*` were empty **at build time** (`proxy.ts:36`). Rebuild. |
| Sign-in: `auth/unauthorized-domain` | Domain not allowlisted | Firebase → Authentication → Settings → Authorized domains |
| API routes 500 on every write | Atlas IP allowlist | Atlas → Network Access → add the VM IP |
| Backend exits immediately | Replay log missing/empty | `ls -la model/data/logs/`; see the `--record` note in §8 |
| Stream stutters, viewer freezes | Bandwidth | §12 — enable deflate, drop `target_fps` |
| Frontend build OOM-killed | <2 GB RAM | Build on your Mac and push to GHCR (§13.3) |

---

## 16. What this does *not* change

**The live demo still runs from `http://localhost:3000`.** NFR-9 and the demo run-book
are unchanged. This deployment exists for the submission link and for judges who want to
open the project from their own machine. The rehearsed demo path stays local, where the
frame stream is free and nothing depends on conference wifi.

Keep the replay-log fallback (R-7) rehearsed regardless of what is deployed here.

---

## 17. Cost

| Item | Plan | Cost |
|---|---|---|
| VM — Oracle Ampere A1, 4 OCPU / 24 GB | Always Free | ₹0 |
| Egress — 10 TB/month | Always Free | ₹0 |
| Domain — DuckDNS subdomain | Free | ₹0 |
| TLS — Let's Encrypt via Caddy | Free | ₹0 |
| MongoDB Atlas M0, 512 MB | Free forever | ₹0 |
| Firebase Auth | Spark | ₹0 |
| **Total** | | **₹0** |

Oracle's Always Free tier has no expiry, unlike AWS's and Azure's 12-month trials. Keep
an eye on the account after the hackathon anyway — idle Always Free compute instances can
be reclaimed after long periods of inactivity.
