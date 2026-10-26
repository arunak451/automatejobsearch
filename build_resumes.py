"""Builds the four tailored resume PDFs in resumes/.

Every version uses only facts from the original resume; versions differ in title, summary,
and the order of skills, experience bullets and projects. Edit the data below and re-run:
    python build_resumes.py
"""

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

OUT = Path(__file__).resolve().parent / "resumes"

NAME = "K. ARUNKUMAR"
CONTACT = ("Coimbatore, Tamil Nadu  |  6374893968  |  aruarun142004@gmail.com<br/>"
           '<link href="https://www.linkedin.com/in/arun-kumar-5516572a">linkedin.com/in/arun-kumar-5516572a</link>'
           '  |  <link href="https://github.com/arunak451">github.com/arunak451</link>')

SKILLS = {
    "prog": ("Programming and Web Development", "Python, SQL, HTML, CSS, JavaScript"),
    "ml": ("Machine Learning", "Scikit-learn, TensorFlow, Machine Learning, Deep Learning, NLP, Computer Vision, "
                               "YOLO, EDA, Statistical Analysis"),
    "genai": ("Generative AI", "LLM, Generative AI, RAG, LangChain, HuggingFace, OpenAI, Claude, Groq, AI Agents"),
    "ops": ("Deployment and MLOps", "Docker, Kubernetes, Terraform, Ansible, Linux, CI/CD, AWS, Flask, Django, "
                                    "Streamlit"),
    "auto": ("Automation and Integration", "n8n, Make, Workflow Automation, API Integration, AI Automation"),
    "data": ("Data and Visualization", "Power BI, Tableau, Excel, DAX, Matplotlib, Seaborn, Plotly"),
    "tools": ("Development Tools", "Git"),
}

XPLORE = {
    "cv": "Build production-oriented computer vision and AI/ML solutions for live use cases, taking projects from "
          "data preparation and model development through testing, deployment, and operational improvement.",
    "pipelines": "Develop and integrate machine learning pipelines, AI applications, and deployment workflows with "
                 "a focus on reliability, reproducibility, and production readiness.",
    "automation": "Build AI-powered workflow automations and API integrations using n8n and Make to connect data, "
                  "model, and business processes.",
    "ops": "Apply Linux, Docker, Kubernetes, Terraform, Ansible, and CI/CD practices to support scalable AI/ML "
           "deployments and consistent development-to-production workflows.",
    "teach": "Train and mentor learners in Data Science, Machine Learning, Generative AI, computer vision, and "
             "practical AI project development.",
}

PROJECTS = {
    "voice": ("AI Voice Agent", "Built an AI-powered voice agent combining speech-to-text, LLM-based dialogue "
                                "management, and text-to-speech for automated calling and support use cases."),
    "scraper": ("LLM-Powered Web Scraper", "Developed a web-scraping tool that extracts and structures data from "
                                           "unstructured web pages using natural-language prompts, adapting to "
                                           "changing page layouts without manual parsing rules."),
    "trading": ("AI-Powered Trading Assistant", "Built an AI assistant that analyzes market data, price trends, and "
                                                "technical indicators to generate data-driven trade signals and "
                                                "insights."),
    "digest": ("Daily AI News Digest for Gmail", "Created an automated pipeline that retrieves daily AI news, "
                                                 "summarizes content using an LLM, and delivers a concise digest to "
                                                 "Gmail."),
}

VERSIONS = {
    "AI / GenAI Engineer": {
        "file": "Arunkumar_AI_GenAI_Engineer.pdf",
        "title": "AI Engineer | Generative AI | Computer Vision",
        "summary": "AI Engineer with hands-on experience building production-oriented machine learning, computer "
                   "vision and Generative AI solutions for live client projects. Builds LLM applications, RAG "
                   "pipelines and AI agents with LangChain, HuggingFace, OpenAI, Claude and Groq, and connects them "
                   "to business processes through n8n, Make and API integrations. Covers the full AI lifecycle from "
                   "data preparation and model development to evaluation, deployment and system integration, with "
                   "Docker, Kubernetes and CI/CD for production readiness.",
        "skills": ["genai", "ml", "prog", "auto", "ops", "data", "tools"],
        "xplore": ["cv", "pipelines", "automation", "ops", "teach"],
        "projects": ["voice", "scraper", "digest", "trading"],
    },
    "Data Scientist / ML Engineer": {
        "file": "Arunkumar_Data_Scientist_ML_Engineer.pdf",
        "title": "Data Scientist | Machine Learning Engineer",
        "summary": "Data Scientist and Machine Learning Engineer with hands-on experience delivering end-to-end "
                   "machine learning solutions for multiple live client projects, covering data analysis, feature "
                   "preparation, model building, evaluation and deployment. Skilled in Python, SQL, Scikit-learn, "
                   "TensorFlow, NLP, computer vision and statistical analysis, with experience automating data "
                   "pipelines and deploying models through Flask, Streamlit, Docker and CI/CD.",
        "skills": ["ml", "prog", "data", "genai", "ops", "auto", "tools"],
        "xplore": ["cv", "pipelines", "ops", "automation", "teach"],
        "projects": ["trading", "scraper", "voice", "digest"],
    },
    "DevOps / MLOps Engineer": {
        "file": "Arunkumar_DevOps_MLOps_Engineer.pdf",
        "title": "DevOps Engineer | MLOps | AI Engineer",
        "summary": "DevOps and MLOps-focused engineer who applies Linux, Docker, Kubernetes, Terraform, Ansible and "
                   "CI/CD practices to support scalable AI/ML deployments and consistent development-to-production "
                   "workflows. Experienced in building and deploying machine learning pipelines and AI applications "
                   "for live use cases with a focus on reliability, reproducibility and production readiness, along "
                   "with workflow automation and API integration using n8n and Make.",
        "skills": ["ops", "auto", "prog", "tools", "ml", "genai", "data"],
        "xplore": ["ops", "pipelines", "automation", "cv", "teach"],
        "projects": ["digest", "voice", "scraper", "trading"],
    },
    "Data Analyst": {
        "file": "Arunkumar_Data_Analyst.pdf",
        "title": "Data Analyst | Data Scientist",
        "summary": "Data professional with hands-on experience in data analysis, EDA and statistical analysis for "
                   "live client projects. Skilled in SQL, Python, Excel, Power BI, DAX and Tableau for turning raw "
                   "data into dashboards and insights, with Matplotlib, Seaborn and Plotly for visualization. Built "
                   "automated data-preprocessing pipelines that reduced data-cleaning time by 40%, and applies "
                   "machine learning where prediction adds value.",
        "skills": ["data", "prog", "ml", "auto", "genai", "ops", "tools"],
        "xplore": ["pipelines", "automation", "cv", "teach", "ops"],
        "projects": ["trading", "digest", "scraper", "voice"],
    },
}

