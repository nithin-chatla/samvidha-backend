import requests
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
        "User-Agent": "Mozilla/5.0",
        "Origin": BASE,
        "Referer": BASE + "/index",
    }

    try:
        # CORRECT FIELD NAMES FOR SAMVIDHA ↓↓↓
        res = session.post(
            LOGIN_URL,
            data={"txt_uname": username, "txt_pwd": password},
            headers=headers,
            timeout=15
        )

        j = res.json()

    except Exception as e:
        print("Login Error:", e)
        return None, "server_error"

    # Samvidha success = status "1"
    if j.get("status") == "1":
        return session, None
    else:
        return None, "invalid_credentials"


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
    soup = BeautifulSoup(r.text, "lxml")
    table = find_table_with_keywords(soup, ["Attendance %"])
    return table_to_json(table)


def scrape_midmarks(session):
    r = session.get(BASE + "/home?action=cie_marks_ug", timeout=15)
    soup = BeautifulSoup(r.text, "lxml")

    theory_table = find_table_with_keywords(soup, ["CIE-I", "Total Marks"])
    lab_table = find_table_with_keywords(soup, ["Day to Day Marks", "Week 1"])

    return {
        "theory": table_to_json(theory_table),
        "laboratory": table_to_json(lab_table)
    }


def scrape_profile(session):
    r = session.get(BASE + "/home?action=profile", timeout=15)
    soup = BeautifulSoup(r.text, "lxml")

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

    # FRONTEND sends: { username, password }
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
    app.run(host="0.0.0.0", port=5000)
