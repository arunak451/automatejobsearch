"""Daily job digest: reads LinkedIn / Naukri / Indeed job-alert emails from Gmail and
Google Jobs results via SerpApi, ranks the jobs against profile.md, drafts cover
letters and emails a report.

It never logs in to or scrapes the job portals and never applies anywhere.
Applying is always manual.

Usage:
    python job_digest.py            # normal daily run (sends email)
    python job_digest.py --dry-run  # build report locally, do not send or mark jobs as seen
"""

import argparse
import datetime as dt
import email
import html
import imaplib
import json
import re
import smtplib
import sys
import time
import urllib.error
import urllib.request
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent
REPORTS = BASE / "reports"
SEEN_FILE = BASE / "seen_jobs.json"
SEEN_KEEP_DAYS = 45
CLAUDE_MODEL = "claude-opus-5-5"
GROQ_MODEL = "openai/gpt-oss-120b"


# ---------------------------------------------------------------- config

def load_env(dry_run):
    env = {}
    path = BASE / ".env"
    if not path.exists():
        sys.exit("Missing .env - copy .env.example to .env and fill it in.")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    env["GMAIL_APP_PASSWORD"] = env.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not dry_run:
        for key in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "REPORT_TO"):
            if not env.get(key):
                sys.exit(f"{key} is empty in .env")
    return env


def load_config():
    return json.loads((BASE / "config.json").read_text(encoding="utf-8"))


def load_seen():
    if not SEEN_FILE.exists():
        return {}
    seen = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    cutoff = (dt.date.today() - dt.timedelta(days=SEEN_KEEP_DAYS)).isoformat()
    return {k: v for k, v in seen.items() if v >= cutoff}


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(seen, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- gmail

def fetch_alert_emails(env, cfg):
    """Return [(sender, subject, html_body)] for recent job-alert emails."""
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(env["GMAIL_USER"], env["GMAIL_APP_PASSWORD"])
    status, _ = imap.select('"[Gmail]/All Mail"', readonly=True)
    if status != "OK":
        imap.select("INBOX", readonly=True)

    senders = " OR ".join(f"from:{s}" for s in cfg["alert_senders"])
    query = f'newer_than:{cfg["lookback_days"]}d ({senders})'
    status, data = imap.search(None, "X-GM-RAW", f'"{query}"')
    ids = data[0].split() if status == "OK" else []

    messages = []
    for msg_id in ids:
        status, parts = imap.fetch(msg_id, "(RFC822)")
        if status != "OK":
            continue
        msg = email.message_from_bytes(parts[0][1])
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                body = part.get_payload(decode=True).decode(charset, errors="replace")
                break
        if body:
            sender = str(make_header(decode_header(msg.get("From", ""))))
            subject = str(make_header(decode_header(msg.get("Subject", ""))))
            messages.append((sender, subject, body))
    imap.logout()
    return messages


# ---------------------------------------------------------------- parsing

LINKEDIN_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?\s]*-)?(\d{6,})")
NAUKRI_RE = re.compile(r"naukri\.com/(job-listings-[^?#&\s\"']+)")
INDEED_RE = re.compile(r"[?&]jk=([0-9a-f]{16})")


def candidate_urls(href):
    """The href itself plus any URL hidden in tracking-redirect query params."""
    urls = [href, unquote(href)]
    try:
        for values in parse_qs(urlparse(href).query).values():
            urls.extend(unquote(v) for v in values if "http" in v or "jk=" in v)
    except ValueError:
        pass
    return urls


def canonical_job(href):
    """Map a (possibly tracked) link to (job_key, source, clean_url), or None."""
    for url in candidate_urls(href):
        if m := LINKEDIN_RE.search(url):
            return f"li:{m[1]}", "LinkedIn", f"https://www.linkedin.com/jobs/view/{m[1]}/"
        if m := NAUKRI_RE.search(url):
            slug = m[1]
            job_id = re.search(r"(\d{8,})$", slug)
            return f"nk:{job_id[1] if job_id else slug}", "Naukri", f"https://www.naukri.com/{slug}"
        if m := INDEED_RE.search(url):
            return f"in:{m[1]}", "Indeed", f"https://in.indeed.com/viewjob?jk={m[1]}"
    return None


