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

## 4) Runtime config

Create `~/.nanobot/config.json` and put your API and model settings.

## 5) Start web service (example)

```bash
source .venv/bin/activate
python -m uvicorn nanobot.web.app:create_app --factory --host 127.0.0.1 --port 9936
```

Then put Caddy/Nginx in front of `127.0.0.1:9936`.
