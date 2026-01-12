"""Ultra-simple test server to verify Railway connectivity"""
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        print(f"Received request: {self.path}", flush=True)
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Hello from Railway! App is reachable.")

    def log_message(self, format, *args):
        print(f"REQUEST: {format % args}", flush=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting simple HTTP server on port {port}", flush=True)
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    print(f"Server listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()
