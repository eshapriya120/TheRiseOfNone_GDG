import csv
import io
import json
import os
from datetime import datetime
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

try:
    from pyngrok import ngrok
except ImportError:
    ngrok = None

from flask import Flask, render_template, request, redirect, session, url_for, Response, abort, jsonify

app = Flask(__name__)
app.secret_key = "dev-secret-key"
CREDENTIALS_FILE = Path(__file__).resolve().parent / "credentials.csv"
STUDENT_DATA_FILE = Path(__file__).resolve().parent / "student_progress.csv"
FEEDBACK_DATA_FILE = Path(__file__).resolve().parent / "feedback_data.csv"
FEEDBACK_ANALYSIS_FILE = Path(__file__).resolve().parent / "feedback_analysis.csv"
PERFORMANCE_DATA_FILE = Path(__file__).resolve().parent / "performance_metrics.csv"
DRIVE_STATE_FILE = Path(__file__).resolve().parent / "drive_state.csv"
CONFIG_FILE = Path(__file__).resolve().parent / "secrets.toml"
TABLEAU_DASHBOARD_URL = "https://public.tableau.com/views/YourWorkbook/YourDashboard"


def load_credentials():
    credentials = {}
    if not CREDENTIALS_FILE.exists():
        return credentials

    with CREDENTIALS_FILE.open(newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            credentials[row["username"]] = {
                "password": row["password"],
                "role": row["role"],
                "department": row.get("department", ""),
                "name": row.get("name", row["username"]),
            }
    return credentials


def load_students():
    students = []
    if not STUDENT_DATA_FILE.exists():
        return students

    with STUDENT_DATA_FILE.open(newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            row["cgpa"] = float(row["cgpa"])
            row["applications"] = int(row["applications"])
            row["programming"] = int(row["programming"])
            row["dsa"] = int(row["dsa"])
            row["aptitude"] = int(row["aptitude"])
            row["communication"] = int(row["communication"])
            students.append(row)
    return students


def get_student(username):
    for student in load_students():
        if student["username"] == username:
            return student
    return None


def get_students_by_department(department):
    if department == "ALL":
        return load_students()
    return [s for s in load_students() if s["department"] == department]


def load_feedback_count():
    if not FEEDBACK_DATA_FILE.exists():
        return 0

    with FEEDBACK_DATA_FILE.open(newline="", encoding="utf-8") as csvfile:
        return sum(1 for _ in csv.DictReader(csvfile))


def load_performance_metrics():
    if not PERFORMANCE_DATA_FILE.exists():
        return []

    with PERFORMANCE_DATA_FILE.open(newline="", encoding="utf-8") as csvfile:
        return list(csv.DictReader(csvfile))


def append_performance_data(uploaded_file):
    text_stream = io.TextIOWrapper(uploaded_file.stream, encoding="utf-8", newline="")
    reader = csv.DictReader(text_stream)
    uploaded_rows = list(reader)
    if not uploaded_rows:
        return 0

    existing_rows = []
    existing_fieldnames = []
    if PERFORMANCE_DATA_FILE.exists():
        with PERFORMANCE_DATA_FILE.open(newline="", encoding="utf-8") as csvfile:
            existing = list(csv.DictReader(csvfile))
            if existing:
                existing_fieldnames = list(existing[0].keys())
                existing_rows = existing

    fieldnames = list(dict.fromkeys((existing_fieldnames or []) + (reader.fieldnames or [])))
    with PERFORMANCE_DATA_FILE.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in existing_rows:
            writer.writerow({fn: row.get(fn, "") for fn in fieldnames})
        for row in uploaded_rows:
            writer.writerow({fn: row.get(fn, "") for fn in fieldnames})

    return len(uploaded_rows)


def load_config():
    if not CONFIG_FILE.exists():
        return {}

    with CONFIG_FILE.open("rb") as config_file:
        return tomllib.load(config_file)


def load_drive_state():
    if not DRIVE_STATE_FILE.exists():
        return []

    with DRIVE_STATE_FILE.open(newline="", encoding="utf-8") as csvfile:
        return list(csv.DictReader(csvfile))


def get_drive_state_for_student(username):
    for row in load_drive_state():
        if row.get("student_username") == username:
            return row
    return None


def save_drive_state(rows):
    fieldnames = [
        "student_username",
        "drive_name",
        "attendance",
        "feedback_submitted",
        "placement_status",
        "permission_requested",
        "permission_granted",
        "permission_reason",
        "updated_at",
    ]
    with DRIVE_STATE_FILE.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({fn: row.get(fn, "") for fn in fieldnames})


def append_drive_state_entry(entry):
    rows = load_drive_state()
    existing_index = next((idx for idx, row in enumerate(rows) if row.get("student_username") == entry.get("student_username")), None)
    if existing_index is not None:
        rows[existing_index] = entry
    else:
        rows.append(entry)
    save_drive_state(rows)
    return entry


def process_google_form_payload(payload):
    if payload is None:
        payload = {}
    if isinstance(payload, dict) and "response" in payload and isinstance(payload["response"], dict):
        payload = payload["response"]

    normalized = {}
    normalized["student_username"] = (
        payload.get("student_username")
        or payload.get("username")
        or payload.get("email")
        or payload.get("student_id")
        or payload.get("roll_no")
        or ""
    ).strip()
    normalized["drive_name"] = (payload.get("drive_name") or payload.get("drive") or "Tech Drive 2026").strip()
    normalized["attendance"] = (payload.get("attendance") or payload.get("attended") or "unknown").strip().lower()
    normalized["feedback_submitted"] = (payload.get("feedback_submitted") or payload.get("submitted_feedback") or "unknown").strip().lower()
    normalized["placement_status"] = (payload.get("placement_status") or payload.get("placed") or "not_placed").strip().lower()
    normalized["permission_requested"] = "no"
    normalized["permission_granted"] = "no"
    normalized["permission_reason"] = payload.get("permission_reason") or ""
    normalized["updated_at"] = datetime.utcnow().isoformat() + "Z"

    if normalized["placement_status"] == "true":
        normalized["placement_status"] = "placed"
    elif normalized["placement_status"] == "false":
        normalized["placement_status"] = "not_placed"

    entry = append_drive_state_entry(normalized)
    return {"ok": True, "entry": entry}


def evaluate_drive_eligibility(student, previous_state):
    placement_status = (student.get("status") or "").strip().lower()
    if placement_status == "placed":
        return {"eligible": False, "decision": "placed", "requires_permission": False, "reason": "Student is already placed."}

    if not previous_state:
        return {"eligible": True, "decision": "eligible_default", "requires_permission": False, "reason": "No prior drive record found; allowed to participate by default."}

    attendance = (previous_state.get("attendance") or "").strip().lower()
    feedback = (previous_state.get("feedback_submitted") or "").strip().lower()
    previous_placement = (previous_state.get("placement_status") or "").strip().lower()

<<<<<<< HEAD
    if attendance == "yes" and feedback == "yes" and previous_placement != "placed":
        return {"eligible": True, "decision": "eligible", "requires_permission": False, "reason": "Previous attendance and feedback were completed."}

    if attendance == "no" or feedback == "no":
        if previous_placement == "placed":
            return {"eligible": False, "decision": "not_eligible_placed", "requires_permission": False, "reason": "Student is already placed."}
=======
    if previous_placement == "placed":
        return {"eligible": False, "decision": "placed", "requires_permission": False, "reason": "Student is already placed."}

    if attendance == "yes" and feedback == "yes":
        return {"eligible": True, "decision": "eligible", "requires_permission": False, "reason": "Previous attendance and feedback were completed."}

    if attendance == "no" or feedback == "no":
>>>>>>> b993e77a0a14b8669f178d6cd8d4122ba4e44b3a
        return {"eligible": False, "decision": "permission_required", "requires_permission": True, "reason": "Attendance or feedback was incomplete; coordinator permission is required."}

    return {"eligible": False, "decision": "not_eligible", "requires_permission": False, "reason": "Previous drive state does not allow participation."}


def get_gemini_api_key():
    config = load_config()
    return config.get("google", {}).get("gemini_api_key")


def get_tableau_dashboard_url():
    config = load_config()
    return config.get("tableau_dashboard_url") or TABLEAU_DASHBOARD_URL


def init_gemini_client():
    api_key = get_gemini_api_key()
    if not api_key:
        return None

    try:
        import generativeai.gemini as gemini_lib
    except ModuleNotFoundError:
        return None

    if hasattr(gemini_lib, "configure"):
        gemini_lib.configure(api_key=api_key)
        return gemini_lib

    if hasattr(gemini_lib, "Gemini"):
        return gemini_lib.Gemini(api_key=api_key)

    return gemini_lib


def summarize_feedback_for_gemini():
    gemini = init_gemini_client()
    if not gemini:
        return None

    feedback_rows = load_feedback_rows()
    analysis_rows = load_feedback_analysis_rows()

    performance_rows = load_performance_metrics()
    prompt = (
        "You are a placement preparation analyst. Use the student feedback and performance metrics to build a detailed training plan. "
        "Classify companies into Product-based, Service-based, and General/Other categories when possible, and recommend the topics students must cover for each category. "
        "Also provide company-specific preparation guidance for named companies, and identify generic training topics that all students should study.\n\n"
        "Data sources:\n"
        "- Feedback analysis rows with company_name, department, category, rating, feedback_text, and role_applied.\n"
        "- Performance metrics rows with student IDs and skill/assessment scores, if available.\n\n"
        "Use the following feedback rows as examples:\n"
    )
    for row in analysis_rows[:5]:
        company = row.get("company_name") or row.get("department") or "Unknown"
        role = row.get("role_applied") or "Unknown role"
        prompt += f"- Company: {company}, Role: {role}, Category: {row.get('category', '')}, Rating: {row.get('rating', '')}, Feedback: {row.get('feedback_text', '')[:120]}\n"

    if performance_rows:
        prompt += "\nPerformance metrics are also available for some students. Include these metrics when suggesting strengths and weaknesses.\n"
        example_metrics = performance_rows[:3]
        for perf in example_metrics:
            prompt += f"- Metrics: {perf}\n"

    prompt += (
        "\nAnswer with:\n"
        "1. Generic training topics for all students.\n"
        "2. Product-based company preparation topics.\n"
        "3. Service-based company preparation topics.\n"
        "4. General/other company preparation topics.\n"
        "5. Company-specific training recommendations for each named company.\n"
        "6. A short student planner summary.\n"
        "Keep the response structured and actionable."
    )

    try:
        if hasattr(gemini, "generate"):
            response = gemini.generate(prompt)
            return getattr(response, "text", str(response))
        if hasattr(gemini, "chat"):
            response = gemini.chat(prompt)
            return getattr(response, "text", str(response))
    except Exception:
        return None

    return None


def normalize_rating(value):
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        text = str(value).strip().lower()
        mapping = {
            "excellent": 5,
            "very good": 4,
            "good": 4,
            "fair": 3,
            "average": 3,
            "poor": 2,
            "bad": 1,
        }
        return mapping.get(text, None)


def build_feedback_planner_insights():
    analysis_rows = load_feedback_analysis_rows()
    if not analysis_rows:
        return {
            "summary_text": "No feedback analysis data is available yet. Upload a feedback CSV first.",
            "recommendations": [
                "Upload a mock student feedback CSV to generate analysis.",
                "Once feedback appears, this page will show trends and planner suggestions.",
            ],
            "department_counts": {},
            "category_counts": {},
            "top_snippets": [],
        }

    department_counts = {}
    category_counts = {}
    ratings = []
    snippet_candidates = []
    weakness_terms = ["communication", "interview", "technical", "confidence", "coding", "presentation"]
    weakness_scores = {term: 0 for term in weakness_terms}

    for row in analysis_rows:
        dept = (row.get("department") or "Unknown").strip() or "Unknown"
        category = (row.get("category") or "General").strip() or "General"
        department_counts[dept] = department_counts.get(dept, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1

        rating = normalize_rating(row.get("rating"))
        if rating is not None:
            ratings.append(rating)

        feedback_text = (row.get("feedback_text") or "").strip()
        if feedback_text:
            if len(snippet_candidates) < 5:
                snippet_candidates.append(feedback_text)
            lower = feedback_text.lower()
            for term in weakness_terms:
                if term in lower:
                    weakness_scores[term] += 1

    average_rating = round(sum(ratings) / len(ratings), 1) if ratings else None
    ordered_departments = sorted(department_counts.items(), key=lambda x: x[1], reverse=True)
    ordered_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
    top_weaknesses = [term for term, score in sorted(weakness_scores.items(), key=lambda x: x[1], reverse=True) if score > 0][:4]

    summary_lines = [
        f"Collected {len(analysis_rows)} feedback entries for analysis.",
    ]
    if average_rating is not None:
        summary_lines.append(f"Average feedback rating is {average_rating} out of 5.")
    if ordered_departments:
        summary_lines.append(f"Most active departments: {', '.join([dept for dept, _ in ordered_departments[:3]])}.")
    if ordered_categories:
        summary_lines.append(f"Top feedback categories: {', '.join([cat for cat, _ in ordered_categories[:3]])}.")
    if top_weaknesses:
        summary_lines.append(f"Common student challenges include {', '.join(top_weaknesses)}.")

    recommendations = []
    if average_rating is None or average_rating < 3.5:
        recommendations.append("Focus on interview, communication, and confidence-building workshops.")
    if "technical" in top_weaknesses or "coding" in top_weaknesses:
        recommendations.append("Add technology-focused practice sessions and code mock tests.")
    if "communication" in top_weaknesses or "presentation" in top_weaknesses:
        recommendations.append("Provide presentation skills and group discussion support.")
    if not recommendations:
        recommendations.append("Continue to reinforce strengths while tracking progress in future feedback uploads.")

    planner = [
        "Review the top feedback trends by department and category.",
        "Assign targeted student coaching based on the weakest areas from the latest CSV data.",
        "Use average rubric scores to plan monthly workshops for the most common challenges.",
    ]

    return {
        "summary_text": " ".join(summary_lines),
        "recommendations": recommendations,
        "planner": planner,
        "department_counts": ordered_departments,
        "category_counts": ordered_categories,
        "top_snippets": snippet_candidates,
    }


def get_ai_analysis_summary():
    gemini_result = summarize_feedback_for_gemini()
    if gemini_result:
        return gemini_result

    insights = build_feedback_planner_insights()
    return insights["summary_text"]


def load_feedback_rows():
    if not FEEDBACK_DATA_FILE.exists():
        return []

    with FEEDBACK_DATA_FILE.open(newline="", encoding="utf-8") as csvfile:
        return list(csv.DictReader(csvfile))


def load_feedback_analysis_rows():
    if not FEEDBACK_ANALYSIS_FILE.exists():
        return []

    with FEEDBACK_ANALYSIS_FILE.open(newline="", encoding="utf-8") as csvfile:
        return list(csv.DictReader(csvfile))


def extract_feedback_analysis_fields(row, source_name=None):
    student_name = row.get("student_name") or row.get("name") or row.get("full_name") or row.get("student") or ""
    student_id = row.get("register_no") or row.get("student_id") or row.get("id") or ""
    department = row.get("department") or row.get("dept") or ""
    company_name = row.get("company_name") or row.get("company") or ""
    role_applied = row.get("role_applied") or row.get("role") or ""
    round_name = row.get("round_name") or row.get("round") or ""
    rating = row.get("rating") or row.get("feedback_rating") or row.get("score") or ""
    feedback_text = row.get("feedback") or row.get("comments") or row.get("suggestions") or row.get("response") or ""
    category = row.get("category") or row.get("topic") or ""
    uploaded_at = datetime.utcnow().isoformat() + "Z"
    raw_data = json.dumps(row, ensure_ascii=False)

    return {
        "uploaded_at": uploaded_at,
        "source_file": source_name or "",
        "student_name": student_name,
        "student_id": student_id,
        "department": department,
        "company_name": company_name,
        "role_applied": role_applied,
        "round_name": round_name,
        "rating": rating,
        "category": category,
        "feedback_text": feedback_text,
        "raw_data": raw_data,
    }


def append_feedback_data(uploaded_file):
    text_stream = io.TextIOWrapper(uploaded_file.stream, encoding="utf-8", newline="")
    reader = csv.DictReader(text_stream)
    uploaded_rows = list(reader)
    if not uploaded_rows:
        return 0

    existing_rows = []
    existing_fieldnames = []
    if FEEDBACK_DATA_FILE.exists():
        with FEEDBACK_DATA_FILE.open(newline="", encoding="utf-8") as csvfile:
            existing = list(csv.DictReader(csvfile))
            if existing:
                existing_fieldnames = list(existing[0].keys())
                existing_rows = existing

    fieldnames = list(dict.fromkeys((existing_fieldnames or []) + (reader.fieldnames or [])))
    with FEEDBACK_DATA_FILE.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in existing_rows:
            writer.writerow({fn: row.get(fn, "") for fn in fieldnames})
        for row in uploaded_rows:
            writer.writerow({fn: row.get(fn, "") for fn in fieldnames})

    append_feedback_analysis(uploaded_rows, uploaded_file.filename)
    return len(uploaded_rows)


def append_feedback_analysis(rows, source_name=None):
    analysis_fieldnames = [
        "uploaded_at",
        "source_file",
        "student_name",
        "student_id",
        "department",
        "company_name",
        "role_applied",
        "round_name",
        "rating",
        "category",
        "feedback_text",
        "raw_data",
    ]

    existing_analysis = []
    if FEEDBACK_ANALYSIS_FILE.exists():
        with FEEDBACK_ANALYSIS_FILE.open(newline="", encoding="utf-8") as csvfile:
            existing_analysis = list(csv.DictReader(csvfile))

    with FEEDBACK_ANALYSIS_FILE.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=analysis_fieldnames)
        writer.writeheader()
        for row in existing_analysis:
            writer.writerow({fn: row.get(fn, "") for fn in analysis_fieldnames})
        for row in rows:
            analysis_row = extract_feedback_analysis_fields(row, source_name)
            writer.writerow(analysis_row)

    return len(rows)


def compute_student_stats(student):
    scores = [student["programming"], student["dsa"], student["aptitude"], student["communication"]]
    readiness = sum(scores) // len(scores)
    skills_completed = sum(1 for value in scores if value >= 70)
    tests_completed = sum(1 for value in scores if value >= 50)
    eligible_drives = 3 if student["cgpa"] >= 8.0 else 2
    return {
        "readiness": readiness,
        "skills_completed": skills_completed,
        "tests_completed": tests_completed,
        "eligible_drives": eligible_drives,
    }


def compute_staff_summary(students):
    total = len(students)
    placed = sum(1 for s in students if s["status"] == "Placed")
    in_process = sum(1 for s in students if s["status"] == "In Process")
    not_placed = total - placed - in_process
    department_counts = {"CSE": 0, "IT": 0, "EEE": 0}
    department_rates = {"CSE": 0, "IT": 0, "EEE": 0}

    for student in students:
        department = student["department"]
        department_counts.setdefault(department, 0)
        department_counts[department] += 1

    for dept in ["CSE", "IT", "EEE"]:
        dept_students = [s for s in students if s["department"] == dept]
        if dept_students:
            dept_placed = sum(1 for s in dept_students if s["status"] == "Placed")
            department_rates[dept] = int((dept_placed / len(dept_students)) * 100)

    placement_rate = int((placed / total) * 100) if total else 0
    return {
        "total_students": total,
        "placed": placed,
        "in_process": in_process,
        "not_placed": not_placed,
        "placement_rate": placement_rate,
        "department_counts": department_counts,
        "department_rates": department_rates,
    }


@app.route("/")
def home():
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    credentials = load_credentials()
    user = credentials.get(username)

    if username == "team01" and password == "team123":
        user = {
            "password": "team123",
            "role": "student",
            "department": "CSE",
            "name": "Team Member",
        }

    if user and user["password"] == password:
        session["username"] = username
        session["role"] = user["role"]
        session["department"] = user["department"]
        session["name"] = user["name"]

        if user["role"] == "student":
            return redirect(url_for("student"))
        return redirect(url_for("staff"))

    return render_template("login.html", error="Invalid Username or Password")


@app.route("/student")
def student():
    if "username" not in session or session.get("role") != "student":
        return redirect(url_for("home"))

    student_data = get_student(session["username"])
    if not student_data:
        return redirect(url_for("home"))

    stats = compute_student_stats(student_data)
    progress_items = [
        {"label": "Programming", "value": student_data["programming"]},
        {"label": "DSA", "value": student_data["dsa"]},
        {"label": "Aptitude", "value": student_data["aptitude"]},
        {"label": "Communication", "value": student_data["communication"]},
    ]

    drive_state = get_drive_state_for_student(session["username"])
    eligibility = evaluate_drive_eligibility(student_data, drive_state)
    upcoming_drive = {
        "name": "Tech Drive 2026",
        "message": "Students can opt in for the next drive once their previous-drive status is reviewed.",
    }

    return render_template(
        "student.html",
        student=student_data,
        stats=stats,
        progress_items=progress_items,
        drive_state=drive_state,
        drive_eligibility=eligibility,
        upcoming_drive=upcoming_drive,
    )


@app.route("/student/drive-update", methods=["POST"])
def student_drive_update():
    if "username" not in session or session.get("role") != "student":
        return redirect(url_for("home"))

    student_data = get_student(session["username"])
    if not student_data:
        return redirect(url_for("home"))

    attendance = request.form.get("attendance", "").strip().lower()
    feedback_submitted = request.form.get("feedback_submitted", "").strip().lower()
    placement_status = request.form.get("placement_status", "").strip().lower()
    permission_reason = request.form.get("permission_reason", "").strip()

    entry = {
        "student_username": session["username"],
        "drive_name": request.form.get("drive_name", "Tech Drive 2026"),
        "attendance": attendance or "unknown",
        "feedback_submitted": feedback_submitted or "unknown",
        "placement_status": placement_status or "not_placed",
        "permission_requested": "yes" if request.form.get("permission_requested") == "on" else "no",
        "permission_granted": "no",
        "permission_reason": permission_reason,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    append_drive_state_entry(entry)
    return redirect(url_for("student"))


@app.route("/staff")
def staff():
    if "username" not in session or session.get("role") not in ["staff", "coordinator"]:
        return redirect(url_for("home"))

    credentials = load_credentials()
    user = credentials.get(session["username"])
    if not user:
        return redirect(url_for("home"))

    if user["role"] == "coordinator":
        students = get_students_by_department("ALL")
        export_url = url_for("download_all")
        department_label = "All Departments"
        feedback_count = load_feedback_count()
        performance_count = len(load_performance_metrics())
    else:
        department = user["department"]
        students = get_students_by_department(department)
        export_url = url_for("download_department", department=department)
        department_label = department
        feedback_count = 0
        performance_count = 0

    summary = compute_staff_summary(students)
    drive_state_rows = load_drive_state()
    return render_template(
        "staff.html",
        staff=user,
        students=students,
        summary=summary,
        export_url=export_url,
        department_label=department_label,
        feedback_count=feedback_count,
        performance_count=performance_count,
        drive_state_rows=drive_state_rows,
        is_coordinator=(user["role"] == "coordinator"),
    )


@app.route("/coordinator/drive-action", methods=["POST"])
def coordinator_drive_action():
    if "username" not in session or session.get("role") != "coordinator":
        return redirect(url_for("home"))

    student_username = request.form.get("student_username", "").strip()
    action = request.form.get("action", "").strip().lower()
    rows = load_drive_state()
    for row in rows:
        if row.get("student_username") == student_username:
            if action == "grant":
                row["permission_granted"] = "yes"
                row["permission_reason"] = row.get("permission_reason") or "Coordinator approved access"
            elif action == "deny":
                row["permission_granted"] = "no"
                row["permission_reason"] = row.get("permission_reason") or "Coordinator denied access"
            break
    save_drive_state(rows)
    return redirect(url_for("staff"))


@app.route("/analysis")
def analysis():
    if "username" not in session or session.get("role") not in ["staff", "coordinator"]:
        return redirect(url_for("home"))

    credentials = load_credentials()
    user = credentials.get(session["username"])
    if not user:
        return redirect(url_for("home"))

    analysis_data = build_feedback_planner_insights()
    ai_summary = summarize_feedback_for_gemini() or analysis_data["summary_text"]

    return render_template(
        "analysis.html",
        staff=user,
        analysis=analysis_data,
        ai_summary=ai_summary,
        department_label="All Departments" if user["role"] == "coordinator" else user["department"],
        is_coordinator=(user["role"] == "coordinator"),
    )


@app.route("/google-form-webhook", methods=["POST"])
def google_form_webhook():
    payload = request.get_json(silent=True) or request.form.to_dict(flat=True) or {}
    result = process_google_form_payload(payload)
    return jsonify(result), 200


@app.route("/tableau-dashboard")
def tableau_dashboard():
    if "username" not in session or session.get("role") not in ["staff", "coordinator"]:
        return redirect(url_for("home"))

    credentials = load_credentials()
    user = credentials.get(session["username"])
    if not user:
        return redirect(url_for("home"))

    tableau_url = get_tableau_dashboard_url()
    return render_template(
        "tableau_dashboard.html",
        staff=user,
        tableau_url=tableau_url,
        department_label="All Departments" if user["role"] == "coordinator" else user["department"],
        is_coordinator=(user["role"] == "coordinator"),
    )


@app.route("/feedback/upload", methods=["POST"])
def upload_feedback():
    if "username" not in session or session.get("role") != "coordinator":
        return redirect(url_for("home"))

    feedback_file = request.files.get("feedback_file")
    if not feedback_file or not feedback_file.filename.lower().endswith(".csv"):
        return redirect(url_for("staff"))

    append_feedback_data(feedback_file)
    return redirect(url_for("staff"))


@app.route("/performance/upload", methods=["POST"])
def upload_performance():
    if "username" not in session or session.get("role") != "coordinator":
        return redirect(url_for("home"))

    perf_file = request.files.get("performance_file")
    if not perf_file or not perf_file.filename.lower().endswith(".csv"):
        return redirect(url_for("staff"))

    append_performance_data(perf_file)
    return redirect(url_for("staff"))


@app.route("/download/<department>")
def download_department(department):
    if "username" not in session or session.get("role") not in ["staff", "coordinator"]:
        return redirect(url_for("home"))

    if session.get("role") == "staff" and session.get("department") != department:
        abort(403)

    students = get_students_by_department(department)
    if not students:
        abort(404)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "username",
        "full_name",
        "register_no",
        "department",
        "teacher",
        "cgpa",
        "applications",
        "status",
        "programming",
        "dsa",
        "aptitude",
        "communication",
    ])
    for student_item in students:
        writer.writerow([
            student_item["username"],
            student_item["full_name"],
            student_item["register_no"],
            student_item["department"],
            student_item["teacher"],
            student_item["cgpa"],
            student_item["applications"],
            student_item["status"],
            student_item["programming"],
            student_item["dsa"],
            student_item["aptitude"],
            student_item["communication"],
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={department.lower()}_progress.csv"},
    )


@app.route("/download/all")
def download_all():
    if "username" not in session or session.get("role") != "coordinator":
        return redirect(url_for("home"))

    students = get_students_by_department("ALL")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "username",
        "full_name",
        "register_no",
        "department",
        "teacher",
        "cgpa",
        "applications",
        "status",
        "programming",
        "dsa",
        "aptitude",
        "communication",
    ])
    for student_item in students:
        writer.writerow([
            student_item["username"],
            student_item["full_name"],
            student_item["register_no"],
            student_item["department"],
            student_item["teacher"],
            student_item["cgpa"],
            student_item["applications"],
            student_item["status"],
            student_item["programming"],
            student_item["dsa"],
            student_item["aptitude"],
            student_item["communication"],
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=all_departments_progress.csv"},
    )


def start_ngrok(port=5000):
    if not ngrok:
        print("pyngrok is not installed; skipping ngrok tunnel.")
        return None

    try:
        tunnel = ngrok.connect(port, "http")
        public_url = tunnel.public_url
        print(f"* ngrok tunnel started at: {public_url}")
        print(f"* Use this public URL for Apps Script: {public_url}/google-form-webhook")
        return public_url
    except Exception as exc:
        print(f"Could not start ngrok tunnel: {exc}")
        return None


if __name__ == "__main__":
    port = 5000
    public_url = start_ngrok(port)
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)