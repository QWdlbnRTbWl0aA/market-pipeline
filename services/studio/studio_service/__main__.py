import argparse
import logging
import signal
import threading
from .core import Studio
from .server import Server, configuration


def main():
    parser = argparse.ArgumentParser(description='Independent mock Studio and approval dashboard')
    parser.add_argument('action', choices=('serve', 'tick'))
    parser.add_argument('--data', required=True); parser.add_argument('--config')
    parser.add_argument('--host', default='127.0.0.1'); parser.add_argument('--port', type=int, default=8096)
    args = parser.parse_args(); logging.basicConfig(level=logging.INFO)
    config = configuration(args.config)
    providers={}
    if config['development_openai']:
        from .openai_dev import OpenAIDev
        paid=OpenAIDev(args.data);providers['understanding']=paid
        for key in ('sketches','professional'):
            option='sketch_provider' if key=='sketches' else 'professional_provider'
            if config[option]=='openai_dev':providers[key]=paid
    studio = Studio(args.data,development=config['development_openai'],**providers)
    if args.action == 'tick': studio.tick(); return
    server = Server((args.host, args.port), studio, config)
    def stop(*_): threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    server.start_worker()
    try: server.serve_forever(poll_interval=0.2)
    finally: server.server_close()


if __name__ == '__main__': main()
