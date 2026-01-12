"""Gunicorn configuration for Railway deployment"""
import multiprocessing
import os

# Bind to Railway's PORT environment variable
port = os.environ.get('PORT', '8080')
bind = f"0.0.0.0:{port}"
print(f"Gunicorn will bind to: {bind}", flush=True)

# Worker configuration
workers = 1  # Use single worker for debugging
worker_class = "sync"
threads = 1  # Single thread for simplicity
timeout = 120  # Increased timeout for slow database queries
keepalive = 5

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = "debug"  # More verbose logging
capture_output = True

# Worker lifecycle hooks
def on_starting(server):
    print("Gunicorn server starting", flush=True)

def when_ready(server):
    print("Gunicorn server ready to accept connections", flush=True)

def pre_request(worker, req):
    print(f"[{worker.pid}] Handling request: {req.method} {req.path}", flush=True)

def post_request(worker, req, environ, resp):
    print(f"[{worker.pid}] Completed request: {req.method} {req.path} -> {resp.status}", flush=True)

def worker_abort(worker):
    print(f"Worker {worker.pid} aborted (likely timeout)", flush=True)
