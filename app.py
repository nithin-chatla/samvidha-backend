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
import json

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
            raw_html = r.text
            a_html = ""
            
            ajax_urls = re.findall(r'url\s*:\s*[\'"]([^\'"]+\.php)[\'"]', raw_html, re.IGNORECASE)
            ajax_urls.extend(["pages/student/mybox/ajax/mybox.php", "pages/student/my_box/ajax/mybox.php"])
            test_urls = []
            for url in ajax_urls:
                clean_url = BASE + url if url.startswith("/") else (url if url.startswith("http") else BASE + "/" + url)
                if clean_url not in test_urls: test_urls.append(clean_url)
            
            headers = {'x-requested-with': 'XMLHttpRequest'}
            for url in test_urls:
                for action in ['get_mybox', 'get_mybox_data', 'get_data', '']:
                    try:
                        payload = {'action': action} if action else {}
                        ajax_res = session.post(url, data=payload, headers=headers, timeout=5)
                        if ajax_res.status_code == 200 and (".pdf" in ajax_res.text.lower() or roll in ajax_res.text.upper()):
                            a_html = ajax_res.text
                            break
                    except: pass
                if a_html: break

            for content in [raw_html, a_html]:
                if not content: continue
                soup = BeautifulSoup(content, "html.parser")
                
                for tr in soup.find_all("tr"):
                    if tr.find("table"): continue
                    
                    row_html = str(tr)
                    href = None
                    
                    pdf_match = re.search(rf'({roll}_\d+\.pdf)', row_html, re.IGNORECASE)
                    if pdf_match:
                        href = f"https://iare-data.s3.ap-south-1.amazonaws.com/uploads/STUDENTS/{roll}/mybox/{pdf_match.group(1)}"
                    else:
                        s3_match = re.search(r'(https://iare-data\.s3[^\s"\'<>]+\.pdf)', row_html, re.IGNORECASE)
                        if s3_match:
                            href = s3_match.group(1)
                        else:
                            win_match = re.search(r"window\.open\(['\"]([^'\"]+)['\"]", row_html, re.IGNORECASE)
                            if win_match and win_match.group(1).endswith(".pdf"):
                                href = win_match.group(1)
                                if not href.startswith("http"):
                                    pdf_name = href.split('/')[-1]
                                    href = f"https://iare-data.s3.ap-south-1.amazonaws.com/uploads/STUDENTS/{roll}/mybox/{pdf_name}"

                    if not href or any(m['link'] == href for m in memos):
                        continue
                        
                    for junk in tr.find_all(["button", "a", "script", "style", "i", "span"]):
                        junk.decompose()
                        
                    cols = tr.find_all(["td", "th"])
                    name = "Official Grade Memo"
                    date = "Available"
                    
                    for col in cols:
                        txt = col.get_text(separator=" ", strip=True)
                        txt = re.sub(r'(?i)(cancel|print|view|download|close)', '', txt).strip(' -:>')
                        txt = re.sub(r'\s+', ' ', txt).strip()
                        
                        if re.match(r'^\d{2}[-/]\d{2}[-/]\d{2,4}$', txt):
                            date = txt
                        elif any(x in txt.upper() for x in ["B. TECH", "EXAMINATION", "MEMO", "REGULAR", "SUPPLEMENTARY", "RESULTS"]):
                            if 5 < len(txt) < 150: 
                                name = txt
                                
                    memos.append({"name": name, "date": date, "link": href})

            if not memos:
                combined = raw_html + a_html
                pdfs = re.findall(rf'({roll}_\d+\.pdf)', combined, re.IGNORECASE)
                pdfs = list(dict.fromkeys(pdfs))
                
                for idx, pdf in enumerate(pdfs):
                    link = f"https://iare-data.s3.ap-south-1.amazonaws.com/uploads/STUDENTS/{roll}/mybox/{pdf}"
                    if any(m['link'] == link for m in memos): continue
                    
                    match_pos = combined.find(pdf)
                    name = f"Official Grade Memo {idx+1}"
                    date = "Available"
                    
                    if match_pos != -1:
                        context = combined[max(0, match_pos - 600) : match_pos]
                        
                        d_matches = re.findall(r'\d{2}[-/]\d{2}[-/]\d{4}', context)
                        if d_matches: 
                            date = d_matches[-1] 
                            
                        n_matches = re.findall(r'((?:B\.\s*TECH|EXAMINATION)[^"\'<,\\]+)', context, re.IGNORECASE)
                        if n_matches:
                            best_name = n_matches[-1] 
                            clean_name = re.sub(r'(?i)(cancel|print|view|download|close|btn|class|href|javascript|my box|revaluation|s\.no|exam title)', '', best_name).strip(' -:>')
                            clean_name = re.sub(r'\s+', ' ', clean_name).strip()
                            if clean_name: name = clean_name
                            
                    memos.append({"name": name, "date": date, "link": link})

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

