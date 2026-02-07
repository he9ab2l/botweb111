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

Notes:
- Run `npm` commands inside `frontend/` only. The backend does not use Node.
- The build output goes to `nanobot/web/static/dist/` and is served by FastAPI.

## 4) Runtime config

You can configure models and API keys in two ways:

Option A: WebUI Settings (recommended)
- Start the server
- Open the UI
- Click `Settings`
- Add provider API key and set the model

Option B: Config file

```bash
mkdir -p ~/.nanobot
cp ./config.example.json ~/.nanobot/config.json
```

Then edit `~/.nanobot/config.json` and set at least one provider `apiKey`.

GLM/Z.ai example:
- set `providers.zhipu.apiKey`
- choose model `zai/glm-4.7`

OpenRouter example:
- set `providers.openrouter.apiKey`
- choose model `openrouter/stepfun/step-3.5-flash:free`

If the API key is not configured, the UI will still load, but model runs will fail until a key is set.

## 5) Start web service (example)

```bash
source .venv/bin/activate
python -m uvicorn nanobot.web.app:create_app --factory --host 127.0.0.1 --port 9936
```

Then put Caddy/Nginx in front of `127.0.0.1:9936`.

## 6) Optional: permissions mode

From the UI Settings panel, choose:
- Require Approval (tool execution prompts for each tool), or
- Allow All Tools (all tool calls execute without prompts)
