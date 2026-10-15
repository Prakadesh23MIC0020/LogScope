# LogScope

LogScope is a Flask-based log analyzer using Neon PostgreSQL through `psycopg`. The existing HTML, CSS, and frontend behavior are retained.

## Run locally (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:DATABASE_URL = "YOUR_EXISTING_NEON_POSTGRESQL_CONNECTION_STRING"
python -m unittest discover -s tests -v
python app.py
```

Open `http://127.0.0.1:5000`. The database URL must point to the existing Neon database. Do not replace the database or recreate its tables.

## Privacy and learning behavior

- Uploaded logs are processed for the current request only.
- New analyses are not inserted into the `analyses` table. `/api/history` returns an empty list so the existing History view remains compatible without retaining uploads.
- The existing `analyses` table and its existing rows are not deleted or modified.
- Reusable general solutions remain in the existing `knowledge` table. Error signatures are normalized before learning; raw logs and stack traces are not saved as knowledge.
- Novel fixes can be added through `POST /api/knowledge/feedback` only when a user submits a solution with `confirmed: true`. Set a strong `LEARNING_WRITE_TOKEN` environment variable and send it in the `X-Learning-Token` header. Submit a generalized pattern, not raw log text.
- External research sends a short sanitized error signature, not the uploaded log or stack trace.
- No Gemini SDK, API key, or other paid AI API is required. Diagnosis uses local deterministic rules, the existing knowledge base, and optional Stack Overflow/GitHub search results. Unknown errors are not given invented fixes.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Diagnosis regression coverage

`sample_logs/shopease_regression.log` is a regression fixture assembled from the reported ShopEase failure scenarios (missing column/order HTTP 500, checkout payment timeout/HTTP 502, HikariCP acquisition timeout/HTTP 503, nullable cart timestamp, repeated login failures). It is not claimed to be the original user-provided ShopEase log file.

Metrics use these definitions: `total_lines` counts every input line; `total_errors` counts grouped Error/Critical occurrences except correlated downstream HTTP symptoms; `critical` counts only Critical-severity occurrences after that same exclusion; `unique_errors` counts distinct normalized `(type, message signature)` groups, including visible correlated symptoms. Numeric values are retained in signatures when they may distinguish different errors.
