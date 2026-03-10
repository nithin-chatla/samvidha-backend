import requests
import os
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from bs4 import BeautifulSoup
import secrets
import time

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

def scrape_profile(session):
    try:
        r = session.get(BASE + "/home?action=profile", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        profile = {
            "Header": {},
            "Sections": {},
            "Documents": {}
        }
        
        # 1. Grab Name/Branch Headers robustly
        header_card = soup.find("div", class_=["card-body", "panel-body", "profile-user-info"])
        if header_card:
            name = header_card.find(["h3", "h4", "h5", "strong"])
            if name: profile["Header"]["Full Name"] = name.get_text(strip=True)
            branch = header_card.find(["h5", "p"])
            if branch: profile["Header"]["Department"] = branch.get_text(strip=True)

        # 2. Iterate ALL tables to prevent missing data in different layouts
        for table in soup.find_all("table"):
            # Try to identify the table's section name
            section_title = "General Details"
            prev_header = table.find_previous(["div", "h3", "h4", "h5", "h6"], class_=["card-header", "panel-heading", "box-header", "bg-primary"])
            if prev_header and prev_header.get_text(strip=True):
                section_title = prev_header.get_text(strip=True)

            if section_title not in profile["Sections"]:
                profile["Sections"][section_title] = {}

            # Process every row in the table
            for tr in table.find_all("tr"):
                cells = tr.find_all(["th", "td"])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True).replace(":", "").strip()
                    val_elem = cells[1]
                    
                    # Look for downloadable Document Links
                    link = val_elem.find("a", href=True)
                    if link:
                        href = link["href"]
                        if href.startswith("/"): href = BASE + href
                        elif not href.startswith("http"): href = BASE + "/" + href
                        profile["Documents"][key] = href
                    else:
                        val = val_elem.get_text(strip=True)
                        if key and val:
                            profile["Sections"][section_title][key] = val
                            
                            # Fallback: Capture Roll Number wherever it appears to ensure the photo loads
                            if "roll number" in key.lower() or "rollno" in key.lower():
                                profile["Header"]["Roll Number"] = val
                            # Fallback: Capture name/branch if it wasn't at the top of the page
                            if "name" in key.lower() and "father" not in key.lower() and "mother" not in key.lower() and "Full Name" not in profile["Header"]:
                                profile["Header"]["Full Name"] = val
                            if "branch" in key.lower() and "Department" not in profile["Header"]:
                                profile["Header"]["Department"] = val

        return profile
    except Exception as e:
        print(f"Scrape Profile Error: {e}")
        return {"Header": {}, "Sections": {}, "Documents": {}}

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
    return jsonify({
        "ok": True,
        "attendance": scrape_attendance(session),
        "midmarks": scrape_midmarks(session),
        "profile": scrape_profile(session)
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