def scrape_timetable(session, ay=None, section=None):
    try:
        r = session.get(BASE + "/home?action=TT_std", timeout=15)
        check_auth(r)
        soup = BeautifulSoup(r.text, "html.parser")
        
        ays, sections = [], []
        ay_input_name = "ay"
        sec_input_name = "sec"
        
        sel_ay = soup.find('select', id=re.compile(r'ay', re.I)) or soup.find('select', {'name': re.compile(r'ay', re.I)})
        if sel_ay:
            ay_input_name = sel_ay.get('name', 'ay')
            ays = [{'value': o.get('value', ''), 'label': o.get_text(strip=True)} for o in sel_ay.find_all('option') if o.get('value')]
            
        sel_sec = soup.find('select', id=re.compile(r'sec', re.I)) or soup.find('select', {'name': re.compile(r'sec', re.I)})
        if sel_sec:
            sec_input_name = sel_sec.get('name', 'sec')
            sections = [{'value': o.get('value', ''), 'label': o.get_text(strip=True)} for o in sel_sec.find_all('option') if o.get('value')]

        schedule, subjects = [], []
        html_to_parse = r.text
        
        if ay and section:
            try:
                form_data = {
                    ay_input_name: ay,
                    sec_input_name: section,
                    'action': 'TT_std',
                    'submit': 'show',
                    'show': 'show',
                    'btnShow': 'show'
                }
                
                form = soup.find('form')
                if form:
                    for inp in form.find_all('input', type='hidden'):
                        if inp.get('name'):
                            form_data[inp.get('name')] = inp.get('value', '')
                            
                    submit_btn = form.find('button', type='submit') or form.find('input', type='submit')
                    if submit_btn and submit_btn.get('name'):
                        form_data[submit_btn.get('name')] = submit_btn.get('value', '') or 'show'

                res = session.post(BASE + "/home?action=TT_std", data=form_data, timeout=10)
                if res.status_code == 200 and "Period" in res.text:
                    html_to_parse = res.text
            except: pass
            
            if "Period" not in html_to_parse:
                ajax_urls = [
                    BASE + "/pages/student/timetable/ajax/timetable.php",
                    BASE + "/pages/student/time_table/ajax/timetable.php",
                    BASE + "/pages/student/time_table/ajax/day2day.php",
                    BASE + "/pages/student/tt/ajax/tt.php",
                    BASE + "/pages/student/tt/ajax/timetable.php"
                ]
                headers = {'x-requested-with': 'XMLHttpRequest'}
                for url in ajax_urls:
                    for action in ['get_timetable', 'get_tt', 'show_tt', 'get_data', 'get_timetable_data']:
                        try:
                            payload = {'action': action, 'ay': ay, 'section': section, 'sec': section, ay_input_name: ay, sec_input_name: section}
                            res = session.post(url, data=payload, headers=headers, timeout=5)
                            if res.status_code == 200 and ("Period" in res.text or "Staff" in res.text):
                                html_to_parse = res.text
                                break
                        except: pass
                    if "Period" in html_to_parse: break

        data_soup = BeautifulSoup(html_to_parse, "html.parser")
        
        for table in data_soup.find_all("table"):
            header_text = table.get_text(separator=" ", strip=True).lower()
            if "period - i" in header_text or "period" in header_text:
                for tr in table.find_all("tr"):
                    cols = tr.find_all(["th", "td"])
                    if not cols: continue
                    day_text = cols[0].get_text(separator=" ", strip=True)
                    
                    if any(d in day_text.lower() for d in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]):
                        periods = []
                        for col in cols[1:]:
                            p_text = col.get_text(separator="\n", strip=True)
                            if not p_text or p_text == "-":
                                periods.append({"isFree": True, "subject": "-", "room": "", "faculty": ""})
                            else:
                                lines = [line.strip() for line in p_text.split('\n') if line.strip()]
                                subject = lines[0] if len(lines) > 0 else "-"
                                room = ""
                                faculty = ""
                                for line in lines[1:]:
                                    if "Room" in line: room = line.replace("Room", "").replace(":", "").strip()
                                    elif "Faculty" in line or "Staff" in line: faculty = line.replace("Faculty Id", "").replace("Faculty", "").replace(":", "").strip()
                                periods.append({"isFree": False, "subject": subject, "room": room, "faculty": faculty})

                        if periods: schedule.append({"day": day_text, "periods": periods})
                            
            elif "staff name" in header_text and "subject code" in header_text:
                for tr in table.find_all("tr"):
                    cols = tr.find_all("td")
                    if len(cols) >= 5 and cols[0].get_text(strip=True).isdigit():
                        subjects.append({
                            "code": cols[1].get_text(strip=True),
                            "name": cols[2].get_text(strip=True),
                            "short": cols[3].get_text(strip=True) if len(cols) > 3 else "",
                            "staff": cols[5].get_text(strip=True) if len(cols) > 5 else (cols[4].get_text(strip=True) if len(cols) > 4 else "")
                        })
                        
        return {"ok": True, "ays": ays, "sections": sections, "schedule": schedule, "subjects": subjects}
    except Exception as e:
        return {"ok": False, "error": str(e), "ays": [], "sections": [], "schedule": [], "subjects": []}

