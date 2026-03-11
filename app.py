import requests
import os
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from bs4 import BeautifulSoup
import secrets
import time
import re
import io

try:
    import fitz  # PyMuPDF
    from PIL import Image
except ImportError:
    fitz = None
    Image = None
    print("Warning: PyMuPDF or Pillow is not installed. Auto-compression disabled.")

app = Flask(__name__)
CORS(app)

BASE = "https://samvidha.iare.ac.in"
LOGIN_URL = BASE + "/pages/login/checkUser.php"

TOKENS = {}
SESSIONS = {}

def login_session(username, password):
    session = requests.Session()
    headers = {
        "Host": "samvidha.iare.ac.in",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": BASE,
        "Referer": BASE + "/",
        "X-Requested-With": "XMLHttpRequest",
    }
    payload = {"username": username, "password": password}
    try:
        res = session.post(LOGIN_URL, data=payload, headers=headers, timeout=20)
        j = res.json()
        if j.get("status") == "1":
            return session, None
        return None, "invalid_credentials"
    except Exception as e:
        return None, "network_error"

def scrape_attendance(session):
    try:
        r = session.get(BASE + "/home?action=stud_att_STD", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        attendance_data = []
        for table in soup.find_all("table"):
            if "Course Name" in table.get_text() and "Attendance %" in table.get_text():
                for tr in table.find_all("tr"):
                    cols = tr.find_all("td")
                    if len(cols) >= 7 and cols[0].get_text(strip=True).isdigit():
                        attendance_data.append({
                            "Subject": cols[2].get_text(strip=True), 
                            "Course Code": cols[1].get_text(strip=True),
                            "Conducted": cols[-4].get_text(strip=True),
                            "Attended": cols[-3].get_text(strip=True),
                            "Attendance %": cols[-2].get_text(strip=True),
                            "Status": cols[-1].get_text(strip=True) 
                        })
                break
        return attendance_data
    except Exception:
        return []

def scrape_midmarks(session):
    try:
        r = session.get(BASE + "/home?action=cie_marks_ug", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.find_all("tr")
        theory_data = []
        lab_data = []
        current_mode = None 
        current_sem = "Current Semester"

        for row in rows:
            text = row.get_text(strip=True).lower()
            if "semester -" in text:
                for cell in row.find_all(["th", "td"]):
                    if "semester -" in cell.get_text(strip=True).lower():
                        current_sem = cell.get_text(strip=True)
                        break
                        
            if "continuous internal assessment marks (theory)" in text:
                current_mode = "theory"
                continue
            elif "laboratory marks (practical)" in text or "seminar marks" in text:
                current_mode = "lab"
                continue
                
            cols = row.find_all("td")
            if len(cols) >= 10 and current_mode == "theory" and cols[0].get_text(strip=True).isdigit():
                theory_data.append({
                    "Semester": current_sem, "Course Name": cols[2].get_text(strip=True),
                    "CIE-I": cols[3].get_text(strip=True), "AAT:I-I": cols[4].get_text(strip=True),
                    "AAT:I-II": cols[5].get_text(strip=True), "CIE-II": cols[6].get_text(strip=True),
                    "AAT:II-I": cols[7].get_text(strip=True), "AAT:II-II": cols[8].get_text(strip=True),
                    "Total Marks": cols[-1].get_text(strip=True)
                })
            elif len(cols) >= 5 and current_mode == "lab" and cols[0].get_text(strip=True).isdigit():
                week_marks = [cols[i].get_text(strip=True) for i in range(3, len(cols) - 2) if cols[i].get_text(strip=True)]
                lab_data.append({
                    "Semester": current_sem, "Course Name": cols[2].get_text(strip=True),
                    "Weeks": week_marks, "Marks": cols[-1].get_text(strip=True)
                })
        return {"theory": theory_data, "laboratory": lab_data}
    except Exception:
        return {"theory": [], "laboratory": []}

def scrape_profile(session, username):
    try:
        r = session.get(BASE + "/home?action=profile", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        profile = {"Header": {"Roll Number": username.upper()}, "Sections": {}, "Documents": {}}
        
        header_card = soup.find("div", class_=lambda c: c and any(x in c.lower() for x in ['profile', 'user-info', 'card-body', 'panel-body']))
        if not header_card: header_card = soup
        name = header_card.find(["h3", "h4", "h5", "strong"])
        if name: profile["Header"]["Full Name"] = name.get_text(strip=True)
        branch = header_card.find(["h5", "p"])
        if branch: profile["Header"]["Department"] = branch.get_text(strip=True)

        processed_trs = set()
        inner_tables = [t for t in soup.find_all("table") if not t.find("table")]

        for i, table in enumerate(inner_tables):
            section_title = f"Details Section {i+1}"
            parent_card = table.find_parent(["div", "section"], class_=lambda c: c and any(x in c.lower() for x in ['card', 'panel', 'box', 'wrap']))
            if parent_card:
                header = parent_card.find(["div", "h1", "h2", "h3", "h4", "h5", "h6"], class_=lambda c: c and any(x in c.lower() for x in ['header', 'heading', 'title']))
                if header and len(header.get_text(strip=True)) < 50: 
                    section_title = header.get_text(strip=True)
            if section_title.startswith("Details Section"):
                prev = table.find_previous_sibling(["h1", "h2", "h3", "h4", "h5", "h6", "div"])
                if prev and len(prev.get_text(strip=True)) < 50:
                    section_title = prev.get_text(strip=True)

            if section_title not in profile["Sections"]: profile["Sections"][section_title] = {}

            for tr in table.find_all("tr"):
                if tr in processed_trs: continue
                cells = tr.find_all(["th", "td"], recursive=False)
                if not cells or len(cells) < 2: continue
                
                processed_trs.add(tr)
                cell_texts = [c.get_text(separator=" ", strip=True) for c in cells]
                if cell_texts[0].lower().replace(".", "").replace(" ", "") in ["sno", "slno", "serialno", "#"]: continue

                key = cell_texts[1].replace(":", "").strip() if len(cells) >= 3 and cell_texts[0].isdigit() else cell_texts[0].replace(":", "").strip()
                val_elem = cells[-1] if len(cells) >= 3 and cell_texts[0].isdigit() else cells[1]

                if not key or key.lower() == section_title.lower() or len(key) > 60: continue

                val_text = val_elem.get_text(separator=" ", strip=True)
                inputs = val_elem.find_all("input", type=lambda t: t and t.lower() != "hidden")
                if inputs: val_text = " ".join([inp.get("value", "").strip() for inp in inputs if inp.get("value")])

                href = None
                a_tag = val_elem.find("a", href=True)
                if a_tag and "javascript" not in a_tag["href"].lower() and "#" not in a_tag["href"]: href = a_tag["href"]
                else:
                    match = re.search(r"window\.open\(['\"]([^'\"]+)['\"]", str(val_elem))
                    if match: href = match.group(1)

                if href:
                    if href.startswith("/"): href = BASE + href
                    elif not href.startswith("http"): href = BASE + "/" + href
                    doc_name = val_text if val_text and val_text.lower() not in ["view", "download", "click here", "-", ""] else key
                    profile["Documents"][doc_name] = href
                else:
                    if val_text and val_text.lower() not in ["view", "download", "-", ""]:
                        profile["Sections"][section_title][key] = val_text

        empty_keys = [k for k, v in profile["Sections"].items() if not v]
        for k in empty_keys: del profile["Sections"][k]
        return profile
    except Exception:
        return {"Header": {"Roll Number": username.upper()}, "Sections": {}, "Documents": {}}

# --- Extreme Auto-Compression (From Bot) ---
def rasterize_and_compress_pdf(file_bytes):
    if not fitz or not Image:
        raise Exception("PyMuPDF/Pillow missing.")
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    images = []
    zoom_matrix = fitz.Matrix(0.5, 0.5)
    for page in doc:
        pix = page.get_pixmap(matrix=zoom_matrix, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
    if not images: return file_bytes
    output_io = io.BytesIO()
    images[0].save(output_io, format="PDF", resolution=100.0, save_all=True, append_images=images[1:], quality=50, optimize=True)
    return output_io.getvalue()

# -------------------------------------------------------------------
# API ROUTES
# -------------------------------------------------------------------
@app.route("/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    username, password = data.get("username"), data.get("password")
    if not username or not password: return jsonify({"ok": False, "error": "missing_credentials"}), 400
    session, err = login_session(username, password)
    if not session: return jsonify({"ok": False, "error": err}), 401
    token = secrets.token_urlsafe(24)
    TOKENS[token] = {"username": username, "time": time.time()}
    SESSIONS[token] = session
    return jsonify({"ok": True, "token": token})

@app.route("/all", methods=["GET"])
def api_all():
    token = require_token()
    session = SESSIONS[token]
    username = TOKENS[token]["username"]  
    return jsonify({
        "ok": True,
        "attendance": scrape_attendance(session),
        "midmarks": scrape_midmarks(session),
        "profile": scrape_profile(session, username)
    })

# --- NEW LAB ROUTES BASED ON BOT AJAX LOGIC ---

@app.route("/lab_init", methods=["GET"])
def api_lab_init():
    token = require_token()
    session = SESSIONS[token]
    try:
        r = session.get(BASE + "/home?action=labrecord_std", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        
        user_details = {}
        for key in ['ay', 'rollno', 'current_sem', 'lab_batch_no', 'dept_id', 'sec']:
            inp = soup.find('input', id=key)
            user_details[key] = inp['value'].strip() if inp else ""
            
        subjects = []
        # Target the exact ID found in the bot's scrape_lab_form logic
        select = soup.find('select', id='ddlsub_code')
        if select:
            for opt in select.find_all('option'):
                val = opt.get('value', '').strip()
                text = opt.get_text(strip=True)
                # Usually options are formatted as "CODE - Name", let's split it if possible
                if val and "Select Lab" not in text:
                    # Clean up the label if it contains a dash
                    if " - " in text:
                         text = text.split(" - ", 1)[1]
                    subjects.append({"value": val, "label": text})
                    
        return jsonify({"ok": True, "user_details": user_details, "subjects": subjects})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/lab_subject_data", methods=["POST"])
def api_lab_subject_data():
    token = require_token()
    session = SESSIONS[token]
    data = request.get_json() or {}
    sub_code = data.get("sub_code")
    ud = data.get("user_details", {})
    
    ajax_url = BASE + "/pages/student/lab_records/ajax/day2day.php"
    headers = {'x-requested-with': 'XMLHttpRequest'}
    
    schedule_list = []
    submitted_list = []
    
    try:
        # Fetch Schedule HTML
        exp_res = session.post(ajax_url, headers=headers, data={'ay': ud.get('ay'), 'sub_code': sub_code, 'action': 'get_exp_list'}, timeout=15)
        if exp_res.status_code == 200:
            soup = BeautifulSoup(exp_res.text, 'html.parser')
            for tr in soup.find_all('tr')[1:]:
                cols = tr.find_all('td')
                if len(cols) >= 3:
                    week = cols[0].get_text(strip=True)
                    title = cols[2].get_text(strip=True)
                    schedule_list.append({"week": week, "title": title})

        # Fetch Submitted JSON
        sub_res = session.post(ajax_url, headers=headers, data={'rollno': ud.get('rollno'), 'ay': ud.get('ay'), 'sub_code': sub_code, 'action': 'day2day_lab'}, timeout=15)
        if sub_res.status_code == 200:
            sub_json = sub_res.json()
            for rec in sub_json.get('data', []):
                week_no = rec.get('week_no')
                mark = rec.get('mark', '')
                status = "Evaluated" if mark and mark not in ['-', ''] else "Submitted"
                
                roll = ud.get('rollno', '').upper()
                sem = ud.get('current_sem', '').upper()
                url = f"https://iare-data.s3.ap-south-1.amazonaws.com/uploads/STUDENTS/{roll}/LAB/SEM{sem}/{sub_code}/{roll}_week{week_no}.pdf"
                
                submitted_list.append({
                    "week_no": str(week_no),
                    "week": f"Week-{week_no}",
                    "title": rec.get('exp_title', f"Experiment {week_no}"),
                    "marks": mark,
                    "status": status,
                    "url": url,
                })
                
        # Link Titles
        for sub in submitted_list:
            for sch in schedule_list:
                if sch['week'].replace(" ", "") == sub['week'].replace(" ", ""):
                    sub['title'] = sch['title']
                    
        return jsonify({"ok": True, "schedule": schedule_list, "submitted": submitted_list})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/lab_upload", methods=["POST"])
def api_lab_upload():
    token = require_token()
    session = SESSIONS[token]
    
    ajax_url = BASE + "/pages/student/lab_records/ajax/day2day"
    
    # We must send fields as MULTIPART using the exact structure the bot discovered
    upload_payload = {'action': (None, 'upload_lab_record_student')}
    for k, v in request.form.items():
        upload_payload[k] = (None, v)

    if not request.files or 'prog_doc' not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
        
    f = request.files['prog_doc']
    file_bytes = f.read()
    file_size = len(file_bytes)
    
    if file_size > 1024 * 1024:
        try:
            print(f"Auto-compressing {file_size} bytes...")
            file_bytes = rasterize_and_compress_pdf(file_bytes)
            file_size = len(file_bytes)
            print(f"Compressed down to: {file_size} bytes")
        except Exception as comp_err:
            print(f"Auto-Compression Failed: {comp_err}")
        
        if file_size > 1024 * 1024:
            return jsonify({"ok": False, "error": "PDF too large. Auto-compression failed. Please compress manually."}), 400

    stream = io.BytesIO(file_bytes)
    
    # Use exact naming convention required by portal
    rollno = request.form.get('rollno', '').upper()
    week_no = request.form.get('week_no', '')
    filename = f"{rollno}_week{week_no}.pdf" if rollno and week_no else f.filename
    
    upload_payload['prog_doc'] = (filename, stream, 'application/pdf')

    try:
        res = session.post(ajax_url, files=upload_payload, timeout=30)
        res_json = res.json()
        if res_json.get("status") == "success":
            return jsonify({"ok": True, "message": "Uploaded successfully to Samvidha!"})
        return jsonify({"ok": False, "error": res_json.get("msg", "Upload failed")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/lab_delete", methods=["POST"])
def api_lab_delete():
    token = require_token()
    session = SESSIONS[token]
    data = request.get_json() or {}
    
    ajax_url = BASE + "/pages/student/lab_records/ajax/day2day"
    headers = {'x-requested-with': 'XMLHttpRequest'}
    
    payload = {
        'rollno': data.get('rollno'), 'ay': data.get('ay'), 'sub_code': data.get('sub_code'),
        'week_no': data.get('week_no'), 'sem': data.get('current_sem'), 'action': 'day2day_lab_delete'
    }
    
    try:
        res = session.post(ajax_url, data=payload, headers=headers, timeout=15)
        res_json = res.json()
        if res_json.get("status") == "success":
            return jsonify({"ok": True, "message": "Deleted successfully from Samvidha!"})
        return jsonify({"ok": False, "error": res_json.get("msg", "Delete failed")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def require_token():
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "): abort(401)
    token = h.split(" ")[1]
    if token not in TOKENS: abort(401)
    return token

@app.route("/", methods=["GET"])
def home(): return jsonify({"status": "API is running"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
