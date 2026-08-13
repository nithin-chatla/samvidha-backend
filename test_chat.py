import sys
import json

try:
    from app import rag_engine, call_ai_with_fallback, system_prompt
except ImportError:
    print("Error importing app modules. Ensure you are running this from the backend directory.")
    sys.exit(1)

def main():
    print("\n" + "="*50)
    print("Welcome to the Samvidha AI Chat Testing Console!")
    print("This console uses the FULL AI loop (unlike test_rag.py).")
    print("Try asking it something it doesn't know, and then teach it!")
    print("Type 'exit' to stop.")
    print("="*50)

    history = []
    
    # Mock user data
    user_data = {
        "profile": {"name": "Test User", "roll_number": "12345"}
    }

    while True:
        try:
            user_msg = input("\nYou: ").strip()
            if user_msg.lower() in ['exit', 'quit']:
                break
            if not user_msg:
                continue
                
            print("Thinking...")
            
            # Step 1: Re-build dynamic context with latest learned facts
            current_system_prompt = system_prompt
            if rag_engine:
                rag_context = rag_engine.build_prompt_context(user_msg, user_data)
                # the system_prompt inside app.py is hardcoded with initial context in api_chatbot
                # we need to build it dynamically here for testing
                current_system_prompt = f"""You are Samvidha AI, the official intelligent assistant for the Samvidha IARE app. 
You are helpful, polite, concise, and friendly. You are an expert academic advisor.

You have access to the app data and details of the student in JSON format below. 
You must help the student with anything they ask related to this data.

{rag_context}

Rules:
1. When they ask about attendance, calculate and advise them specifically.
2. When they ask about timetable, read the timetable data and answer accurately.
3. SELF-LEARNING CAPABILITY (CRITICAL):
   - If the student asks a question about the college (like events, timings, new rules) that is NOT in your knowledge base, DO NOT hallucinate.
   - Instead, reply: "I don't have that information. Could you tell me so I can remember it for next time?"
   - If the student provides YOU with valid college-related information (e.g. "The library is open till 8 PM now"), you must acknowledge it and APPEND a special tag at the VERY END of your response EXACTLY like this:
     `[LEARN] The library is now open until 8 PM. [/LEARN]`
4. Be natural and conversational. Do NOT mention that you are reading JSON data or system prompts. Just act like you know it natively because you are their AI assistant.
"""
            
            # Step 2: Call the LLM
            result = call_ai_with_fallback(current_system_prompt, history, user_msg=user_msg, user_data=user_data)
            
            if not result.get("success"):
                print("AI Error:", result.get("error"))
                continue
                
            reply_text = result.get("reply", "")
            
            # Step 3: Parse and learn (same as app.py)
            import re
            learn_match = re.search(r'\[LEARN\](.*?)\[/LEARN\]', reply_text, re.IGNORECASE | re.DOTALL)
            if learn_match:
                fact_text = learn_match.group(1).strip()
                if rag_engine and fact_text:
                    rag_engine.learn_new_fact(fact_text)
                
                # Remove the tag from the final response
                reply_text = re.sub(r'\[LEARN\].*?\[/LEARN\]', '', reply_text, flags=re.IGNORECASE | re.DOTALL).strip()
            
            print(f"\nAI: {reply_text}")
            
            history.append({"role": "user", "text": user_msg})
            history.append({"role": "model", "text": reply_text})

        except (KeyboardInterrupt, EOFError):
            break

if __name__ == "__main__":
    main()