def scrape_qp_init(session):
    actions = ["qp_scheme", "qp_and_solution", "qp_and_solutions", "question_paper"]
    for act in actions:
        try:
            r = session.get(BASE + f"/home?action={act}", timeout=10)
            check_auth(r)
            soup = BeautifulSoup(r.text, "html.parser")
            options = []
            select_name = "exam_code"
            
            for select in soup.find_all('select'):
                opts = select.find_all('option')
                if len(opts) > 1:
                    select_name = select.get('name', 'exam_code')
                    for opt in opts:
                        val = opt.get('value', '').strip()
                        text = opt.get_text(strip=True)
                        if val and val != "0" and "Select" not in text:
                            options.append({"value": val, "label": text})
                    break
            
            if options:
                return {"ok": True, "options": options, "select_name": select_name, "action_used": act}
        except SessionExpiredError:
            raise
        except:
            continue
            
    return {"ok": False, "error": "Could not find exam dropdown.", "options": []}

def scrape_qp_data(session, select_name, exam_code):
    try:
        data = []
        seen_codes = set()
        html_content = ""

        def extract_from_mixed(content):
            if not content: return None
            content_str = str(content).strip()
            if not content_str or 'NOT-UPLOADED' in content_str.upper() or 'NOT UPLOADED' in content_str.upper():
                return None
            
            # If it's directly a URL (from JSON response)
            if content_str.startswith('http'):
                return content_str.replace('\\/', '/')
            
            # If it's HTML (fallback parser)
            soup_cell = BeautifulSoup(content_str, 'html.parser')
            a = soup_cell.find('a', href=True)
            if a and not a['href'].startswith('#') and 'javascript' not in a['href'].lower():
                link = a['href']
                if not link.startswith('http'): link = BASE + '/' + link.lstrip('/')
                return link.replace('\\/', '/')
                    
            s3_m = re.search(r'(https://iare-data\.s3[^\s"\'<>]*\.pdf)', content_str, re.IGNORECASE)
            if s3_m: return s3_m.group(1).replace('\\/', '/')
            
            win_m = re.search(r"window\.open\(['\"]([^'\"]+)['\"]", content_str, re.IGNORECASE)
            if win_m:
                link = win_m.group(1)
                if not link.startswith('http'): link = BASE + '/' + link.lstrip('/')
                return link.replace('\\/', '/')

            return None

        def add_record(c_code, c_name, c_date, qp_raw, sol_raw):
            if not c_code or c_code.lower() in ["n/a", "course code"]: return
            if c_code in seen_codes: return
            
            qp_link = extract_from_mixed(qp_raw)
            sol_link = extract_from_mixed(sol_raw)
            
            if qp_link or sol_link:
                data.append({
                    "course_code": c_code,
                    "course_name": c_name,
                    "date": c_date,
                    "qp_link": qp_link,
                    "sol_link": sol_link
                })
                seen_codes.add(c_code)

        # 1. Grab required hidden inputs (like dept_id) from the main Question Paper page
        base_urls = [BASE + "/home?action=qp_scheme", BASE + "/home?action=qp_and_solution"]
        hidden_payload = {}
        for burl in base_urls:
            try:
                r_base = session.get(burl, timeout=10)
                soup_base = BeautifulSoup(r_base.text, 'html.parser')
                for inp in soup_base.find_all('input', type='hidden'):
                    if inp.get('name') and inp.get('value'):
                        hidden_payload[inp.get('name')] = inp.get('value')
                if 'dept_id' in hidden_payload:
                    break 
            except: pass

        dept_id = hidden_payload.get('dept_id', '')

        headers = {
            'x-requested-with': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Referer': BASE + "/home?action=qp_scheme"
        }

        # 2. EXACT Match for the Network Payload provided in the screenshot
        # The screenshot explicitly shows the path /pages/student/exam_result/ajax/qp_scheme.php
        primary_ajax_url = BASE + "/pages/student/exam_result/ajax/qp_scheme.php"
        primary_payload = {
            "exam_code": exam_code,
            "dept_id": dept_id,
            "action": "get_qp_scheme_list"
        }
        
        # Merge any other hidden payload values (CSRF tokens)
        for k, v in hidden_payload.items():
            if k not in primary_payload:
                primary_payload[k] = v

        try:
            r_ajax = session.post(primary_ajax_url, data=primary_payload, headers=headers, timeout=10)
            if r_ajax.status_code == 200:
                if "{" in r_ajax.text:
                    try:
                        j = r_ajax.json()
                        if 'data' in j:
                            for row in j['data']:
                                # Handing pure JSON dictionary array shown in user screenshot
                                if isinstance(row, dict):
                                    add_record(
                                        row.get('sub_code', '').strip(),
                                        row.get('sub_title', '').strip(),
                                        row.get('exam_date', '').strip(),
                                        row.get('qp', ''),
                                        row.get('scheme', '')
                                    )
                                # Fallback if returned as a list array inside the JSON data block
                                elif isinstance(row, list) and len(row) >= 6:
                                    add_record(
                                        BeautifulSoup(str(row[1]), 'html.parser').get_text(strip=True),
                                        BeautifulSoup(str(row[2]), 'html.parser').get_text(strip=True),
                                        BeautifulSoup(str(row[3]), 'html.parser').get_text(strip=True),
                                        str(row[4]), str(row[5])
                                    )
                    except Exception as e: 
                        print("JSON Parse Error:", e)
                
                # We always append to html_content in case it is returning raw HTML
                html_content += r_ajax.text
        except: pass

        # Return early if primary attempt hit correctly and found records
        if data: return {"ok": True, "records": data}

        # 3. If that failed, fall back to aggressive multi-endpoint scan including the new exam_result path
        ajax_endpoints = [
            "/pages/student/exam_result/ajax/qp_scheme.php", 
            "/pages/student/qp_scheme/ajax/qp_scheme.php",
            "/pages/student/qp_and_solution/ajax/get_data.php",
            "/pages/student/qp_and_solutions/ajax/get_data.php",
            "/pages/student/question_paper/ajax/get_data.php",
            "/pages/student/qp_scheme/ajax/get_data.php",
            "/pages/student/qp_scheme/ajax/qp_scheme_data.php",
            "/pages/student/question_paper/ajax/qp.php"
        ]
        
        for endpoint in ajax_endpoints:
            for action_val in ['get_qp_scheme_list', 'get_data', 'show_data', 'get_qp_data', 'get_scheme', '']:
                try:
                    payload = {
                        select_name: exam_code, "exam_code": exam_code, "examCode": exam_code,
                        "dept_id": dept_id, "action": action_val,
                        "draw": "1", "start": "0", "length": "100"
                    }
                    for k, v in hidden_payload.items():
                        if k not in payload: payload[k] = v
                        
                    r2 = session.post(BASE + endpoint, data=payload, headers=headers, timeout=8)
                    if r2.status_code == 200:
                        if "{" in r2.text and "data" in r2.text:
                            try:
                                j = r2.json()
                                if 'data' in j:
                                    for row in j['data']:
                                        if isinstance(row, dict):
                                            add_record(
                                                row.get('sub_code', '').strip(),
                                                row.get('sub_title', '').strip(),
                                                row.get('exam_date', '').strip(),
                                                row.get('qp', ''),
                                                row.get('scheme', '')
                                            )
                                        elif isinstance(row, list) and len(row) >= 6:
                                            add_record(
                                                BeautifulSoup(str(row[1]), 'html.parser').get_text(strip=True),
                                                BeautifulSoup(str(row[2]), 'html.parser').get_text(strip=True),
                                                BeautifulSoup(str(row[3]), 'html.parser').get_text(strip=True),
                                                str(row[4]), str(row[5])
                                            )
                                    if data: return {"ok": True, "records": data}
                            except: pass
                        html_content += r2.text
                except: pass

        # 4. Parse all accumulated HTML (for standard <tr> responses as seen in elements screenshot)
        soup = BeautifulSoup(html_content, "html.parser")
        for tr in soup.find_all("tr"):
            cols = tr.find_all(["td", "th"])
            if len(cols) >= 6:
                s_no_cell = cols[0].get_text(strip=True)
                if s_no_cell.isdigit():
                    add_record(
                        cols[1].get_text(strip=True),
                        cols[2].get_text(strip=True),
                        cols[3].get_text(strip=True),
                        str(cols[4]), str(cols[5])
                    )
        
        return {"ok": True, "records": data}
    except SessionExpiredError:
        raise
    except Exception as e:
        return {"ok": False, "records": [], "error": str(e)}

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
    return jsonify({
        "version": "4.0", 
        "build_number": 4, 
        "download_url": "https://paste-your-google-drive-link-here.com"
    })

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
    results_info["memos"] = scrape_memos(SESSIONS[token], TOKENS[token]["username"])
    return jsonify({"results": results_info})