def card_text(anchor, key):
    """Text of the largest enclosing block that holds only this one job (its card)."""
    node, best = anchor, anchor.get_text(" ", strip=True)
    for _ in range(8):
        node = node.parent
        if node is None:
            break
        other_job = any((found := canonical_job(a["href"])) and found[0] != key
                        for a in node.find_all("a", href=True))
        text = node.get_text(" ", strip=True)
        if other_job or len(text) > 700:
            break
        best = text
    return re.sub(r"\s+", " ", best)


def extract_jobs(messages):
    jobs = {}
    for _sender, subject, body in messages:
        soup = BeautifulSoup(body, "html.parser")
        for a in soup.find_all("a", href=True):
            found = canonical_job(a["href"])
            if not found:
                continue
            key, source, url = found
            text = card_text(a, key)
            link_text = a.get_text(" ", strip=True)
            job = jobs.setdefault(key, {"key": key, "source": source, "url": url, "snippet": "",
                                        "link_text": "", "alert_subject": subject})
            if len(text) > len(job["snippet"]):
                job["snippet"] = text
            if len(link_text) > len(job["link_text"]) and len(link_text) < 120:
                job["link_text"] = link_text
    return list(jobs.values())


# ---------------------------------------------------------------- google jobs (serpapi)

def days_ago(extensions):
    for ext in extensions:
        ext = ext.lower()
        if "hour" in ext or "minute" in ext or "just" in ext:
            return 0
        if m := re.match(r"(\d+)\s+day", ext):
            return int(m[1])
        if "month" in ext or "week" in ext:
            return 30
    return None


def strip_tracking(url):
    return re.sub(r"[?&]utm_[^&]+", "", url).rstrip("?&")


def todays_searches(scfg, today):
    """Rotate through the configured searches so the monthly quota stretches."""
    searches, per_day = scfg["searches"], scfg["searches_per_day"]
    start = today.toordinal() * per_day % len(searches)
    return [searches[(start + i) % len(searches)] for i in range(min(per_day, len(searches)))]


def fetch_google_jobs(api_key, cfg, today):
    scfg = cfg["serpapi"]
    jobs = {}
    for search in todays_searches(scfg, today):
        params = {"engine": "google_jobs", "gl": "in", "hl": "en", "api_key": api_key, **search}
        try:
            with urllib.request.urlopen("https://serpapi.com/search.json?" + urlencode(params),
                                        timeout=60) as resp:
                data = json.load(resp)
        except OSError as e:
            print(f"SerpApi search failed ({search['q']}): {e}")
            continue
        if data.get("error"):
            print(f"SerpApi: {data['error']}")
            continue
        for r in data.get("jobs_results", []):
            age = days_ago(r.get("extensions", []))
            if age is not None and age > scfg["max_posted_days_ago"]:
                continue
            links = [r.get("source_link")] + [o.get("link") for o in r.get("apply_options", [])]
            links = [strip_tracking(l) for l in links if l]
            # Reuse the portal job key when Google points at LinkedIn/Naukri/Indeed, so a job
            # that also arrived by alert email is not listed twice.
            portal = next((found for l in links if (found := canonical_job(l))), None)
            company = r.get("company_name", "")
            key = portal[0] if portal else \
                "gj:" + re.sub(r"\W+", "-", f"{r.get('title', '')}-{company}".lower()).strip("-")
            url = links[0] if links else r.get("share_link", "")
            jobs[key] = {
                "key": key, "source": f"Google Jobs via {r.get('via', '?')}", "url": url,
                "link_text": r.get("title", ""), "company": company,
                "location": r.get("location", ""), "alert_subject": search["q"],
                "snippet": re.sub(r"\s+", " ", " · ".join([
                    r.get("title", ""), company, r.get("location", ""),
                    ", ".join(r.get("extensions", [])), r.get("description", "")[:1500]])),
            }
    return list(jobs.values())


# ---------------------------------------------------------------- ranking (LLM: Claude or Groq)

