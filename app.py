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

# In-memory storage
TOKENS = {}
SESSIONS = {}

# -------------------------------------------------------------------
# LOGIN SESSION
# -------------------------------------------------------------------
def login_session(username, password):
    session = requests.Session()

    headers = {
        "Host": "samvidha.iare.ac.in",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://samvidha.iare.ac.in",
        "Referer": "https://samvidha.iare.ac.in/",
        "X-Requested-With": "XMLHttpRequest",
    }

    payload = {
        "username": username,
        "password": password
    }

    try:
        res = session.post(
            LOGIN_URL,
            data=payload,
            headers=headers,
            timeout=20
        )

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
# HELPERS
# -------------------------------------------------------------------
def find_table_with_keywords(soup, keywords):
    for table in soup.find_all("table"):
        text = table.get_text()
        if all(word in text for word in keywords):
            return table
    return None

def table_to_json(table):
    if not table:
        return []

    rows = []
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    
    all_trs = table.find_all("tr")
    if not headers and all_trs:
        headers = [td.get_text(strip=True) for td in all_trs[0].find_all("td")]
        all_trs = all_trs[1:]
    
    for tr in all_trs:
        cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cols) == len(headers) and len(headers) > 0:
            if cols == headers: continue
            rows.append(dict(zip(headers, cols)))
        elif len(cols) > 0 and not headers:
            rows.append({"data": cols})

    return rows


# -------------------------------------------------------------------
# SCRAPERS
# -------------------------------------------------------------------
def scrape_attendance(session):
    try:
        r = session.get(BASE + "/home?action=stud_att_STD", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        
        attendance_data = []
        
        # Search all tables for the exact attendance report format
        for table in soup.find_all("table"):
            text = table.get_text()
            if "Course Name" in text and "Attendance %" in text:
                for tr in table.find_all("tr"):
                    cols = tr.find_all("td")
                    
                    # Safely handle different column counts across branches
                    if len(cols) >= 7:
                        s_no = cols[0].get_text(strip=True)
                        
                        if not s_no.isdigit():
                            continue
                            
                        # Reading from the END of the list ensures we always get the right numbers 
                        # even if a branch has extra columns like "Course Category"
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
        current_sem = "Current Semester" # Default track

        for row in rows:
            text = row.get_text(strip=True).lower()
            
            # Detect the semester header (usually spans across the table)
            if "semester" in text and len(row.find_all(["th", "td"])) <= 3:
                # Ignore standard headers that might randomly contain the word
                if "course" not in text and "marks" not in text:
                    current_sem = row.get_text(strip=True).replace(":", "").strip()
                    continue

            if "continuous internal assessment marks (theory)" in text:
                current_mode = "theory"
                continue
            elif "laboratory marks (practical)" in text:
                current_mode = "lab"
                continue
                
            cols = row.find_all("td")
            
            # Use safer indexing to support branches with fewer AAT exams
            if len(cols) >= 6 and current_mode == "theory":
                if not cols[0].get_text(strip=True).isdigit(): continue
                theory_data.append({
                    "Semester": current_sem,
                    "Course Name": cols[2].get_text(strip=True),
                    "CIE-I": cols[3].get_text(strip=True) if len(cols) > 3 else "-",
                    "AAT:I-I": cols[4].get_text(strip=True) if len(cols) > 4 else "-",
                    "AAT:I-II": cols[5].get_text(strip=True) if len(cols) > 5 else "-",
                    "CIE-II": cols[6].get_text(strip=True) if len(cols) > 6 else "-",
                    "AAT:II-I": cols[7].get_text(strip=True) if len(cols) > 7 else "-",
                    "Total Marks": cols[-1].get_text(strip=True) # Always grabs the very last column
                })
            elif len(cols) >= 4 and current_mode == "lab":
                if not cols[0].get_text(strip=True).isdigit(): continue
                lab_data.append({
                    "Semester": current_sem,
                    "Course Name": cols[2].get_text(strip=True),
                    "Week 1": cols[3].get_text(strip=True) if len(cols) > 3 else "-",
                    "Marks": cols[-1].get_text(strip=True) # Always grabs the very last column
                })
        return {"theory": theory_data, "laboratory": lab_data}
    except:
        return {"theory": [], "laboratory": []}

def scrape_profile(session):
    try:
        r = session.get(BASE + "/home?action=profile", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        profile = {}
        
        # Capture Top Header Card Info
        header_card = soup.find("div", class_="card-body")
        if header_card:
            name = header_card.find(["h3", "h4"])
            if name: profile["Full Name"] = name.get_text(strip=True)
            branch = header_card.find(["h5", "p"])
            if branch: profile["Department"] = branch.get_text(strip=True)

        # Scrape all detail sections (General, Admin, Marks, Progress)
        for card in soup.find_all("div", class_="card"):
            header = card.find("div", class_="card-header")
            section_name = header.get_text(strip=True) if header else "Other Details"
            
            table = card.find("table")
            if table:
                section_data = {}
                for tr in table.find_all("tr"):
                    cells = tr.find_all(["th", "td"])
                    if len(cells) == 2:
                        key = cells[0].get_text(strip=True).replace(":", "").strip()
                        val = cells[1].get_text(strip=True)
                        if key: section_data[key] = val
                    elif len(cells) > 2:
                        pass
                
                if section_data:
                    for k, v in section_data.items():
                        profile[f"{section_name} - {k}"] = v

        return profile
    except Exception as e:
        print(f"Scrape Profile Error: {e}")
        return {}


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
