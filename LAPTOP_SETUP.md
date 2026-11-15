# Run Trusted Trade on your own laptop

## Option 1: offline judging demo (recommended first)

Prerequisites: Python 3.11 or newer and internet for the first dependency install.
After installation, sample mode makes no Claude, supplier or Vapi calls. It does
not need API keys, the official catalogue, ngrok or a Vapi account.

1. Download and extract Trusted_Trade_Agents_API.zip into a new folder.
2. Windows: double-click **start_demo.cmd**. macOS/Linux: open Terminal in the
   extracted folder and run `sh start_demo.sh`.
3. Open http://127.0.0.1:8000 in your browser.
4. Copy the reviewer token printed in the terminal into the workspace login form.
5. Keep the terminal running while you use the demo. Ctrl+C stops it.

If Windows cannot find `py`, install Python from https://www.python.org/downloads/
and enable its launcher. On Ubuntu, a missing venv module may require your
system's `python3-venv` package. The launchers use a local virtual environment.
If port 8000 is already in use, run the created virtual environment's Python with
`demo.py --port 8001` and open http://127.0.0.1:8001 instead.

### Manual setup on Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe demo.py
```

### Manual setup on macOS / Linux

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python demo.py
```

### The repeatable walkthrough

Sample mode uses the actual gateway, UI, approval and receipt routes with fixed
synthetic recipe/product/price/stock responses. A yellow banner identifies it.
It starts a fresh temporary database each time. Receipts last for that running
session. It does not demonstrate live Claude quality, supplier stock or latency.

- **Meal with an exception:** open the seeded Spaghetti bolognese basket for 200.
  One beef product is unavailable, so another matching product supplies the meat.
  Wine is unavailable. Review the proposed omission and click Yes to record a
  mock receipt. Inspect Recipe, quantities & decision history.
- **Human spending approval:** open the seeded 1,000 L lactose-free milk request.
  Its sample subtotal is €1,770 including tax, above the €1,200 authority. Approve
  spending, then recheck and commit the mock order.
- **Autonomous commitment:** the seeded 10 L milk request already has a mock
  receipt within authority. Alternatively, use the external agent command below.
- **New sample request:** Plan a meal → Quick plan → Chickpea curry or Lohikeitto.
  Use the suggested delivery date printed in the terminal. Leave preferences
  blank. Sample mode supports those dishes and Spaghetti bolognese only. Unknown
  dishes, preference interpretation and web research require live mode.
- **Open interface:** visit http://127.0.0.1:8000/docs and inspect structured
  products, offers, proposals, recipe jobs and mock receipt endpoints.

### External agent in a second terminal

On Windows, replace TOKEN with the agent token from the running demo terminal and
DATE with its suggested delivery date:

```powershell
$env:AIMO_AGENT_TOKEN = "TOKEN"
.\.venv\Scripts\python.exe agent_client.py --date DATE --litres 10
```

On macOS/Linux:

```sh
AIMO_AGENT_TOKEN="TOKEN" .venv/bin/python agent_client.py --date DATE --litres 10
```

This demonstrates the purchasing API independently of the UI. Use the agent token,
not the reviewer token. Check `agent_client.py --help` for its commitment option.

## Option 2: live Claude and supplied Aimo mock APIs

Use the same virtual environment. Obtain these separately:

- The organiser-supplied product JSON and Aimo mock API key.
- Your own Anthropic Console API key with model access and available API credit.
- Optional Vapi configuration for voice. Text and direct product search work
  without Vapi or ngrok.

Copy `config.env.example` to **config.env**, fill in your own keys locally, and
place the official `valio_aimo_junction26_product_data.json` beside the code. You
can instead set `AIMO_CATALOG` to its absolute path. Then run:

```powershell
.\.venv\Scripts\python.exe run_live.py
```

macOS/Linux: `.venv/bin/python run_live.py`. Keys already set in the terminal take
priority over config.env. Use a fresh terminal if you intend the file to replace
old environment values. The launcher prints new local agent/reviewer credentials
when none were supplied. Paste the reviewer token into the dashboard.

Start with Quick plan. It proposes an AI recipe draft for whole-basket review.
Published mode uses web research and can take longer. Live mode still creates
local mock receipts, because the challenge provides no supplier order API.
Never use the production webshop to place a demonstration order.

Keep config.env, tokens, databases and the official catalogue out of public source
uploads. The included .gitignore excludes them. Do not share your API keys with
judges. They can use offline mode, their own authorised keys, or your supervised
running live demo.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Browser connection refused | Keep the server terminal running. Check the printed port. |
| Token not accepted | Use the token from this running server, not a previous session. |
| Sample dish unsupported | Use one of the three sample dishes, or start live mode. |
| Live supplier HTTP 401 | Check AIMO_API_KEY. It is separate from the local gateway token. |
| Claude configuration / credit error | Check ANTHROPIC_API_KEY, workspace credit and model access. |
| Old UI | Ctrl+F5 after replacing files and restarting. |
| Delivery unavailable | Choose a valid date. Fixed organiser cut-offs do not move automatically. |

Run offline checks with the virtual environment Python:
`python -m unittest discover -s . -p "test*.py"`.

The launchers use requirements-lock.txt to reproduce the tested dependency versions. requirements.txt contains the broader supported ranges for developers. Automated checks ran on Linux with Python 3.12; Windows/macOS launcher commands are provided but were not executed on native Windows/macOS in this environment.
