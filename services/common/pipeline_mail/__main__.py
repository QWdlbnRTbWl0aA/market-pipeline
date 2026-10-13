"""Explicit delivery-only recovery. Unknown SMTP outcomes may duplicate mail."""
import argparse
import json
import re
from pathlib import Path
from . import read,write,tick

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--outbox',required=True);parser.add_argument('--recover',required=True);parser.add_argument('--reason',required=True)
parser.add_argument('--confirm-unknown',action='store_true')
args=parser.parse_args()
if not re.fullmatch('[a-f0-9]{64}',args.recover) or not args.reason.strip():parser.error('Saved mail identity and audit reason required')
folder=Path(args.outbox)/args.recover;state=read(folder/'delivery.json')
if state['status']=='accepted_by_smtp':parser.error('Completed mail cannot be resent')
if state['status'] in ('unknown','partially_delivered') and not args.confirm_unknown:parser.error('Check SMTP/provider records first; explicit --confirm-unknown acknowledges possible duplicates')
write(folder/f'recovery-{state.get("total_attempts",state["attempts"]):04d}.json',{'previous_state':state,'reason':args.reason,'duplicate_risk_acknowledged':args.confirm_unknown})
state.update(status='pending',attempts=0,next_attempt_at=0);write(folder/'delivery.json',state)
print(json.dumps(tick(args.outbox,read(folder/'content.json')['mail_policy'],mail_id=args.recover)))
