# Deploy on a New Server

## 1) Clone

```bash
git clone https://github.com/he9ab2l/botweb111.git
cd botweb111
```

## 2) Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## 3) Frontend build

```bash
cd frontend
npm install
npm run build
cd ..
```

Note:

- Run `npm` commands inside `frontend/` only. The backend does not use Node.
- The build output goes to `nanobot/web/static/dist/` and is served by FastAPI.

## 4) Runtime config

Create `~/.nanobot/config.json` and put your API and model settings.

Quick start:

```bash
mkdir -p ~/.nanobot
cp ./config.example.json ~/.nanobot/config.json
```

Then edit `~/.nanobot/config.json` and set at least one provider `apiKey` (e.g. `providers.openrouter.apiKey`).

If the API key is not configured, opening the web UI will show a setup page instead of the chat UI.

## 5) Start web service (example)

```bash
source .venv/bin/activate
python -m uvicorn nanobot.web.app:create_app --factory --host 127.0.0.1 --port 9936
```

Then put Caddy/Nginx in front of `127.0.0.1:9936`.
