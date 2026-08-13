import json
from rag_engine import UnifiedRAG

def test():
    print("Initializing Unified RAG Engine...")
    rag = UnifiedRAG()
    
    # Mock user data for testing dynamic RAG
    mock_user_data = {
        "profile": {"name": "Test User", "roll_number": "12345", "branch": "CSE"},
        "attendance": {"percentage": 85, "classes": [{"subject": "Math", "status": "present"}]},
        "timetable": {"today": [{"time": "10:00 AM", "subject": "Math"}]}
    }
    
    print("\n" + "="*50)
    print("Welcome to the UnifiedRAG testing console!")
    print("Type 'exit' or 'quit' to stop.")
    print("="*50)
    
    while True:
        try:
            query = input("\nEnter your query: ").strip()
            if query.lower() in ['exit', 'quit']:
                break
            if not query:
                continue
                
            print("-" * 50)
            context = rag.build_prompt_context(query, user_data=mock_user_data)
            
            if not context.strip():
                print("No relevant context found across any dataset.")
            else:
                print("--- INJECTED CONTEXT ---")
                print(context)
                print("------------------------")
            
            print("="*50)
        except (KeyboardInterrupt, EOFError):
            break


if __name__ == "__main__":
    test()
