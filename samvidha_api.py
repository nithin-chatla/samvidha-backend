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

    # HEADERS EXACTLY LIKE YOUR BROWSER
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
            print("NOT JSON:", res.text[:300])
            return None, "invalid_response"

        if j.get("status") == "1":
            print("LOGIN SUCCESS")
            return session, None

        print("LOGIN FAILED:", j)
        return None, "invalid_credentials"

    except Exception as e:
        print("LOGIN ERROR:", e)
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

    for tr in table.find_all("tr")[1:]:
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cols) == len(headers):
            rows.append(dict(zip(headers, cols)))

    return rows


# -------------------------------------------------------------------
# SCRAPERS
# -------------------------------------------------------------------
def scrape_attendance(session):
    r = session.get(BASE + "/home?action=stud_att_STD", timeout=15)
    # Using html.parser instead of lxml to prevent build errors on Render
    soup = BeautifulSoup(r.text, "html.parser")
    table = find_table_with_keywords(soup, ["Attendance %"])
    return table_to_json(table)

def scrape_midmarks(session):
    r = session.get(BASE + "/home?action=cie_marks_ug", timeout=15)
    # Using html.parser instead of lxml to prevent build errors on Render
    soup = BeautifulSoup(r.text, "html.parser")

    # We grab all rows from the page to handle complex spanning headers
    rows = soup.find_all("tr")
    
    theory_data = []
    lab_data = []
    
    current_mode = None  # Tracks if we are currently reading 'theory' or 'lab'

    for row in rows:
        text = row.get_text(strip=True).lower()
        
        # Detect which section we are in based on section headers
        if "continuous internal assessment marks (theory)" in text:
            current_mode = "theory"
            continue
        elif "laboratory marks (practical)" in text:
            current_mode = "lab"
            continue
            
        cols = row.find_all("td")
        
        # Valid data rows have many columns. Headers usually use 'th'.
        if len(cols) > 5: 
            if current_mode == "theory":
                # Extracted according to the exact column layout in screenshot
                theory_data.append({
                    "Course Name": cols[2].get_text(strip=True),
                    "CIE-I": cols[3].get_text(strip=True),
                    "AAT:I-I": cols[4].get_text(strip=True),
                    "AAT:I-II": cols[5].get_text(strip=True),
                    "CIE-II": cols[6].get_text(strip=True),
                    "AAT:II-I": cols[7].get_text(strip=True),
                    "Total Marks": cols[-1].get_text(strip=True) # Always grabs the last column
                })
            elif current_mode == "lab":
                lab_data.append({
                    "Course Name": cols[2].get_text(strip=True),
                    "Week 1": cols[3].get_text(strip=True),
                    "Week 2": cols[4].get_text(strip=True),
                    "Week 3": cols[5].get_text(strip=True),
                    "Marks": cols[-1].get_text(strip=True)
                })
                
    return {
        "theory": theory_data,
        "laboratory": lab_data
    }

def scrape_profile(session):
    r = session.get(BASE + "/home?action=profile", timeout=15)
    # Using html.parser instead of lxml to prevent build errors on Render
    soup = BeautifulSoup(r.text, "html.parser")

    profile = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cols = tr.find_all("td")
            if len(cols) == 2:
                k = cols[0].get_text(strip=True)
                v = cols[1].get_text(strip=True)
                profile[k] = v

    return profile


# -------------------------------------------------------------------
# TOKEN AUTH
# -------------------------------------------------------------------
def require_token():
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "):
        abort(401)

    token = h.split(" ")[1]
    if token not in TOKENS:
        abort(401)

    return token


# -------------------------------------------------------------------
# API ROUTES
# -------------------------------------------------------------------
@app.route("/login", methods=["POST"])
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

@app.route("/attendance", methods=["GET"])
def api_attendance():
    token = require_token()
    session = SESSIONS[token]
    data = scrape_attendance(session)
    return jsonify({"ok": True, "attendance": data})

@app.route("/midmarks", methods=["GET"])
def api_midmarks():
    token = require_token()
    session = SESSIONS[token]
    data = scrape_midmarks(session)
    return jsonify({"ok": True, "midmarks": data})

@app.route("/profile", methods=["GET"])
def api_profile():
    token = require_token()
    session = SESSIONS[token]
    data = scrape_profile(session)
    return jsonify({"ok": True, "profile": data})

@app.route("/all", methods=["GET"])
def api_all():
    token = require_token()
    session = SESSIONS[token]

    return jsonify({
        "ok": True,
        "attendance": scrape_attendance(session),
        "midmarks": scrape_midmarks(session),
        "profile": scrape_profile(session)
    })

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Samvidha API is running"})

if __name__ == "__main__":
    # Render assigns a dynamic port, so we read it from the environment here.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
