import requests
import os
import concurrent.futures
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

app = Flask(__name__)
CORS(app)

BASE = "https://samvidha.iare.ac.in"
LOGIN_URL = BASE + "/pages/login/checkUser.php"

TOKENS = {}
SESSIONS = {}

class SessionExpiredError(Exception): pass

@app.errorhandler(SessionExpiredError)
def handle_session_expired(e):
    return jsonify({"ok": False, "error": "session_expired"}), 401

def check_auth(r):
    url = r.url.lower()
    if "login" in url or "index.php" in url or "checkuser" in url:
        raise SessionExpiredError("Session expired")
    if '<input type="password"' in r.text.lower() or 'name="password"' in r.text.lower():
        raise SessionExpiredError("Session expired")

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
        check_auth(r)
        
        soup = BeautifulSoup(r.text, "html.parser")
        attendance_data = []
        last_date = ""

        for td in soup.find_all(["td", "th"]):
            if "last date of semester" in td.get_text(strip=True).lower():
                nxt = td.find_next_sibling("td")
                if nxt:
                    last_date = nxt.get_text(strip=True)
                break

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
        return {"records": attendance_data, "last_date": last_date}
    except SessionExpiredError:
        raise
    except Exception:
        return {"records": [], "last_date": ""}

def scrape_biometric(session):
    try:
        r = session.get(BASE + "/home?action=std_bio", timeout=15)
        check_auth(r)
        
        soup = BeautifulSoup(r.text, "html.parser")
        bio_data = []
        for table in soup.find_all("table"):
            headers_text = table.get_text(separator=" ", strip=True).lower()
            if "date" in headers_text and "in time" in headers_text and "out time" in headers_text:
                for tr in table.find_all("tr"):
                    cols = tr.find_all("td")
                    if len(cols) >= 6 and cols[0].get_text(strip=True).isdigit():
                        roll_no = cols[1].get_text(strip=True)
                        if not roll_no or roll_no == "-": continue 
                        date = cols[3].get_text(strip=True)
                        in_time = cols[4].get_text(strip=True)
                        out_time = cols[5].get_text(strip=True)
                        status = cols[6].get_text(strip=True) if len(cols) > 6 else "-"
                        
                        if date and date != "-":
                            bio_data.append({"date": date, "in_time": in_time, "out_time": out_time, "status": status})
                break
        return bio_data
    except SessionExpiredError:
        raise
    except Exception as e:
        return []

def scrape_midmarks(session):
    try:
        r = session.get(BASE + "/home?action=cie_marks_ug", timeout=15)
        check_auth(r)
        
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
    except SessionExpiredError:
        raise
    except Exception:
        return {"theory": [], "laboratory": []}

def scrape_results(session):
    try:
        r = session.get(BASE + "/home?action=credit_register", timeout=15)
        check_auth(r)
        
        if r.status_code == 200 and "SEMESTER" in r.text.upper():
            soup = BeautifulSoup(r.text, "html.parser")
            results_data = []
            current_sem_data = None
            overall_cgpa = "N/A"
            
            rows = soup.find_all('tr')
            for row in rows:
                text = row.get_text(separator=" ", strip=True).upper()
                if "SEMESTER" in text and "AVERAGE" not in text and len(text.split()) <= 3:
                    if current_sem_data: results_data.append(current_sem_data)
                    current_sem_data = {"semester": text.strip(), "subjects": [], "sgpa": "N/A", "cgpa": "N/A"}
                    continue
                if not current_sem_data: continue
                if "SEMESTER GRADE POINT AVERAGE" in text:
                    match = re.search(r'SGPA[^\d]*([\d\.]+)', text)
                    if match: current_sem_data["sgpa"] = match.group(1)
                    continue
                if "CUMULATIVE GRADE POINT AVERAGE" in text:
                    match = re.search(r'CGPA[^\d]*([\d\.]+)', text)
                    if match: 
                        current_sem_data["cgpa"] = match.group(1)
                        overall_cgpa = match.group(1) 
                    continue
                cols = row.find_all(['td', 'th'])
                if len(cols) >= 8 and cols[0].get_text(strip=True).isdigit():
                    grade = cols[3].get_text(strip=True)
                    status = cols[5].get_text(strip=True)
                    is_backlog = status == 'F' or grade == 'F' or 'bg-danger' in str(row)
                    current_sem_data["subjects"].append({
                        "code": cols[1].get_text(strip=True), "name": cols[2].get_text(strip=True),
                        "grade": grade, "points": cols[4].get_text(strip=True),
                        "status": status, "credits": cols[6].get_text(strip=True), "is_backlog": is_backlog
                    })
            if current_sem_data: results_data.append(current_sem_data)
            return {"semesters": results_data, "overall_cgpa": overall_cgpa}
    except SessionExpiredError: raise
    except Exception as e: pass
    return {"semesters": [], "overall_cgpa": "N/A"}

