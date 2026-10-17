import argparse
import logging
import signal
import threading
from .core import Studio
from .server import Server, configuration


def main():
    parser = argparse.ArgumentParser(description='Independent Studio and approval dashboard')
    parser.add_argument('action', choices=('serve', 'tick','authorize-budget'))
    parser.add_argument('--data', required=True); parser.add_argument('--config')
    parser.add_argument('--host', default='127.0.0.1'); parser.add_argument('--port', type=int, default=8096)
    parser.add_argument('--prior-total-usd',type=float);parser.add_argument('--total-usd',type=float);parser.add_argument('--reason');parser.add_argument('--initialize-empty',action='store_true')
    args = parser.parse_args(); logging.basicConfig(level=logging.INFO)
    if args.action=='authorize-budget':
        from .dev_budget import Budget
        from pathlib import Path
        if args.total_usd is None or not args.reason:parser.error('Explicit --total-usd and --reason required; preserve the existing Studio data root')
        Budget(Path(args.data)/'development-openai').authorize(args.total_usd,args.reason,args.initialize_empty,args.prior_total_usd)
        print('Budget authorization saved with existing charges/reservations. Update trial_total_usd and explicitly restart the affected Studio before use.');return
    config = configuration(args.config)
    providers={}
    if config['broker_provider']=='file':
        from pathlib import Path
        from .adapters import FileBroker
        providers['broker']=FileBroker(Path(args.data)/'broker-inbox')
    if config['development_openai']:
        from .openai_dev import OpenAIDev
        paid=OpenAIDev(args.data,limit_usd=config['trial_total_usd']);providers['understanding']=paid
        from .providers import OpenAIStudio,GeminiStudio,Comparison
        providers['copywriter']=OpenAIStudio(args.data,limit_usd=config['trial_total_usd'])
        if config['lifestyle_mockups']:
            providers['mockup_planner']=providers['copywriter']
            providers['mockup_drafts']=OpenAIStudio(args.data,limit_usd=config['trial_total_usd'],image_model=config['draft_model'])
            providers['mockup_finals']=OpenAIStudio(args.data,limit_usd=config['trial_total_usd'],image_model=config['mockup_final_model'])
        for key in ('sketches','professional'):
            option='sketch_provider' if key=='sketches' else 'professional_provider'
            if config[option]=='openai_dev':providers[key]=paid
            elif config[option]=='openai':providers[key]=OpenAIStudio(args.data,limit_usd=config['trial_total_usd'],image_model=config['draft_model' if key=='sketches' else 'professional_model'])
            elif config[option]=='gemini':providers[key]=GeminiStudio(args.data,limit_usd=config['trial_total_usd'],observer=paid)
            elif config[option]=='comparison':providers[key]=Comparison(OpenAIStudio(args.data,limit_usd=config['trial_total_usd']),GeminiStudio(args.data,limit_usd=config['trial_total_usd'],observer=paid))
    studio = Studio(args.data,development=config['development_openai'],budget_limit_usd=config['trial_total_usd'],**providers)
    if args.action == 'tick': studio.tick(); return
    server = Server((args.host, args.port), studio, config)
    def stop(*_): threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    server.start_worker()
    try: server.serve_forever(poll_interval=0.2)
    finally: server.server_close()


if __name__ == '__main__': main()