class RankedJob(BaseModel):
    key: str
    title: str
    company: str
    location: str
    salary: str
    experience_required: str
    job_type: str
    required_skills: list[str]
    matched_skills: list[str]
    missing_skills: list[str]
    match_score: int
    priority: str
    resume_version: str
    likely_closed: bool
    passes_filters: bool
    reason: str


class Ranking(BaseModel):
    jobs: list[RankedJob]


class Letter(BaseModel):
    key: str
    cover_letter: str


class Letters(BaseModel):
    letters: list[Letter]


def claude_llm(api_key):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    def call(system, user, schema):
        response = client.beta.messages.parse(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium"},
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        if response.stop_reason == "refusal":
            return None
        return response.parsed_output

    call.name, call.batch_size, call.letter_batch = "Claude", 40, 20
    return call


class RequestTooLarge(Exception):
    pass


def groq_llm(api_key):
    def call(system, user, schema):
        body = {
            "model": GROQ_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "schema": schema.model_json_schema()}},
            "reasoning_effort": "medium",
            "max_completion_tokens": 16000,
        }
        request = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                     "User-Agent": "job-digest"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=120) as resp:
                    data = json.load(resp)
                break
            except urllib.error.HTTPError as e:
                if e.code == 413:  # over the free-tier tokens-per-minute limit; caller splits the batch
                    raise RequestTooLarge() from e
                if e.code != 429 or attempt == 2:  # free-tier rate limit: wait and retry
                    print(f"Groq error {e.code}: {e.read()[:300]!r}")
                    return None
                time.sleep(min(float(e.headers.get("retry-after") or 20), 60))
        return schema.model_validate_json(data["choices"][0]["message"]["content"])

    call.name, call.batch_size, call.letter_batch = "Groq", 15, 5
    return call


def rank_with_llm(llm, jobs, cfg, profile):
    versions = ", ".join(cfg["resume_versions"])
    instructions = f"""You screen job listings for one candidate. Below are job cards extracted from
job-alert emails and Google Jobs (text may be partial). For every card return one entry with the same `key`.

Fill fields from the card text only; write "Not disclosed" when salary or experience is missing.
Do not invent requirements the card does not state.

Candidate filters:
- Roles: {", ".join(cfg["roles"])} (and close variants).
- Locations: {", ".join(cfg["locations"])}. Hybrid in these cities is fine.
- {cfg["job_type"]} only (no internships). Candidate has {cfg["experience_years"]["min"]}-{cfg["experience_years"]["max"]} years;
  reject senior/lead roles and any role whose minimum required experience is above
  {cfg["experience_years"]["reject_if_min_required_above"]} years.
- Salary at least {cfg["min_salary_lpa"]} LPA when disclosed; undisclosed salary is acceptable.
Set passes_filters=false when any filter clearly fails, and say which one in `reason`.
Set likely_closed=true only if the text says the job is closed, expired or no longer accepting applications.

match_score (0-100): overlap between the job's needs and the candidate profile, weighted toward the core
skills and the seniority fit. priority: "High" (>=75), "Medium" (55-74) or "Low".
resume_version: one of: {versions}.
reason: one short sentence on why it fits or does not.

<candidate_profile>
{profile}
</candidate_profile>"""

    def call_llm(batch):
        cards = json.dumps([{k: j[k] for k in ("key", "source", "snippet")} for j in batch],
                           ensure_ascii=False)
        try:
            return llm(instructions, f"<job_cards>{cards}</job_cards>", Ranking)
        except RequestTooLarge:
            if len(batch) == 1:
                raise
            half = len(batch) // 2
            parts = [call_llm(batch[:half]), call_llm(batch[half:])]
            return Ranking(jobs=[r for part in parts if part for r in part.jobs])

    ranked = []
    size = llm.batch_size
    for start in range(0, len(jobs), size):
        batch = jobs[start:start + size]
        try:
            result = call_llm(batch)
        except Exception as e:  # never lose the daily report over one bad batch
            print(f"{llm.name} failed on batch {start}: {e}")
            result = None
        if result is None:
            print(f"{llm.name} did not rank batch {start}; using keyword scoring for it.")
            ranked.extend(rank_with_keywords(batch, cfg))
            continue
        by_key = {j["key"]: j for j in batch}
        for r in result.jobs:
            if r.key in by_key:
                ranked.append({**by_key.pop(r.key), **r.model_dump()})
        ranked.extend(rank_with_keywords(list(by_key.values()), cfg))  # any the model skipped
    return ranked