def scrape_memos(session, username):
    try:
        r = session.get(BASE + "/home?action=mybox", timeout=15)
        check_auth(r)
        memos = []
        roll = username.upper()
        
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            
            # STRATEGY 1: Parse the HTML table normally
            for table in soup.find_all("table"):
                headers_text = table.get_text(separator=" ", strip=True).lower()
                if "view file" in headers_text or "name" in headers_text or "date" in headers_text:
                    for tr in table.find_all("tr"):
                        cols = tr.find_all("td")
                        if len(cols) < 2: continue
                        
                        # Find the index of the Date column to anchor our data extraction safely
                        date_idx = -1
                        date_str = ""
                        for i, col in enumerate(cols):
                            txt = col.get_text(strip=True)
                            if re.search(r'\d{2}[-/]\d{2}[-/]\d{2,4}', txt):
                                date_idx = i
                                date_str = txt
                                break
                                
                        name = ""
                        if date_idx > 0:
                            name = cols[date_idx - 1].get_text(strip=True)
                        elif len(cols) >= 2:
                            name = cols[1].get_text(strip=True)

                        if not name or "no data" in name.lower(): continue

                        raw_html = str(tr)
                        href = None
                        
                        # Look specifically for a .pdf filename in the row's raw HTML
                        pdf_match = re.search(r'[\'"]([a-zA-Z0-9_]+\.pdf)[\'"]', raw_html, re.IGNORECASE)
                        if pdf_match:
                            href = pdf_match.group(1)
                        else:
                            win_match = re.search(r"window\.open\(['\"]([^'\"]+)['\"]", raw_html, re.IGNORECASE)
                            if win_match: href = win_match.group(1)
                            
                        if href:
                            # Reconstruct the Amazon S3 link perfectly based on your example
                            if href.endswith(".pdf") and "/" not in href:
                                href = f"https://iare-data.s3.ap-south-1.amazonaws.com/uploads/STUDENTS/{roll}/mybox/{href}"
                            elif href.startswith("/"): 
                                href = BASE + href
                            elif not href.startswith("http"): 
                                href = BASE + "/" + href
                            
                            if not any(m['link'] == href for m in memos):
                                memos.append({"name": name, "date": date_str, "link": href})

            # STRATEGY 2: If the data was loaded via JS array and is missing from the DOM tree
            if not memos:
                # Force-extract all PDF filenames attached to this roll number from the raw scripts
                pdf_files = re.findall(rf'({roll}_[0-9]+\.pdf)', r.text, re.IGNORECASE)
                
                # Extract surrounding Context Names & Dates
                names = re.findall(r'(B\.\s*TECH[^"\'<,\\]+)', r.text, re.IGNORECASE)
                dates = re.findall(r'\d{2}-\d{2}-\d{4}', r.text)
                
                # Remove duplicates while preserving order
                pdf_files = list(dict.fromkeys(pdf_files)) 
                names = list(dict.fromkeys(names))
                dates = list(dict.fromkeys(dates))

                for i, pdf in enumerate(pdf_files):
                    link = f"https://iare-data.s3.ap-south-1.amazonaws.com/uploads/STUDENTS/{roll}/mybox/{pdf}"
                    name = names[i].strip() if i < len(names) else f"Official Memo {i+1}"
                    date_str = dates[i] if i < len(dates) else "Available"
                    
                    if not any(m['link'] == link for m in memos):
                        memos.append({"name": name, "date": date_str, "link": link})
                        
        return memos
    except Exception as e:
        print(f"Memos Error: {e}")
    return []