INK, ACCENT, MUTED = HexColor("#1f2328"), HexColor("#0b5394"), HexColor("#57606a")
S = {
    "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=TA_CENTER,
                           textColor=INK),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=11, leading=15, alignment=TA_CENTER,
                            textColor=ACCENT),
    "contact": ParagraphStyle("contact", fontName="Helvetica", fontSize=9, leading=12.5, alignment=TA_CENTER,
                              textColor=MUTED, linkUnderline=False),
    "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=ACCENT,
                        spaceBefore=7, spaceAfter=1),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.3, leading=12.2, textColor=INK),
    "role": ParagraphStyle("role", fontName="Helvetica-Bold", fontSize=9.6, leading=12.5, textColor=INK,
                           spaceBefore=3),
}


def section(story, heading):
    story.append(Paragraph(heading, S["h"]))
    story.append(HRFlowable(width="100%", thickness=0.7, color=ACCENT, spaceBefore=1, spaceAfter=4))


def bullets(items):
    return ListFlowable([ListItem(Paragraph(t, S["body"]), leftIndent=11, value="•") for t in items],
                        bulletType="bullet", bulletFontSize=8, leftIndent=11, spaceBefore=1)


def role(story, title, company, dates):
    story.append(Paragraph(f'{title} - {company} <font name="Helvetica-Oblique" color="#57606a">'
                           f'&nbsp;&nbsp;{dates}</font>', S["role"]))


def build(version, v):
    story = [Paragraph(NAME, S["name"]), Paragraph(v["title"], S["title"]), Paragraph(CONTACT, S["contact"])]

    section(story, "PROFESSIONAL SUMMARY")
    story.append(Paragraph(v["summary"], S["body"]))

    section(story, "TECHNICAL SKILLS")
    for key in v["skills"]:
        label, items = SKILLS[key]
        story.append(Paragraph(f"<b>{label}:</b> {items}", S["body"]))

    section(story, "PROFESSIONAL EXPERIENCE")
    role(story, "AI Engineer and Instructor", "Xplore IT Corp", "Mar 2026 - Present")
    story.append(bullets([XPLORE[k] for k in v["xplore"]]))
    role(story, "Data Scientist", "Ether Infotech", "May 2025 - Mar 2026")
    story.append(bullets([
        "Delivered end-to-end machine learning solutions for multiple live client projects, covering data "
        "analysis, feature preparation, model building, evaluation, and deployment.",
        "Led Data Science training for 200+ learners, achieving 95% learner satisfaction and 85% job placement "
        "for graduates through hands-on mentoring."]))
    role(story, "Machine Learning Intern", "Novitech", "Mar 2025 - Apr 2025")
    story.append(bullets([
        "Developed and deployed 3 machine learning models with 85% accuracy and automated data-preprocessing "
        "pipelines, reducing data-cleaning time by 40%."]))

    section(story, "SELECTED PROJECTS")
    story.append(bullets([f"<b>{PROJECTS[k][0]}:</b> {PROJECTS[k][1]}" for k in v["projects"]]))

    section(story, "EDUCATION")
    story.append(Paragraph("<b>Uptor - LMES Academy</b> - Diploma in Data Science &amp; Machine Learning", S["body"]))
    story.append(Paragraph("<b>P.A.C.R. Polytechnic</b> - Diploma in Textile Technology, 96% (2024)", S["body"]))

    section(story, "CERTIFICATIONS AND TRAINING")
    story.append(Paragraph("Data Visualization | Machine Learning with Scikit-learn | Python for Data Science | "
                           "SQL | Data Analytics", S["body"]))

    path = OUT / v["file"]
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm,
                      bottomMargin=12 * mm, title=f"K. Arunkumar - {version}", author="K. Arunkumar").build(story)
    return path


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, v in VERSIONS.items():
        print(build(name, v))
