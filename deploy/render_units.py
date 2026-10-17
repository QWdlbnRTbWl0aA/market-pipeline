#!/usr/bin/env python3
import argparse
from pathlib import Path
from unit_templates import SPECS,render

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Render systemd units; does not install or start them')
    parser.add_argument('--output',required=True)
    parser.add_argument('--with-mail',action='store_true',help='Expose dedicated SMTP credential to Market Analyst and Product only')
    parser.add_argument('--with-product-paid',action='store_true',help='Give Product its own OpenAI credential delivery and access to the shared paid ledger')
    parser.add_argument('--with-studio-ai',action='store_true',help='Give Studio only its dedicated OpenAI credential; does not enable generation or budgets')
    parser.add_argument('--with-studio-google',action='store_true',help='Give Studio its optional Nano Banana credential; no provider calls')
    args=parser.parse_args();target=Path(args.output);target.mkdir(parents=True,exist_ok=True)
    for name in SPECS:(target/f'market-pipeline-{name}.service').write_text(render(name,mail=args.with_mail,product_paid=args.with_product_paid,studio_ai=args.with_studio_ai,studio_google=args.with_studio_google))
