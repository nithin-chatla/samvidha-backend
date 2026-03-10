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
        
        # 1. Grab Name/Branch Headers robustly
        header_card = soup.find("div", class_=lambda c: c and any(x in c.lower() for x in ['profile', 'user-info', 'card-body', 'panel-body']))
        if not header_card: header_card = soup
        name = header_card.find(["h3", "h4", "h5", "strong"])
        if name: profile["Header"]["Full Name"] = name.get_text(strip=True)
        branch = header_card.find(["h5", "p"])
        if branch: profile["Header"]["Department"] = branch.get_text(strip=True)

        # 2. Iterate ONLY innermost tables (Ignores giant layout wrapper tables)
        inner_tables = [t for t in soup.find_all("table") if not t.find("table")]

        for i, table in enumerate(inner_tables):
            section_title = "Other Details"
            
            # Find the closest parent card/panel to get the real header
            parent_card = table.find_parent(["div", "section"], class_=lambda c: c and any(x in c.lower() for x in ['card', 'panel', 'box', 'wrap']))
            if parent_card:
                header = parent_card.find(["div", "h1", "h2", "h3", "h4", "h5", "h6"], class_=lambda c: c and any(x in c.lower() for x in ['header', 'heading', 'title']))
                if header: 
                    cleaned_header = header.get_text(strip=True)
                    if cleaned_header and len(cleaned_header) < 50: 
                        section_title = cleaned_header
            
            # Fallback if still generic
            if section_title == "Other Details":
                prev_header = table.find_previous_sibling(["h1", "h2", "h3", "h4", "h5", "h6", "div"])
                if prev_header:
                    text = prev_header.get_text(strip=True)
                    if 0 < len(text) < 50:
                        section_title = text

            if section_title not in profile["Sections"]:
                profile["Sections"][section_title] = {}

            # Process rows
            for tr in table.find_all("tr"):
                cells = tr.find_all(["th", "td"])
                if not cells or len(cells) < 2: continue
                
                cell_texts = [c.get_text(separator=" ", strip=True) for c in cells]
                first_cell_lower = cell_texts[0].lower().replace(".", "").replace(" ", "")

                # Skip header rows (fixes the "S.no Certificate" bug)
                if first_cell_lower in ["sno", "slno", "serialno", "#"]: 
                    continue
                
                key = ""
                val_elem = None
                
                # Smart Parsing: If 3+ columns and first is a number (S.No)
                if len(cells) >= 3 and cell_texts[0].isdigit():
                    key = cell_texts[1].replace(":", "").strip()
                    val_elem = cells[-1] # Button/Action is usually the last column
                else:
                    key = cell_texts[0].replace(":", "").strip()
                    val_elem = cells[1]

                if not key or key.lower() == section_title.lower() or len(key) > 60: continue
                
                # Extract value (handles standard text AND editable <input> fields like Phone/Email)
                val_text = val_elem.get_text(separator=" ", strip=True)
                input_tags = val_elem.find_all("input", type=lambda t: t != "hidden")
                for inp in input_tags:
                    if inp.get("value"):
                        val_text += " " + inp.get("value").strip()
                val_text = val_text.strip()
                
                # Ultimate Link Extractor (Finds <a> tags AND hidden JavaScript window.open buttons)
                href = None
                a_tag = val_elem.find("a", href=True)
                if a_tag and "javascript" not in a_tag["href"].lower() and "#" not in a_tag["href"]:
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
                    # Normal Text Data
                    if val_text and val_text.lower() not in ["view", "download", "-", ""]:
                        profile["Sections"][section_title][key] = val_text
                        
                        # Fallback updates for header
                        if "name" in key.lower() and "father" not in key.lower() and "mother" not in key.lower() and "Full Name" not in profile["Header"]:
                            profile["Header"]["Full Name"] = val_text
                        if "branch" in key.lower() and "Department" not in profile["Header"]:
                            profile["Header"]["Department"] = val_text

        # Clean up any empty sections
        empty_keys = [k for k, v in profile["Sections"].items() if not v]
        for k in empty_keys: del profile["Sections"][k]

        return profile
    except Exception as e:
        print(f"Scrape Profile Error: {e}")
        return {"Header": {"Roll Number": username.upper()}, "Sections": {}, "Documents": {}}

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
    username = TOKENS[token]["username"]  # Pass username for Guaranteed Roll Number
    return jsonify({
        "ok": True,
        "attendance": scrape_attendance(session),
        "midmarks": scrape_midmarks(session),
        "profile": scrape_profile(session, username)
    })

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
