#!/usr/bin/env python3
import argparse
from pathlib import Path
from unit_templates import SPECS,render

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Render systemd units; does not install or start them')
    parser.add_argument('--output',required=True)
    parser.add_argument('--with-mail',action='store_true',help='Expose dedicated SMTP credential to Market Analyst and Product only')
    args=parser.parse_args();target=Path(args.output);target.mkdir(parents=True,exist_ok=True)
    for name in SPECS:(target/f'market-pipeline-{name}.service').write_text(render(name,mail=args.with_mail))
