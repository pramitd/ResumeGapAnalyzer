# Resume Gap Analyzer

## 🚀 Live Application

**Use the deployed application here:**

👉 [https://pramit-dutta-giggity-resume-analyzer.streamlit.app/](https://pramit-dutta-giggity-resume-analyzer.streamlit.app/)

---
# Resume Gap Analyzer — Groq — GPT-OSS 120B

A generic Streamlit resume/job-description gap analyzer with deterministic weighted ATS scoring. No candidate-specific resume,
DOCX, YAML, API key, password, or generated profile is included.

## AI architecture

The app uses the Groq Python SDK and `openai/gpt-oss-120b`.

Profile creation uses **one Groq request**:

```text
Resume
  +
Optional profile/project-details DOCX
          ↓
Groq — GPT-OSS 120B
          ↓
master_content.yaml
master_project_details.yaml
```

If the optional DOCX is skipped, project context is extracted from the resume.

Job-description analysis uses one additional structured Groq request.

Groq JSON output is used so the application receives predictable JSON,
which is then written as YAML.

## V4 deterministic ATS scoring

V4 separates **evidence assessment** from **score calculation**.

Groq — GPT-OSS 120B evaluates each meaningful JD requirement against the
resume/profile and returns structured evidence with a status:

- `met` = clear evidence
- `partial` = related but incomplete evidence
- `not_met` = no supporting evidence
- `not_applicable` = genuinely not evaluable

Python then calculates the final ATS score. The LLM does **not** provide the
final `/100` score.

### Score weights

| Dimension | Weight |
|---|---:|
| Hard requirements | 30% |
| Skills / technologies | 25% |
| Experience alignment | 20% |
| Responsibilities | 15% |
| Keywords | 5% |
| Education / credentials | 5% |
| **Total** | **100%** |

Within each dimension, `met`, `partial`, and `not_met` map to `1.0`, `0.5`,
and `0.0`. Requirement importance applies deterministic multipliers:
`required = 1.5`, `preferred = 1.0`, `nice_to_have = 0.5`.

The Gap Report and UI expose the six component scores and the requirement
evidence used to calculate them.

## Supported uploads

### Resume

- PDF
- DOCX
- TXT

### Optional profile/project details

- DOCX
- Normal paragraphs
- Tables
- One table per project
- Two-column Field/Value or Label/Details layouts

### Job description

- PDF
- TXT
- Pasted text

## Streamlit Secrets

In Streamlit Community Cloud, open:

**App → Settings → Secrets**

Use:

```toml
APP_PASSWORD = "your-shared-password"
GROQ_API_KEY = "your-Groq-api-key"
```

Never commit `.streamlit/secrets.toml`.

The repository contains only:

```text
.streamlit/secrets.toml.example
```

## Local setup — Windows PowerShell

Clone:

```powershell
git clone https://github.com/pramitd/ResumeGapAnalyzer.git
cd ResumeGapAnalyzer
```

Create a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install Python dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Install Playwright Chromium:

```powershell
python -m playwright install chromium
```

Create local secrets:

```powershell
New-Item -ItemType Directory -Force .streamlit
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
notepad .streamlit\secrets.toml
```

Put your real values into `secrets.toml`:

```toml
APP_PASSWORD = "your-password"
GROQ_API_KEY = "your-key"
```

Run:

```powershell
streamlit run app.py
```

## GitHub upload / replace commands

If this folder is being used as the existing repository working tree:

```powershell
git status
git add .
git commit -m "Switch ResumeGapAnalyzer to Groq — GPT-OSS 120B"
git push origin main
```

If you are starting a clean local Git repository:

```powershell
git init
git branch -M main
git remote add origin https://github.com/pramitd/ResumeGapAnalyzer.git
git add .
git commit -m "Groq — GPT-OSS 120B Resume Gap Analyzer"
git push -u origin main
```

If GitHub already contains the correct repository and you are replacing the
working tree, use the first command sequence rather than adding a second remote.

## Streamlit deployment

The app entry point is:

```text
app.py
```

After pushing to GitHub, Streamlit Community Cloud can redeploy from the
repository.

Then set:

```toml
APP_PASSWORD = "your-shared-password"
GROQ_API_KEY = "your-Groq-api-key"
```

in Streamlit Secrets.

## Important

Do NOT upload:

```text
.streamlit/secrets.toml
.venv/
Applications/
profile/
```

The app creates candidate profile/application data in a per-session temporary
workspace on the Streamlit server. It is not committed to GitHub.

## Current Groq model

```text
openai/gpt-oss-120b
```

The model supports structured output and has a 1,048,576-token input limit.
Google currently describes 2.5 Flash as a stable model but notes that access to
2.5 models is being limited to users who have actively used them; if Google
changes access for a new project, the model can be changed centrally in
`groq_client.py`.



