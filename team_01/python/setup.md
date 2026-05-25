# PermanenceOS — Setup & Run Checklist

---

## Step 1 — Activate the Virtual Environment

Open **Windows PowerShell** and navigate to the repo root:

```powershell
cd C:\Users\Win11\Desktop\AIA2026\PermanenceOS-UI
.\.venv\Scripts\Activate.ps1
```

You should see `(.venv)` at the start of the prompt.

---

## Step 2 — Install dependencies (first time only)

```powershell
pip install -r requirements.txt
```

---

## Step 3 — Open LM Studio and start the server

1. Open **LM Studio**
2. Load the model: **`meta-llama-3.1-8b-instruct`**
3. Go to **Local Server** → click **Start Server**
4. Confirm it's reachable at `http://127.0.0.1:1234`

Verify:
```powershell
curl http://localhost:1234/v1/models
```

---

## Step 4 — Check `.env`

The `.env` file at the repo root should contain:

```dotenv
LOCAL_LLM_ENDPOINT = "http://127.0.0.1:1234/v1/"
LOCAL_LLM_MODEL    = "meta-llama-3.1-8b-instruct"
```

No other variables are required.

---

## Step 5 — Run the agent (CLI)

From the `team_01/python/` folder:

```powershell
cd team_01\python
python main.py "add a structural grid"
python main.py "evaluate the structural layout"
python main.py "what if we remove column C_1_2"
```

The agent will:
1. Reason with the LLM about your request
2. Call the appropriate local Python function (grid generation, structural modification, evaluation)
3. Save the result to `team_01_edited_layout.json`
4. Print a written response with the evaluation table

---

## Step 6 — Run the visual dashboard (Streamlit)

In a second terminal (venv activated), from `team_01/python/`:

```powershell
streamlit run app.py
```

Then in a third terminal, start the Three.js tile server from the repo root:

```powershell
cd C:\Users\Win11\Desktop\AIA2026\PermanenceOS-UI
python -m http.server 8000
```

Open the browser at `http://localhost:8501`.

### Streamlit tabs
| Tab | What it does |
|-----|-------------|
| Layout & Grid | Upload layout JSON, create a structural grid visually, see element counts |
| Cost Calculator | Configure material prices, run structural evaluation, calculate total cost |

---

## Quick reference

| Service | Address |
|---------|---------|
| LM Studio API | `http://127.0.0.1:1234/v1/` |
| Streamlit app | `http://localhost:8501` |
| Three.js tile server | `http://127.0.0.1:8000` |