def cover_letters_with_llm(llm, jobs, profile):
    brief = [{k: j[k] for k in ("key", "title", "company", "location", "required_skills",
                                "matched_skills", "snippet")} for j in jobs]
    system = f"""Write a cover-letter draft for each job, for the candidate below to review and edit
before sending. 150-200 words, plain and specific: name the role and company, connect two or three
real items from the profile to what the job asks for, and close with a short call to action.
Use only facts from the profile - never invent experience, numbers or certifications. No salary talk.
Sign off as "K. Arunkumar".

<candidate_profile>
{profile}
</candidate_profile>"""
    plain = str.maketrans({"‐": "-", "‑": "-", "–": "-", "—": " - ",
                           "’": "'", "“": '"', "”": '"'})  # paste cleanly into forms
    letters = {}
    for start in range(0, len(brief), llm.letter_batch):
        try:
            result = llm(system, json.dumps(brief[start:start + llm.letter_batch], ensure_ascii=False),
                         Letters)
        except Exception as e:  # jobs without a letter get the template one
            print(f"{llm.name} cover letters failed on batch {start}: {e}")
            continue
        if result:
            letters.update({l.key: l.cover_letter.translate(plain) for l in result.letters})
    return letters


# ---------------------------------------------------------------- ranking (keywords fallback)

def pick_resume_version(text, cfg):
    scores = {name: sum(kw in text for kw in v["keywords"])
              for name, v in cfg["resume_versions"].items()}
    return max(scores, key=scores.get)


def rank_with_keywords(jobs, cfg):
    ranked = []
    role_words = [r.lower() for r in cfg["roles"]] + ["ml ", "data science", "analytics", "ai "]
    for j in jobs:
        text = j["snippet"].lower()
        matched = [s for s in cfg["skills"] if re.search(rf"\b{re.escape(s)}\b", text)]
        role_hit = any(w in text for w in role_words)
        title = (j["link_text"] or j["snippet"][:80]).lower()
        too_senior = re.search(r"\b(senior|sr\.?|staff|lead|principal|manager|architect|head|"
                               r"intern|internship|trainee)\b", title)
        where = (j.get("location") or text).lower()
        location_hit = any(loc.lower() in where for loc in cfg["locations"]) or "anywhere" in where
        exp = re.search(r"(\d+)\s*(?:-|to)\s*\d+\s*(?:yrs|years)", text)
        exp_ok = not exp or int(exp[1]) <= cfg["experience_years"]["reject_if_min_required_above"]
        score = min(100, 35 * role_hit + 20 * location_hit + 6 * len(matched) + 10 * exp_ok)
        salary = re.search(r"(?:₹|inr|rs\.?)\s?[\d.,]+\s*(?:-|to)?\s*[\d.,]*\s*(?:lpa|lakhs?|l)?",
                           text, re.I)
        ranked.append({
            **j,
            "title": j["link_text"] or j["snippet"][:80], "company": j.get("company") or "see link",
            "location": j.get("location") or
                        next((loc for loc in cfg["locations"] if loc.lower() in text), "see link"),
            "salary": salary[0] if salary else "Not disclosed",
            "experience_required": exp[0] if exp else "Not disclosed",
            "job_type": "-", "required_skills": matched, "matched_skills": matched,
            "missing_skills": [], "match_score": score,
            "priority": "High" if score >= 75 else "Medium" if score >= 55 else "Low",
            "resume_version": pick_resume_version(text, cfg),
            "likely_closed": any(w in text for w in ("no longer accepting", "expired", "closed")),
            "passes_filters": bool(role_hit and exp_ok and location_hit and not too_senior),
            "reason": f"Keyword match: {len(matched)} skills",
        })
    return ranked


