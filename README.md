# Daily Job Digest

Every day at 9:00 AM IST this reads your LinkedIn, Naukri and Indeed **job-alert emails** in Gmail. It
filters and ranks the jobs against `profile.md`, drafts cover letters and emails you a report with the top 10.

It never logs in to or scrapes the job portals, and it **never applies**. You open each link and apply yourself.

## One-time setup

1. **Job alerts** (on each site, while logged in). Create saved searches with alerts turned on (daily),
   delivered to your Gmail:
   - Keywords: AI Engineer, Machine Learning Engineer, Data Scientist, DevOps Engineer, Data Analyst
   - Locations: Chennai, Coimbatore, Erode, Bangalore, Remote
   - Experience: 1–2 years (Naukri), Full-time, salary 3 LPA+ where the site offers it
2. **Gmail App Password**: Google Account → Security → turn on 2-Step Verification → App passwords →
   create one named "Job Digest". Copy the 16 characters.
3. Copy `.env.example` to `.env` and fill in `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `REPORT_TO`.
   Optional: add `ANTHROPIC_API_KEY` for smarter scoring and tailored cover letters. Without a key it
   uses free keyword scoring and a template letter.
4. Test: `python job_digest.py --dry-run`. This saves the report to `reports\` without emailing it.
5. Real run: `python job_digest.py`. Check your Gmail for the report.
6. Schedule: `powershell -ExecutionPolicy Bypass -File .\setup_task.ps1`

## Resume versions
`resumes/` has four tailored one-page PDFs: AI/GenAI Engineer, Data Scientist/ML Engineer, DevOps/MLOps Engineer
and Data Analyst. Each report row names the PDF to attach. They are built from the facts in the original resume;
only the title, summary and ordering differ. After you change `build_resumes.py`, run `python build_resumes.py`
to rebuild them.

## AI scoring
`ANTHROPIC_API_KEY` is used if it is set. If not, `GROQ_API_KEY` is used with the free tier and
`openai/gpt-oss-120b`. With neither key, the script falls back to keyword scoring. If any AI call fails or hits
a rate limit, that batch falls back to keywords, so the daily report still goes out.

## Google Jobs (SerpApi)
If `SERPAPI_KEY` is set, each run also searches Google Jobs. It runs 3 of the 4 searches in `config.json` each
day, rotating, which comes to about 90 searches a month and fits the free 100/month plan. Jobs posted more than
7 days ago are skipped. When a Google result points to the same LinkedIn, Naukri or Indeed job as an alert
email, it is listed only once.

## Notes
- Jobs already reported are remembered in `seen_jobs.json`, so each day's report only shows new jobs.
- The "closed" check uses what the alert says. Always confirm the job is still open when you click it.
- Change filters, the top-N count or the minimum score in `config.json`. Update `profile.md` when your
  resume changes.
- The PC must be on for the 9 AM run. If it was off, the task runs as soon as you switch it on.