def scrape_profile(session, username):
    try:
        r = session.get(BASE + "/home?action=profile", timeout=15)
        check_auth(r)
        soup = BeautifulSoup(r.text, "html.parser")
        profile = {"Header": {"Roll Number": username.upper()}, "Sections": {}, "Documents": {}}
        
        header_card = soup.find("div", class_=lambda c: c and any(x in c.lower() for x in ['profile', 'user-info', 'card-body']))
        if not header_card: header_card = soup
        name = header_card.find(["h3", "h4", "h5", "strong"])
        if name: profile["Header"]["Full Name"] = name.get_text(strip=True)
        branch = header_card.find(["h5", "p"])
        if branch: profile["Header"]["Department"] = branch.get_text(strip=True)

        for table in soup.find_all("table"):
            heading = table.find_previous(["h1", "h2", "h3", "h4", "h5", "h6", "div"], class_=lambda c: c and ('heading' in c.lower() or 'title' in c.lower() or 'panel-title' in c.lower()))
            panel = table.find_parent(["div"], class_=lambda c: c and 'panel' in c.lower())
            if panel and not heading:
                heading = panel.find(["div", "h1", "h2", "h3", "h4", "h5", "h6"], class_=lambda c: c and 'heading' in c.lower())

            section_name = heading.get_text(strip=True) if heading else "Other Details"
            if not section_name or len(section_name) > 40: section_name = "Other Details"
            if section_name not in profile["Sections"]: profile["Sections"][section_name] = {}

            for tr in table.find_all("tr"):
                cols = tr.find_all(["th", "td"])
                if len(cols) >= 2:
                    if cols[0].get_text(strip=True).isdigit() and len(cols) > 2:
                        key = cols[1].get_text(strip=True).replace(":", "")
                        val_elem = cols[-1]
                    else:
                        key = cols[0].get_text(strip=True).replace(":", "")
                        val_elem = cols[1] if len(cols) == 2 else cols[-1]
                    
                    if key.lower() in ["s.no", "sno", "#", "sl.no", ""]: continue
                    
                    a_tag = val_elem.find("a", href=True)
                    if a_tag and "javascript" not in a_tag["href"].lower() and "#" not in a_tag["href"]:
                        href = a_tag["href"]
                        if href.startswith("/"): href = BASE + href
                        elif not href.startswith("http"): href = BASE + "/" + href
                        doc_name = val_elem.get_text(strip=True)
                        if not doc_name or doc_name.lower() in ["view", "download", "-"]: doc_name = key
                        profile["Documents"][doc_name] = href
                        continue
                        
                    val = val_elem.get_text(separator=" ", strip=True)
                    if val and val != "-" and len(key) < 50:
                        profile["Sections"][section_name][key] = val

        for strong in soup.find_all(["strong", "b"]):
            key = strong.get_text(strip=True).replace(":", "")
            if not key or len(key) > 40: continue
            parent = strong.parent
            if parent.name in ["td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "a", "button"]: continue
            text_content = parent.get_text(separator="\n", strip=True)
            val = text_content.replace(strong.get_text(strip=True), "").strip().strip(":\n- ")
            if val and len(val) > 0 and len(val) < 200:
                panel = parent.find_parent(["div"], class_=lambda c: c and 'panel' in c.lower())
                section_name = "Contacts"
                if panel:
                    heading = panel.find(["div", "h1", "h2", "h3", "h4", "h5", "h6"], class_=lambda c: c and 'heading' in c.lower())
                    if heading: section_name = heading.get_text(strip=True)
                if section_name not in profile["Sections"]: profile["Sections"][section_name] = {}
                profile["Sections"][section_name][key] = val

        empty_keys = [k for k, v in profile["Sections"].items() if not v]
        for k in empty_keys: del profile["Sections"][k]
        return profile
    except SessionExpiredError: raise
    except Exception as e:
        return {"Header": {"Roll Number": username.upper()}, "Sections": {}, "Documents": {}}

def rasterize_and_compress_pdf(file_bytes):
    if not fitz or not Image: raise Exception("PyMuPDF/Pillow missing.")
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

def require_token():
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "): abort(401)
    token = h.split(" ")[1]
    if token not in TOKENS: abort(401)
    return token

@app.route("/check_update", methods=["GET"])
def check_update():
    return jsonify({"version": "2.0.0", "build_number": 3, "download_url": "https://drive.google.com/file/d/1EIY7psGPST0F63nOpcu_4vB5Uys70Inc/view?usp=sharing"})

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

@app.route("/profile", methods=["GET"])
def api_profile():
    token = require_token()
    return jsonify({"profile": scrape_profile(SESSIONS[token], TOKENS[token]["username"])})

@app.route("/attendance", methods=["GET"])
def api_attendance():
    token = require_token()
    return jsonify({"attendance": scrape_attendance(SESSIONS[token]), "biometric": scrape_biometric(SESSIONS[token])})

@app.route("/results", methods=["GET"])
def api_results():
    token = require_token()
    results_info = scrape_results(SESSIONS[token])
    # Pass username properly to scrape_memos
    results_info["memos"] = scrape_memos(SESSIONS[token], TOKENS[token]["username"])
    return jsonify({"results": results_info})

@app.route("/marks", methods=["GET"])
def api_marks():
    token = require_token()
    return jsonify({"midmarks": scrape_midmarks(SESSIONS[token])})

@app.route("/all", methods=["GET"])
def api_all():
    token = require_token()
    session = SESSIONS[token]
    username = TOKENS[token]["username"]  
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            f_att = executor.submit(scrape_attendance, session)
            f_bio = executor.submit(scrape_biometric, session)
            f_mid = executor.submit(scrape_midmarks, session)
            f_pro = executor.submit(scrape_profile, session, username)
            f_res = executor.submit(scrape_results, session)
            f_mem = executor.submit(scrape_memos, session, username)
            
        results_info = f_res.result()
        results_info["memos"] = f_mem.result()
        
        return jsonify({
            "ok": True, 
            "attendance": f_att.result(), 
            "biometric": f_bio.result(), 
            "midmarks": f_mid.result(), 
            "profile": f_pro.result(), 
            "results": results_info
        })
    except SessionExpiredError: abort(401)

@app.route("/lab_init", methods=["GET"])
def api_lab_init():
    token = require_token()
    session = SESSIONS[token]
    try:
        r = session.get(BASE + "/home?action=labrecord_std", timeout=15)
        check_auth(r)
        soup = BeautifulSoup(r.text, "html.parser")
        user_details = {}
        for key in ['ay', 'rollno', 'current_sem', 'lab_batch_no', 'dept_id', 'sec']:
            inp = soup.find('input', id=key)
            user_details[key] = inp['value'].strip() if inp else ""
            
        subjects = []
        seen_subjects = set()
        select = soup.find('select', id='ddlsub_code')
        if select:
            for opt in select.find_all('option'):
                val = opt.get('value', '').strip()
                text = opt.get_text(strip=True)
                if val and "Select Lab" not in text:
                    if val not in seen_subjects:
                        seen_subjects.add(val)
                        if " - " in text: text = text.split(" - ", 1)[1]
                        subjects.append({"value": val, "label": text})
        return jsonify({"ok": True, "user_details": user_details, "subjects": subjects})
    except Exception as e: return jsonify({"ok": False, "error": str(e)})

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
        exp_res = session.post(ajax_url, headers=headers, data={'ay': ud.get('ay'), 'sub_code': sub_code, 'action': 'get_exp_list'}, timeout=15)
        check_auth(exp_res)
        if exp_res.status_code == 200:
            soup = BeautifulSoup(exp_res.text, 'html.parser')
            for tr in soup.find_all('tr')[1:]:
                cols = tr.find_all('td')
                if len(cols) >= 6:
                    schedule_list.append({"week": cols[0].get_text(strip=True), "title": cols[3].get_text(strip=True), "date": cols[5].get_text(strip=True)})

        sub_res = session.post(ajax_url, headers=headers, data={'rollno': ud.get('rollno'), 'ay': ud.get('ay'), 'sub_code': sub_code, 'action': 'day2day_lab'}, timeout=15)
        check_auth(sub_res)
        if sub_res.status_code == 200:
            sub_json = sub_res.json()
            for rec in sub_json.get('data', []):
                week_no = rec.get('week_no')
                mark = str(rec.get('mark', '')).strip()
                action_str = str(rec.get('action', '')).lower()
                remarks = str(rec.get('remarks', '')).lower()
                can_delete = str(rec.get('delete', '0')) == '1' or 'delete' in action_str or 'btn-danger' in action_str
                can_reupload = 'reupload' in action_str or 're-upload' in action_str or 'update' in action_str or 'reupload' in remarks
                
                if can_delete or can_reupload:
                    status = "Submitted"  
                    if mark == "0": mark = "-"  
                else: status = "Evaluated" if mark and mark not in ["-", ""] else "Submitted"
                
                roll = ud.get('rollno', '').upper()
                sem = ud.get('current_sem', '').upper()
                url = f"https://iare-data.s3.ap-south-1.amazonaws.com/uploads/STUDENTS/{roll}/LAB/SEM{sem}/{sub_code}/{roll}_week{week_no}.pdf"
                submitted_list.append({"week_no": str(week_no), "week": f"Week-{week_no}", "title": rec.get('exp_title', f"Experiment {week_no}"), "marks": mark if mark else "-", "status": status, "url": url, "can_delete": can_delete, "can_reupload": can_reupload})
                
        for sub in submitted_list:
            for sch in schedule_list:
                if sch['week'].replace(" ", "") == sub['week'].replace(" ", ""): sub['title'] = sch['title']
        return jsonify({"ok": True, "schedule": schedule_list, "submitted": submitted_list})
    except Exception as e: return jsonify({"ok": False, "error": str(e)})

@app.route("/lab_upload", methods=["POST"])
def api_lab_upload():
    token = require_token()
    session = SESSIONS[token]
    ajax_url = BASE + "/pages/student/lab_records/ajax/day2day"
    upload_payload = {'action': (None, 'upload_lab_record_student')}
    for k, v in request.form.items(): upload_payload[k] = (None, v)
    if not request.files or 'prog_doc' not in request.files: return jsonify({"ok": False, "error": "No file uploaded"}), 400
    f = request.files['prog_doc']
    file_bytes = f.read()
    if len(file_bytes) > 1024 * 1024:
        try: file_bytes = rasterize_and_compress_pdf(file_bytes)
        except Exception: pass
        if len(file_bytes) > 1024 * 1024: return jsonify({"ok": False, "error": "PDF too large. Please compress manually."}), 400
    rollno = request.form.get('rollno', '').upper()
    week_no = request.form.get('week_no', '')
    upload_payload['prog_doc'] = (f"{rollno}_week{week_no}.pdf" if rollno and week_no else f.filename, io.BytesIO(file_bytes), 'application/pdf')
    try:
        res = session.post(ajax_url, files=upload_payload, timeout=30)
        check_auth(res)
        res_json = res.json()
        if res_json.get("status") == "success": return jsonify({"ok": True, "message": "Uploaded successfully to Samvidha!"})
        return jsonify({"ok": False, "error": res_json.get("msg", "Upload failed")})
    except Exception as e: return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/lab_delete", methods=["POST"])
def api_lab_delete():
    token = require_token()
    session = SESSIONS[token]
    data = request.get_json() or {}
    try:
        res = session.post(BASE + "/pages/student/lab_records/ajax/day2day", data={'rollno': data.get('rollno'), 'ay': data.get('ay'), 'sub_code': data.get('sub_code'), 'week_no': data.get('week_no'), 'sem': data.get('current_sem'), 'action': 'day2day_lab_delete'}, headers={'x-requested-with': 'XMLHttpRequest'}, timeout=15)
        check_auth(res)
        if res.json().get("status") == "success": return jsonify({"ok": True, "message": "Deleted successfully!"})
        return jsonify({"ok": False, "error": "Delete failed"})
    except Exception as e: return jsonify({"ok": False, "error": str(e)})

@app.route("/", methods=["GET"])
def home(): return jsonify({"status": "API is running"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
