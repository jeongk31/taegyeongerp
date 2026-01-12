import os
import sys
from app import create_app

# Print startup info for debugging
print(f"Python version: {sys.version}", flush=True)
print(f"PORT environment variable: {os.environ.get('PORT', 'NOT SET')}", flush=True)
print(f"SUPABASE_DB_URL set: {'Yes' if os.environ.get('SUPABASE_DB_URL') else 'No'}", flush=True)

try:
    app = create_app()
    print("Flask app created successfully", flush=True)
except Exception as e:
    print(f"ERROR creating Flask app: {e}", flush=True)
    import traceback
    traceback.print_exc()
    raise

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
