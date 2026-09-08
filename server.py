from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8100


def main():
    site_directory = Path(__file__).resolve().parent
    handler = partial(SimpleHTTPRequestHandler, directory=str(site_directory))
    server = ThreadingHTTPServer((HOST, PORT), handler)

    print(f"Serving Atlas from {site_directory}")
    print(f"Open http://localhost:{PORT}/")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