def template_cover_letter(job, cfg):
    skills = ", ".join(job["matched_skills"][:4]) or "Python, machine learning and deployment"
    company = job["company"] if job["company"] not in ("-", "see link") else "[Company]"
    return f"""Dear Hiring Team at {company},

I am writing to apply for the {job['title']} role. I am an AI Engineer and Data Scientist with about
1.5 years of hands-on experience delivering machine learning and computer vision solutions for live
client projects, from data preparation and model development through deployment.

Your role calls for {skills}, which I use day to day. At Xplore IT Corp I build production-oriented
AI/ML solutions and deployment workflows with Docker, Kubernetes and CI/CD, and at Ether Infotech I
delivered end-to-end ML projects for multiple clients. My projects include an AI voice agent and an
LLM-powered web scraper.

I would welcome the chance to discuss how I can contribute to your team.

Regards,
K. Arunkumar
6374893968 | aruarun142004@gmail.com"""


# ---------------------------------------------------------------- report

def render_report(today, jobs, stats, cfg):
    def esc(v):
        return html.escape(str(v))

    rows = []
    for i, j in enumerate(jobs, 1):
        color = {"High": "#1a7f37", "Medium": "#9a6700"}.get(j["priority"], "#57606a")
        version = cfg["resume_versions"].get(j["resume_version"], {})
        headline = f"{esc(version.get('headline', ''))}<br>📎 {esc(Path(version.get('file', '')).name)}"
        rows.append(f"""
<tr style="border-top:1px solid #d0d7de;vertical-align:top">
  <td style="padding:8px">{i}</td>
  <td style="padding:8px"><b style="color:{color}">{j['match_score']}</b><br>
      <span style="color:{color};font-size:12px">{esc(j['priority'])}</span></td>
  <td style="padding:8px"><b>{esc(j['title'])}</b><br>{esc(j['company'])}<br>
      <span style="color:#57606a;font-size:12px">{esc(j['source'])}</span></td>
  <td style="padding:8px">{esc(j['location'])}<br>
      <span style="font-size:12px">Exp: {esc(j['experience_required'])}</span><br>
      <span style="font-size:12px">Salary: {esc(j['salary'])}</span></td>
  <td style="padding:8px;font-size:12px"><b>Have:</b> {esc(', '.join(j['matched_skills'][:8]) or '-')}<br>
      <b>Gap:</b> {esc(', '.join(j['missing_skills'][:6]) or '-')}<br>
      <i>{esc(j['reason'])}</i></td>
  <td style="padding:8px;font-size:12px"><b>{esc(j['resume_version'])}</b><br>{headline}</td>
  <td style="padding:8px"><a href="{esc(j['url'])}"
      style="background:#0969da;color:#fff;padding:6px 10px;border-radius:6px;text-decoration:none">Open</a></td>
</tr>""")

    table = (f"""<table style="border-collapse:collapse;width:100%;font-size:14px">
<tr style="background:#f6f8fa;text-align:left"><th style="padding:8px">#</th><th style="padding:8px">Score</th>
<th style="padding:8px">Role / Company</th><th style="padding:8px">Location / Exp / Salary</th>
<th style="padding:8px">Skills match</th><th style="padding:8px">Resume version</th><th style="padding:8px">Link</th></tr>
{''.join(rows)}</table>""" if jobs else
             "<p><b>No new strong-match jobs today.</b> Check that your LinkedIn / Naukri / Indeed job alerts "
             "are active and sending to this Gmail.</p>")

    return f"""<div style="font-family:Segoe UI,Arial,sans-serif;color:#1f2328;max-width:1100px">
<h2 style="margin-bottom:4px">Daily Job Digest — {today:%d %b %Y}</h2>
<p style="color:#57606a;margin-top:0">Alert emails read: {stats['emails']} · Google Jobs: {stats['google']} ·
Jobs found: {stats['found']} ·
New today: {stats['new']} · Dropped by filters/closed: {stats['dropped']} · Scoring: {stats['mode']}</p>
{table}
<p style="font-size:13px;color:#57606a;margin-top:20px">Cover-letter drafts are attached. Review and edit them
before use.<br><b>Nothing was applied automatically.</b> Open each link, confirm the job is still open, and
answer sensitive questions (salary, notice period, relocation) yourself.</p></div>"""


