import requests
import os
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from bs4 import BeautifulSoup
import secrets
import time
import re

app = Flask(__name__)
CORS(app)

BASE = "https://samvidha.iare.ac.in"
LOGIN_URL = BASE + "/pages/login/checkUser.php"

TOKENS = {}
SESSIONS = {}

# -------------------------------------------------------------------
# LOGIN SESSION
# -------------------------------------------------------------------
def login_session(username, password):
    session = requests.Session()
    headers = {
        "Host": "samvidha.iare.ac.in",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": BASE,
        "Referer": BASE + "/",
        "X-Requested-With": "XMLHttpRequest",
    }
    payload = {"username": username, "password": password}

    try:
        res = session.post(LOGIN_URL, data=payload, headers=headers, timeout=20)
        try:
            j = res.json()
        except:
            return None, "invalid_response"

        if j.get("status") == "1":
            print(f"LOGIN SUCCESS: {username}")
            return session, None
        return None, "invalid_credentials"
    except Exception as e:
        return None, "network_error"

# -------------------------------------------------------------------
# SCRAPERS
# -------------------------------------------------------------------
def scrape_attendance(session):
    try:
        r = session.get(BASE + "/home?action=stud_att_STD", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        attendance_data = []
        for table in soup.find_all("table"):
            text = table.get_text()
            if "Course Name" in text and "Attendance %" in text:
                for tr in table.find_all("tr"):
                    cols = tr.find_all("td")
                    if len(cols) >= 7:
                        s_no = cols[0].get_text(strip=True)
                        if not s_no.isdigit(): continue
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
    except Exception as e:
        print(f"Scrape Attendance Error: {e}")
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
                    cell_text = cell.get_text(strip=True)
                    if "semester -" in cell_text.lower():
                        current_sem = cell_text
                        break
                        
            if "continuous internal assessment marks (theory)" in text:
                current_mode = "theory"
                continue
            elif "laboratory marks (practical)" in text or "seminar marks" in text:
                current_mode = "lab"
                continue
                
            cols = row.find_all("td")
            
            if len(cols) >= 10 and current_mode == "theory":
                if not cols[0].get_text(strip=True).isdigit(): continue
                theory_data.append({
                    "Semester": current_sem,
                    "Course Name": cols[2].get_text(strip=True),
                    "CIE-I": cols[3].get_text(strip=True),
                    "AAT:I-I": cols[4].get_text(strip=True),
                    "AAT:I-II": cols[5].get_text(strip=True),
                    "CIE-II": cols[6].get_text(strip=True),
                    "AAT:II-I": cols[7].get_text(strip=True),
                    "AAT:II-II": cols[8].get_text(strip=True),
                    "Total Marks": cols[-1].get_text(strip=True)
                })
            elif len(cols) >= 5 and current_mode == "lab":
                if not cols[0].get_text(strip=True).isdigit(): continue
                week_marks = []
                for i in range(3, len(cols) - 2): 
                    val = cols[i].get_text(strip=True)
                    if val: week_marks.append(val)

                lab_data.append({
                    "Semester": current_sem,
                    "Course Name": cols[2].get_text(strip=True),
                    "Weeks": week_marks,
                    "Exam Marks": cols[-2].get_text(strip=True),
                    "Marks": cols[-1].get_text(strip=True)
                })
        return {"theory": theory_data, "laboratory": lab_data}
    except Exception as e:
        print(f"Midmarks Scrape Error: {e}")
        return {"theory": [], "laboratory": []}

def scrape_profile(session, username):
    try:
        r = session.get(BASE + "/home?action=profile", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        profile = {"Header": {"Roll Number": username.upper()}, "Sections": {}, "Documents": {}}
        
        # Grab Name/Branch Headers
        header_card = soup.find("div", class_=lambda c: c and any(x in c.lower() for x in ['profile', 'user-info', 'card-body', 'panel-body']))
        if not header_card: header_card = soup
        name = header_card.find(["h3", "h4", "h5", "strong"])
        if name: profile["Header"]["Full Name"] = name.get_text(strip=True)
        branch = header_card.find(["h5", "p"])
        if branch: profile["Header"]["Department"] = branch.get_text(strip=True)

        processed_trs = set()

        # Iterate ONLY innermost tables to avoid layout tables breaking the parser
        inner_tables = [t for t in soup.find_all("table") if not t.find("table")]

        for i, table in enumerate(inner_tables):
            section_title = "Other Details"
            
            # Find accurate section header
            parent_card = table.find_parent(["div", "section"], class_=lambda c: c and any(x in c.lower() for x in ['card', 'panel', 'box', 'wrap']))
            if parent_card:
                header = parent_card.find(["div", "h1", "h2", "h3", "h4", "h5", "h6"], class_=lambda c: c and any(x in c.lower() for x in ['header', 'heading', 'title']))
                if header: 
                    cleaned_header = header.get_text(strip=True)
                    if cleaned_header and len(cleaned_header) < 50: 
                        section_title = cleaned_header
            
            if section_title == "Other Details":
                prev_header = table.find_previous_sibling(["h1", "h2", "h3", "h4", "h5", "h6", "div"])
                if prev_header:
                    text = prev_header.get_text(strip=True)
                    if 0 < len(text) < 50:
                        section_title = text

            if section_title not in profile["Sections"]:
                profile["Sections"][section_title] = {}

            for tr in table.find_all("tr"):
                if tr in processed_trs: continue
                
                cells = tr.find_all(["th", "td"])
                if not cells or len(cells) < 2: continue
                if any(c.find("table") for c in cells): continue
                    
                processed_trs.add(tr)
                cell_texts = [c.get_text(separator=" ", strip=True) for c in cells]
                
                first_val = cell_texts[0].lower().replace(".", "").replace(" ", "")
                if first_val in ["sno", "slno", "serialno", "#"]: continue

                if len(cells) >= 3 and cell_texts[0].isdigit():
                    key = cell_texts[1].replace(":", "").strip()
                    val_elem = cells[-1] 
                else:
                    key = cell_texts[0].replace(":", "").strip()
                    val_elem = cells[1]

                if not key or key.lower() == section_title.lower() or len(key) > 60: continue

                # Extract Value & Inputs
                val_text = val_elem.get_text(separator=" ", strip=True)
                input_tags = val_elem.find_all("input", type=lambda t: t and t.lower() != "hidden")
                if input_tags:
                    input_vals = [inp.get("value", "").strip() for inp in input_tags if inp.get("value")]
                    if input_vals: val_text = " ".join(input_vals)

                # Extract Links/PDFs
                href = None
                a_tag = val_elem.find("a", href=True)
                if a_tag and a_tag.get("href") and "javascript" not in a_tag["href"].lower() and "#" not in a_tag["href"]:
                    href = a_tag["href"]
                else:
                    match = re.search(r"window\.open\(['\"]([^'\"]+)['\"]", str(val_elem))
                    if match: href = match.group(1)

                if href:
                    if href.startswith("/"): href = BASE + href
                    elif not href.startswith("http"): href = BASE + "/" + href
                    doc_name = key
                    if val_text and val_text.lower() not in ["view", "download", "click here", "-", ""]:
                        doc_name = val_text
                    profile["Documents"][doc_name] = href
                else:
                    if val_text and val_text.lower() not in ["view", "download", "-", ""]:
                        profile["Sections"][section_title][key] = val_text
                        
                        kl = key.lower()
                        if "roll" in kl and "number" in kl: profile["Header"]["Roll Number"] = val_text
                        if "name" in kl and "father" not in kl and "mother" not in kl and "Full Name" not in profile["Header"]:
                            profile["Header"]["Full Name"] = val_text
                        if "branch" in kl and "Department" not in profile["Header"]:
                            profile["Header"]["Department"] = val_text

        empty_keys = [k for k, v in profile["Sections"].items() if not v]
        for k in empty_keys: del profile["Sections"][k]
        return profile
    except Exception as e:
        print(f"Scrape Profile Error: {e}")
        return {"Header": {"Roll Number": username.upper()}, "Sections": {}, "Documents": {}}

def scrape_lab_form(session):
    try:
        r = session.get(BASE + "/home?action=labrecord_std", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        form_data = {
            "action_url": "",
            "inputs": {},
            "dropdowns": {},
            "file_inputs": [],
            "schedule": [],
            "submitted": []
        }

        # 1. Extract the Upload Form
        upload_form = soup.find("form", enctype="multipart/form-data")
        if not upload_form:
            for f in soup.find_all("form"):
                if "upload" in str(f).lower() or "record" in f.get("action", "").lower():
                    upload_form = f
                    break

        if upload_form:
            form_data["action_url"] = upload_form.get("action", "")
            for inp in upload_form.find_all("input"):
                name = inp.get("name")
                inp_type = inp.get("type", "text").lower()
                if name:
                    if inp_type == "file": form_data["file_inputs"].append(name)
                    else: form_data["inputs"][name] = inp.get("value", "")

            for sel in upload_form.find_all("select"):
                name = sel.get("name")
                if name:
                    options = []
                    for opt in sel.find_all("option"):
                        val = opt.get("value", "")
                        text = opt.get_text(strip=True)
                        if val: options.append({"value": val, "label": text})
                    form_data["dropdowns"][name] = options

        # 2. Extract Experiment Schedule and Submitted Lists
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            header_text = " ".join(headers)
            
            # Scrape Experiment Details (Schedule)
            if "experiment title" in header_text and "submission date" in header_text:
                for tr in table.find_all("tr"):
                    cols = tr.find_all("td")
                    if len(cols) >= 6:
                        form_data["schedule"].append({
                            "week": cols[0].get_text(strip=True),
                            "title": cols[3].get_text(strip=True),
                            "date": cols[5].get_text(strip=True)
                        })
                        
            # Scrape Submitted Lab Record List
            if "marks" in header_text and "remarks" in header_text:
                for tr in table.find_all("tr"):
                    cols = tr.find_all("td")
                    if len(cols) >= 8:
                        if "no data available" in cols[0].get_text(strip=True).lower():
                            continue
                        
                        marks = cols[6].get_text(strip=True)
                        status = "Evaluated" if marks and marks not in ["-", ""] else "Submitted"
                        
                        # Find the View/Update link
                        url = ""
                        a_tag = cols[-1].find("a", href=True)
                        if a_tag:
                            url = a_tag["href"]
                            if url.startswith("/"): url = BASE + url
                            elif not url.startswith("http"): url = BASE + "/" + url
                        elif "window.open" in str(cols[-1]):
                            match = re.search(r"window\.open\(['\"]([^'\"]+)['\"]", str(cols[-1]))
                            if match: 
                                url = match.group(1)
                                if url.startswith("/"): url = BASE + url
                                elif not url.startswith("http"): url = BASE + "/" + url
                            
                        form_data["submitted"].append({
                            "week": cols[3].get_text(strip=True),
                            "title": cols[5].get_text(strip=True),
                            "marks": marks,
                            "status": status,
                            "url": url
                        })
        
        return form_data
    except Exception as e:
        print(f"Scrape Lab Form Error: {e}")
        return {"error": str(e)}

# -------------------------------------------------------------------
# API ROUTES
# -------------------------------------------------------------------
@app.route("/login", methods=["POST"], strict_slashes=False)
def api_login():
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"ok": False, "error": "missing_credentials"}), 400
    session, err = login_session(username, password)
    if not session:
        return jsonify({"ok": False, "error": err}), 401
    token = secrets.token_urlsafe(24)
    TOKENS[token] = {"username": username, "time": time.time()}
    SESSIONS[token] = session
    return jsonify({"ok": True, "token": token})

@app.route("/all", methods=["GET"], strict_slashes=False)
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

@app.route("/lab_form", methods=["GET"], strict_slashes=False)
def api_lab_form():
    token = require_token()
    session = SESSIONS[token]
    data = scrape_lab_form(session)
    return jsonify({"ok": True, "form": data})

@app.route("/upload_lab", methods=["POST"], strict_slashes=False)
def api_upload_lab():
    token = require_token()
    session = SESSIONS[token]
    
    action_url = request.form.get("action_url", "")
    if not action_url:
        return jsonify({"ok": False, "error": "Missing action_url"}), 400
        
    if not action_url.startswith("http"):
        action_url = BASE + action_url if action_url.startswith("/") else BASE + "/" + action_url

    payload = {k: v for k, v in request.form.items() if k != "action_url"}

    if not request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
        
    upload_files = {}
    for field_name, f in request.files.items():
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(0)
        if size > 1024 * 1024:
            return jsonify({"ok": False, "error": f"File exceeds Samvidha 1MB limit. Please compress it."}), 400
        
        upload_files[field_name] = (f.filename, f.stream, f.mimetype)

    try:
        res = session.post(action_url, data=payload, files=upload_files, timeout=30)
        if res.status_code == 200:
            return jsonify({"ok": True, "message": "Lab record submitted to Samvidha successfully!"})
        else:
            return jsonify({"ok": False, "error": f"Portal returned status {res.status_code}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

def require_token():
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "): abort(401)
    token = h.split(" ")[1]
    if token not in TOKENS: abort(401)
    return token

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Samvidha API is running"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
