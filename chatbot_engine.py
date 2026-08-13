# Samvidha AI - Natural Offline Chatbot Engine
# This engine uses HuggingFace 'transformers' to run a local AI model.
# It talks naturally to users and requires NO INTERNET after the first run.
#
# REQUIRED LIBRARIES:
# Run this in your terminal: pip install transformers torch

from transformers import pipeline

class SamvidhaBot:
    def __init__(self):
        print("Loading Samvidha AI Offline Model... (This takes a moment)")
        
        # We use a lightweight, natural conversational model from Facebook.
        # It downloads once, and then runs completely offline!
        self.chatbot = pipeline("conversational", model="facebook/blenderbot-400M-distill")
        
        # We keep track of the conversation so the bot remembers the context
        self.conversations = {}

    def get_response(self, user_id, user_message):
        # Import Conversation here to avoid global scope issues if not fully loaded
        from transformers import Conversation
        
        # Check if this user already has an active conversation history
        if user_id not in self.conversations:
            self.conversations[user_id] = Conversation()
            
        conv = self.conversations[user_id]
        
        # Add the user's new message to the conversation
        conv.add_user_input(user_message)
        
        # Generate the AI's response offline
        result = self.chatbot(conv)
        
        # Return the AI's latest reply
        reply = result.generated_responses[-1]
        return reply

# --- FLASK INTEGRATION EXAMPLE ---
# To integrate this into your app.py, simply do:
#
# from chatbot_engine import SamvidhaBot
# bot = SamvidhaBot()
#
# @app.route('/chatbot', methods=['POST'])
# def chatbot_endpoint():
#     data = request.json
#     user_msg = data.get('message', '')
#     
#     # We use "default_user" since we just want a simple chat. 
#     # If you have login tokens, you can pass the roll_number here instead!
#     reply = bot.get_response("default_user", user_msg)
#     
#     return jsonify({"success": True, "reply": reply})
