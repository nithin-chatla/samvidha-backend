import ollama
from flask import Flask, request, jsonify

# Samvidha AI - Complete Offline Server
# This is a ready-to-run Flask server that integrates with Ollama to provide a fully offline, context-aware AI.

app = Flask(__name__)

SYSTEM_PROMPT = """You are Samvidha AI, the official intelligent assistant for the Samvidha IARE app. 
You are helpful, polite, concise, and friendly.
The user is currently talking to you inside the app. 

Here are the user's current live details. Use these exact details to answer their questions:
- Name: {name}
- Roll Number: {roll_number}
- Overall Attendance: {attendance}
- Overall CGPA: {cgpa}

Rules:
1. If they ask about their attendance, tell them the exact percentage listed above.
2. If they ask about their marks or CGPA, tell them the exact CGPA listed above.
3. If you don't know the answer, tell them to explore the Samvidha App dashboard.
4. Keep answers short and natural.
"""

@app.route('/chatbot', methods=['POST'])
def chatbot_endpoint():
    try:
        data = request.json
        user_msg = data.get('message', '')
        user_data = data.get('user_data', {})
        
        # 1. Extract Personal Details
        profile = user_data.get('profile', {}).get('Header', {})
        name = profile.get('Full Name', 'Student')
        roll_number = profile.get('Roll No', 'Unknown')
        
        # 2. Extract and Calculate Attendance
        att_data = user_data.get('attendance')
        attendance_str = "Not available right now"
        if isinstance(att_data, list):
            total_attended = 0
            total_conducted = 0
            for record in att_data:
                cond = float(''.join(filter(str.isdigit, str(record.get('Conducted', '0')))) or 0)
                att = float(''.join(filter(str.isdigit, str(record.get('Attended', '0')))) or 0)
                if cond > 0:
                    total_conducted += cond
                    total_attended += att
            if total_conducted > 0:
                attendance_str = f"{(total_attended / total_conducted) * 100:.2f}%"

        # 3. Extract CGPA
        cgpa = user_data.get('results', {}).get('overall_cgpa', 'Not available right now')
        
        # 4. Inject into AI Context
        context = SYSTEM_PROMPT.format(
            name=name,
            roll_number=roll_number,
            attendance=attendance_str,
            cgpa=cgpa
        )
        
        # 5. Query Local Offline Ollama Model
        response = ollama.chat(model='tinyllama', messages=[
            {'role': 'system', 'content': context},
            {'role': 'user', 'content': user_msg}
        ])
        
        reply = response['message']['content']
        return jsonify({"success": True, "reply": reply})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    print("="*50)
    print("🚀 Starting Samvidha AI Server...")
    print("Ensure you have Ollama installed and run: ollama pull tinyllama")
    print("="*50)
    app.run(host='0.0.0.0', port=5000)

