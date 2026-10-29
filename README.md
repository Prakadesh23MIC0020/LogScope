# LogScope

LogScope is a Flask-based log analyzer using Neon PostgreSQL through `psycopg`. The existing Flask + Neon PostgreSQL architecture and dark visual theme are retained, with a refined interface, community fixes, anonymous upvotes, and no Analysis History page.

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
- New analyses are not inserted into the `analyses` table. The Analysis History page has been removed; `/api/history` remains as a compatibility endpoint returning an empty list.
- The existing `analyses` table and its existing rows are not deleted or modified.
- Reusable general solutions remain in the existing `knowledge` table. Error signatures are normalized before learning; raw logs and stack traces are not saved as knowledge.
- Users can anonymously submit a verified fix through the analysis result. The backend sanitizes the submitted fields, stores a generalized record in `knowledge`, and publishes a community-fix record. No login is required. For a public deployment, configure platform-level rate limiting and monitoring for anonymous submissions.
- External research sends a short sanitized error signature, not the uploaded log or stack trace.
- No Gemini SDK, API key, or other paid AI API is required. Diagnosis uses local deterministic rules, the existing knowledge base, and optional Stack Overflow/GitHub search results. Unknown errors are not given invented fixes.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Diagnosis regression coverage

`sample_logs/shopease_regression.log` is a regression fixture assembled from the reported ShopEase failure scenarios (missing column/order HTTP 500, checkout payment timeout/HTTP 502, HikariCP acquisition timeout/HTTP 503, nullable cart timestamp, repeated login failures). It is not claimed to be the original user-provided ShopEase log file.

Metrics use these definitions: `total_lines` counts every input line; `total_errors` counts grouped Error/Critical occurrences except correlated downstream HTTP symptoms; `critical` counts only Critical-severity occurrences after that same exclusion; `unique_errors` counts distinct normalized `(type, message signature)` groups, including visible correlated symptoms. Numeric values are retained in signatures when they may distinguish different errors.


## Confirmed learning and feedback

LogScope can now learn reusable troubleshooting knowledge from explicit user feedback:

1. Analyze a log and review the diagnosis and suggested fix.
2. Open **Teach LogScope · confirm or improve this fix** on an error card.
3. Edit the generalized error signature, explanation, root cause, and fix as needed.
4. Select **Confirm fix & teach LogScope** only after the fix has been verified to resolve the problem. The solution is saved in the PostgreSQL knowledge table with source `user-confirmed`.
5. On later analyses, LogScope checks the stored knowledge for a matching error type, message pattern, and environment. A matching user-confirmed solution can be shown as the diagnosis.
6. If a suggestion did not work, select **This did not fix it**. This feedback is acknowledged but is not promoted into trusted knowledge.

The learning system stores the generalized signature and solution rather than the full uploaded log. It applies basic redaction to secrets, paths, emails, IP addresses, phone numbers, usernames, and identifiers. Users should still review submitted examples and remove sensitive material before saving.

### Database setup

The persistent knowledge base requires PostgreSQL. Configure `DATABASE_URL` before starting the app. The schema is created automatically on startup. Without a working database, persistent learning and knowledge statistics will not be available.

### Important trust and deployment notes

- Learning is **supervised**, not automatic: an error by itself never becomes a trusted fix. A user must explicitly confirm a successful outcome.
- Confirmed knowledge is reused as a recommendation, not executed automatically. Review it for your specific codebase and environment before applying it.
- This app currently has no user-account system. If you expose it to the public internet, put authentication and rate limiting in front of the feedback endpoint to reduce malicious or low-quality knowledge submissions. Redaction helps privacy but cannot guarantee removal of every secret.
- This is not a claim that LogScope can diagnose every possible error. Unmatched errors should still be reported as uncertain rather than assigned an invented root cause.



## Public GitHub Log Browser

The **GitHub Logs** tab can browse supported text/log files in any public GitHub repository without a GitHub token. Enter a repository URL (for example, `https://github.com/logpai/loghub`), load its default branch file tree, search by filename/path, select multiple files, and choose **Fetch & Analyze** to pass their contents to LogScope's existing analyzer. LogScope does not upload or modify repository contents.

Supported extensions: `.log`, `.txt`, `.out`, `.err`, `.json`, and `.csv`. To keep requests within typical serverless limits, each file is limited to 5 MB, a batch to 15 MB total, and a batch to 50 files. GitHub's unauthenticated API has a rate limit, so repeated repository browsing may require waiting for the limit to reset. Only public repositories are supported. Do not analyze public logs that contain secrets or personal information unless you have permission to process them.

### Using GitHub Logs on Vercel

No GitHub token or new environment variables are required for public repositories. Deploy the updated LogScope application, open **GitHub Logs**, enter a public repository URL, select files, and click **Fetch & Analyze**. The server retrieves the selected files and combines them for one analysis; the repository URL and selected paths are validated server-side.


## Anonymous community fixes and upvotes

- The Knowledge Base tab shows live database counts for built-in rules, user-learned rules, community fixes, and votes. The Analysis History page is removed from the interface; uploads remain temporary.
- When a user confirms a fix in the analysis result, LogScope stores a sanitized reusable knowledge record and publishes an anonymous community-fix record.
- Similar community fixes appear in a **View User Fixes** dropdown on an error card. The dropdown is omitted when there are no matching fixes.
- Users can upvote both the displayed rule-based diagnosis and community fixes without creating an account. A database uniqueness constraint permits one vote per hashed voter address and target, so refreshing the page does not add another vote.
- Raw IP addresses are not stored. Vote identity is an HMAC hash using `VOTE_HASH_SECRET`; configure a strong, stable secret in deployment. If unset, the database URL is used as a fallback secret, so setting `VOTE_HASH_SECRET` explicitly is recommended.
- IP-based voting has tradeoffs: people sharing a public IP may share one vote, and IP changes can permit another vote. Behind a reverse proxy, ensure the proxy's forwarded-address behavior is trusted and configured correctly.
- Confidence is a transparent display score that rises gradually with upvotes and is capped at 99%; votes are signals of usefulness, not proof that a fix is universally correct. User-submitted fixes remain recommendations and are never executed automatically.
- The community-fix tables (`community_fixes` and `fix_votes`) are created additively by `init_db()`. Existing `knowledge` and `analyses` tables are not dropped or recreated.
