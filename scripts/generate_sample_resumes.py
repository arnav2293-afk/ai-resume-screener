"""
Generate 10 FAKE one-page resume PDFs for testing the screening workflow.

All names, emails, phone numbers, colleges and projects are made up.
Emails use the reserved example.com domain so they can never reach a real inbox.

Fit for the AI Intern role (see prompts/job_description.md):
  - 3 strong  (Claude / n8n / Python / APIs + real automation projects)
  - 4 medium  (some Python or ML, little automation or LLM experience)
  - 3 weak    (unrelated background)

Usage:
    python scripts/generate_sample_resumes.py
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "sample_resumes"

CANDIDATES = [
    # ---------------- STRONG FIT ----------------
    {
        "file": "01_aarav_mehta.pdf",
        "name": "Aarav Mehta",
        "email": "aarav.mehta@example.com",
        "phone": "+91 90000 11101",
        "location": "Pune, Maharashtra",
        "summary": "Final-year CS student who builds AI automations. Shipped three "
        "n8n workflows that use the Claude API to triage emails and summarise documents.",
        "education": "B.Tech, Computer Science – Sunrise Institute of Technology, Pune (2022–2026), CGPA 8.7",
        "skills": "Python, REST APIs, JSON, Claude API (Anthropic SDK), prompt engineering, "
        "n8n, Zapier, Google Sheets API, Gmail API, webhooks, Git, FastAPI",
        "experience": [
            "AI Automation Intern, BrightLeaf Labs (May–Jul 2025): built an n8n workflow that "
            "reads support emails, classifies them with Claude and logs them to Google Sheets. "
            "Cut manual triage time by about 60%.",
        ],
        "projects": [
            "Invoice Extractor: n8n + Claude pulls vendor, amount and due date from PDF invoices "
            "into Sheets, with a JSON fallback parser for bad model output.",
            "Meeting Notes Bot: Python script that sends transcripts to Claude and posts "
            "3-line summaries to Slack via webhook.",
            "Zapier lead router: routes Typeform leads to a CRM based on an LLM score.",
        ],
        "extra": "Wrote two blog posts on structured JSON output from LLMs.",
    },
    {
        "file": "02_diya_krishnan.pdf",
        "name": "Diya Krishnan",
        "email": "diya.krishnan@example.com",
        "phone": "+91 90000 11102",
        "location": "Chennai, Tamil Nadu",
        "summary": "Data Science student focused on LLM apps and workflow automation with Make and Python.",
        "education": "B.E., Information Technology – Coastal Engineering College, Chennai (2022–2026), CGPA 8.9",
        "skills": "Python, pandas, Claude API, OpenAPI/REST, Make (Integromat), n8n, "
        "Google Workspace APIs, SQL, Git, Docker, Streamlit",
        "experience": [
            "Operations Automation Intern, Kaveri Retail (Dec 2024–Feb 2025): built Make scenarios "
            "that sync orders from Shopify to Google Sheets and email daily reports.",
        ],
        "projects": [
            "Resume Ranker: Streamlit app that scores resumes against a job description using Claude "
            "and returns JSON with a score and missing skills.",
            "Customer Feedback Classifier: n8n workflow + Claude tags reviews by sentiment and topic.",
            "API Health Checker: Python cron job that pings 20 endpoints and alerts via Telegram.",
        ],
        "extra": "Runner-up, college GenAI hackathon 2025.",
    },
    {
        "file": "03_kabir_singh.pdf",
        "name": "Kabir Singh",
        "email": "kabir.singh@example.com",
        "phone": "+91 90000 11103",
        "location": "Jaipur, Rajasthan",
        "summary": "Backend-leaning student who connects APIs and LLMs to automate small-business tasks.",
        "education": "BCA – Aravali College of Computer Applications, Jaipur (2023–2026), 82%",
        "skills": "Python, Flask, REST APIs, webhooks, Claude API, prompt design, n8n (self-hosted), "
        "Zapier, PostgreSQL, Git, Linux",
        "experience": [
            "Freelance Automation Developer (2024–present): built Zapier and n8n workflows for "
            "3 local businesses, including WhatsApp order alerts and auto-generated invoices.",
        ],
        "projects": [
            "Email-to-Task: n8n reads Gmail, Claude extracts action items as JSON, creates Trello cards.",
            "PDF Q&A CLI: Python tool that extracts PDF text with pypdf and answers questions with Claude.",
        ],
        "extra": "Self-hosts n8n on a small VPS with Docker.",
    },
    # ---------------- MEDIUM FIT ----------------
    {
        "file": "04_ananya_iyer.pdf",
        "name": "Ananya Iyer",
        "email": "ananya.iyer@example.com",
        "phone": "+91 90000 11104",
        "location": "Bengaluru, Karnataka",
        "summary": "ML student interested in NLP. Comfortable with Python and model training; new to automation tools.",
        "education": "B.Tech, AI & Data Science – Lakeview Institute, Bengaluru (2022–2026), CGPA 8.4",
        "skills": "Python, NumPy, scikit-learn, PyTorch, Hugging Face Transformers, SQL, Git",
        "experience": [
            "Research Assistant, college NLP lab (2024–2025): fine-tuned a BERT model for "
            "news headline classification.",
        ],
        "projects": [
            "Sentiment Analysis on Product Reviews (Hugging Face, 89% accuracy).",
            "Movie Recommender using collaborative filtering.",
        ],
        "extra": "Completed an online course on prompt engineering.",
    },
    {
        "file": "05_rohan_desai.pdf",
        "name": "Rohan Desai",
        "email": "rohan.desai@example.com",
        "phone": "+91 90000 11105",
        "location": "Ahmedabad, Gujarat",
        "summary": "Web developer who has started experimenting with LLM APIs in side projects.",
        "education": "B.E., Computer Engineering – Sabarmati Engineering College, Ahmedabad (2022–2026), CGPA 7.8",
        "skills": "JavaScript, React, Node.js, Express, REST APIs, MongoDB, basic Python, Git",
        "experience": [
            "Web Development Intern, PixelCraft Studio (Jun–Aug 2025): built React dashboards "
            "consuming internal REST APIs.",
        ],
        "projects": [
            "Chatbot widget: Node.js backend calling an LLM API for website FAQs.",
            "Expense Tracker MERN app.",
        ],
        "extra": "No experience with n8n, Make or Zapier yet.",
    },
    {
        "file": "06_meera_nair.pdf",
        "name": "Meera Nair",
        "email": "meera.nair@example.com",
        "phone": "+91 90000 11106",
        "location": "Kochi, Kerala",
        "summary": "Business analytics student who automates reports with spreadsheets and some Zapier.",
        "education": "BBA (Business Analytics) – Malabar School of Management, Kochi (2023–2026), 78%",
        "skills": "Excel, Google Sheets, Power BI, Zapier (basic), SQL basics, Python basics",
        "experience": [
            "Operations Intern, GreenCart Logistics (Jan–Mar 2025): set up a Zapier zap that "
            "copies form responses into Google Sheets and sends Slack alerts.",
        ],
        "projects": [
            "Sales dashboard in Power BI for a college fest.",
            "Python script that merges monthly CSV reports.",
        ],
        "extra": "Strong written communication; college newsletter editor.",
    },
    {
        "file": "07_arjun_reddy.pdf",
        "name": "Arjun Reddy",
        "email": "arjun.reddy@example.com",
        "phone": "+91 90000 11107",
        "location": "Hyderabad, Telangana",
        "summary": "Python developer with competitive programming background, curious about AI agents.",
        "education": "B.Tech, Computer Science – Deccan Institute of Engineering, Hyderabad (2022–2026), CGPA 8.1",
        "skills": "Python, C++, Data Structures, Django, REST APIs, Git, Linux",
        "experience": [
            "Backend Intern, CodeNest (May–Jul 2025): wrote Django REST endpoints and unit tests.",
        ],
        "projects": [
            "Telegram bot that fetches cricket scores from a public API.",
            "Web scraper for job listings with BeautifulSoup.",
        ],
        "extra": "Codeforces Specialist. Has not used an LLM API in a project yet.",
    },
    # ---------------- WEAK FIT ----------------
    {
        "file": "08_priya_sharma.pdf",
        "name": "Priya Sharma",
        "email": "priya.sharma@example.com",
        "phone": "+91 90000 11108",
        "location": "Lucknow, Uttar Pradesh",
        "summary": "Commerce graduate seeking a role in accounting and finance.",
        "education": "B.Com – Gomti College of Commerce, Lucknow (2022–2025), 74%",
        "skills": "Tally ERP, MS Excel, GST filing, bookkeeping, MS Word",
        "experience": [
            "Accounts Intern, Sharma & Associates (Jun–Dec 2024): prepared invoices and GST returns.",
        ],
        "projects": ["Study on working capital management of FMCG companies."],
        "extra": "Hindi and English.",
    },
    {
        "file": "09_vikram_patel.pdf",
        "name": "Vikram Patel",
        "email": "vikram.patel@example.com",
        "phone": "+91 90000 11109",
        "location": "Surat, Gujarat",
        "summary": "Mechanical engineering student interested in design and manufacturing.",
        "education": "B.E., Mechanical Engineering – Tapi Institute of Engineering, Surat (2022–2026), CGPA 7.2",
        "skills": "AutoCAD, SolidWorks, CATIA, MATLAB basics, MS Office",
        "experience": [
            "Summer Trainee, Narmada Auto Components (May–Jun 2025): assisted in quality inspection.",
        ],
        "projects": ["Design of a low-cost solar dryer.", "Gearbox CAD model in SolidWorks."],
        "extra": "NSS volunteer.",
    },
    {
        "file": "10_sneha_gupta.pdf",
        "name": "Sneha Gupta",
        "email": "sneha.gupta@example.com",
        "phone": "+91 90000 11110",
        "location": "Kolkata, West Bengal",
        "summary": "Creative graphic designer looking for a design internship.",
        "education": "B.A., Fine Arts – Hooghly College of Arts, Kolkata (2022–2025)",
        "skills": "Adobe Photoshop, Illustrator, Canva, Figma (basic), social media content",
        "experience": [
            "Freelance Designer (2023–present): posters and Instagram creatives for local cafes.",
        ],
        "projects": ["Brand identity for a college cultural fest."],
        "extra": "Bengali, Hindi, English.",
    },
]


def build_resume(candidate: dict, path: Path) -> None:
    styles = getSampleStyleSheet()
    name_style = ParagraphStyle("Name", parent=styles["Title"], fontSize=18, spaceAfter=2)
    contact_style = ParagraphStyle("Contact", parent=styles["Normal"], fontSize=9, alignment=1)
    heading = ParagraphStyle("H", parent=styles["Heading3"], fontSize=11, spaceBefore=8, spaceAfter=3)
    body = ParagraphStyle("B", parent=styles["Normal"], fontSize=9.5, leading=12.5)

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Resume - {candidate['name']}", author="Sample data (fake)",
    )
    story = [
        Paragraph(candidate["name"], name_style),
        Paragraph(
            f"{candidate['email']} &nbsp;|&nbsp; {candidate['phone']} &nbsp;|&nbsp; {candidate['location']}",
            contact_style,
        ),
        Spacer(1, 6),
        Paragraph("Summary", heading),
        Paragraph(candidate["summary"], body),
        Paragraph("Education", heading),
        Paragraph(candidate["education"], body),
        Paragraph("Skills", heading),
        Paragraph(candidate["skills"], body),
        Paragraph("Experience", heading),
        *[Paragraph(f"• {item}", body) for item in candidate["experience"]],
        Paragraph("Projects", heading),
        *[Paragraph(f"• {item}", body) for item in candidate["projects"]],
        Paragraph("Additional", heading),
        Paragraph(candidate["extra"], body),
    ]
    doc.build(story)


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    for candidate in CANDIDATES:
        out = OUTPUT_DIR / candidate["file"]
        build_resume(candidate, out)
        print(f"Created {out.relative_to(OUTPUT_DIR.parent)}")
    print(f"\nDone: {len(CANDIDATES)} fake resumes in {OUTPUT_DIR.name}/")


if __name__ == "__main__":
    main()