@app.route("/marks", methods=["GET"])
def api_marks():
    token = require_token()
    return jsonify({"midmarks": scrape_midmarks(SESSIONS[token])})

@app.route("/timetable", methods=["POST"])
def api_timetable():
    token = require_token()
    data = request.get_json() or {}
    return jsonify(scrape_timetable(SESSIONS[token], data.get("ay"), data.get("section")))

@app.route("/qp_init", methods=["GET"])
def api_qp_init():
    token = require_token()
    return jsonify(scrape_qp_init(SESSIONS[token]))

@app.route("/qp_data", methods=["POST"])
def api_qp_data():
    token = require_token()
    data = request.get_json() or {}
    return jsonify(scrape_qp_data(SESSIONS[token], data.get("select_name", "exam_code"), data.get("exam_code")))

@app.route("/all", methods=["GET"])
def api_all():
    token = require_token()
    session = SESSIONS[token]
    username = TOKENS[token]["username"]  
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
            f_att = executor.submit(scrape_attendance, session)
            f_bio = executor.submit(scrape_biometric, session)
            f_mid = executor.submit(scrape_midmarks, session)
            f_pro = executor.submit(scrape_profile, session, username)
            f_res = executor.submit(scrape_results, session)
            f_mem = executor.submit(scrape_memos, session, username)
            f_tt  = executor.submit(scrape_timetable, session, None, None)
            
        results_info = f_res.result()
        results_info["memos"] = f_mem.result()
        
        return jsonify({
            "ok": True, 
            "attendance": f_att.result(), 
            "biometric": f_bio.result(), 
            "midmarks": f_mid.result(), 
            "profile": f_pro.result(), 
            "results": results_info,
            "timetable_init": f_tt.result()
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