def letters_markdown(today, jobs, cfg):
    parts = [f"# Cover letter drafts — {today:%d %b %Y}\n"]
    for i, j in enumerate(jobs, 1):
        parts.append(f"\n## {i}. {j['title']} — {j['company']}\n{j['url']}\n"
                     f"Resume version: {j['resume_version']} "
                     f"({Path(cfg['resume_versions'].get(j['resume_version'], {}).get('file', '')).name})"
                     f"\n\n{j['cover_letter']}\n\n---")
    return "\n".join(parts)


def send_report(env, subject, html_body, attachment_name, attachment_text):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env["GMAIL_USER"]
    msg["To"] = env["REPORT_TO"]
    msg.set_content("Your email client does not show HTML. Open the attached report.")
    msg.add_alternative(html_body, subtype="html")
    msg.add_attachment(attachment_text.encode("utf-8"), maintype="text", subtype="markdown",
                       filename=attachment_name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(env["GMAIL_USER"], env["GMAIL_APP_PASSWORD"])
        smtp.send_message(msg)


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="save the report locally only; do not email or mark jobs as seen")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows console is cp1252

    env, cfg = load_env(args.dry_run), load_config()
    profile = (BASE / "profile.md").read_text(encoding="utf-8")
    today = dt.date.today()
    llm = claude_llm(env["ANTHROPIC_API_KEY"]) if env.get("ANTHROPIC_API_KEY") else \
        groq_llm(env["GROQ_API_KEY"]) if env.get("GROQ_API_KEY") else None

    messages = fetch_alert_emails(env, cfg) if env.get("GMAIL_APP_PASSWORD") else []
    found = {j["key"]: j for j in extract_jobs(messages)}
    google = fetch_google_jobs(env["SERPAPI_KEY"], cfg, today) if env.get("SERPAPI_KEY") else []
    print(f"Google Jobs: {len(google)} recent jobs")
    for j in google:
        found.setdefault(j["key"], j)  # prefer the alert-email copy when both have it
    found = list(found.values())
    seen = load_seen()
    new_jobs = [j for j in found if j["key"] not in seen]
    print(f"{len(messages)} alert emails, {len(found)} jobs, {len(new_jobs)} new")

    ranked = rank_with_llm(llm, new_jobs, cfg, profile) if llm and new_jobs \
        else rank_with_keywords(new_jobs, cfg)
    keep = [j for j in ranked if j["passes_filters"] and not j["likely_closed"]
            and j["match_score"] >= cfg["min_match_score"]]
    keep.sort(key=lambda j: j["match_score"], reverse=True)
    top, listed = [], set()
    for j in keep:  # portals often send the same posting under two links
        same = re.sub(r"\W+", " ", f"{j['title']} {j['company']} {j['location']}".lower()).strip()
        if same not in listed and len(top) < cfg["max_jobs_in_report"]:
            listed.add(same)
            top.append(j)

    letters = cover_letters_with_llm(llm, top, profile) if llm and top else {}
    for j in top:
        j["cover_letter"] = letters.get(j["key"]) or template_cover_letter(j, cfg)

    stats = {"emails": len(messages), "google": len(google), "found": len(found), "new": len(new_jobs),
             "dropped": len(ranked) - len(keep), "mode": llm.name if llm else "keywords"}
    report = render_report(today, top, stats, cfg)
    letters_md = letters_markdown(today, top, cfg)

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{today}.html").write_text(report, encoding="utf-8")
    (REPORTS / f"{today}-cover-letters.md").write_text(letters_md, encoding="utf-8")
    print(f"Report saved to {REPORTS / f'{today}.html'}")

    if args.dry_run:
        return
    high = sum(j["priority"] == "High" for j in top)
    send_report(env, f"Job Digest {today:%d %b}: {len(top)} matches ({high} high priority)",
                report, f"cover-letters-{today}.md", letters_md)
    seen.update({j["key"]: today.isoformat() for j in new_jobs})
    save_seen(seen)
    print(f"Report emailed to {env['REPORT_TO']}")


if __name__ == "__main__":
    main()
