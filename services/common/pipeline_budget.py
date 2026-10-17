"""Persisted, cross-process paid-call admission. Unknown outcomes keep reservations."""
import datetime as dt
import fcntl
import json
from pathlib import Path
from pipeline_mail import write as write_json
import datetime as _datetime
def now():return _datetime.datetime.now(_datetime.timezone.utc).isoformat()

class BudgetExceeded(RuntimeError): pass

class Budget:
    def __init__(self, root, daily, total, calls, development=None, allow_held_unknown=False):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.daily,self.total,self.calls=daily,total,calls
        self.development=development
        if type(allow_held_unknown) is not bool:raise ValueError('Explicit held-reservation policy required')
        self.allow_held_unknown=allow_held_unknown
    def reserve(self, identity, maximum, experiment_id=None, experiment_limit=4):
        with (self.root/'budget.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            path=self.root/'budget.json'
            ledger=json.loads(path.read_text()) if path.exists() else {'calls':{}}
            unknown=[x for x in ledger['calls'].values() if x['status']=='reserved_unknown']
            if unknown:
                # Explicit opt-in permits NEW identities only, with every unknown
                # call still charged at its full conservative maximum. It never
                # releases a reservation or permits retrying the same identity.
                import math
                fully_held=all(type(x.get('maximum_usd')) in (int,float) and math.isfinite(x['maximum_usd']) and x['maximum_usd']>=0
                    and type(x.get('charged_usd')) in (int,float) and math.isfinite(x['charged_usd']) and x['charged_usd']>=x['maximum_usd'] for x in unknown)
                if not self.allow_held_unknown or not fully_held:
                    raise BudgetExceeded('Unknown paid outcome requires explicit reconciliation; no request sent')
            if ledger.get('blocked'):raise BudgetExceeded('Paid API admission blocked; explicit reconciliation required')
            if ledger.get('cooldown_until') and dt.datetime.now(dt.timezone.utc)<dt.datetime.fromisoformat(ledger['cooldown_until']):raise BudgetExceeded('Provider cooldown active; no request sent')
            if any(x['status']=='usage_exceeded_reservation' for x in ledger['calls'].values()):raise BudgetExceeded('Paid budget tripped; explicit reconciliation required')
            if identity in ledger['calls']:raise BudgetExceeded('Paid request already reserved; explicit reconciliation required')
            today=now()[:10];entries=list(ledger['calls'].values())
            if self.development:
                key=self.development['id'];envelopes=ledger.setdefault('development_envelopes',{})
                existing=envelopes.get(key)
                if existing and existing['total_usd']!=self.development['total_usd']:raise BudgetExceeded('Development envelope cannot be reset or enlarged')
                used=sum(x['charged_usd'] for x in entries if x.get('development_id')==key)
                if used+maximum>self.development['total_usd']+1e-9:raise BudgetExceeded('Development envelope exhausted; no request sent')
                envelopes[key]={'total_usd':self.development['total_usd']}
            if experiment_id and sum(x.get('experiment_id') == experiment_id for x in entries) >= min(4, experiment_limit):
                raise BudgetExceeded('Experiment paid-call ceiling exhausted; no request sent')
            cost=sum(x['charged_usd'] for x in entries)
            day=[x for x in entries if x['at'][:10]==today]
            experiments = ledger.get('experiments', {})
            own = experiments.get(experiment_id)
            if own and own['status'] == 'reserved':
                own_entries = [x for x in entries if x.get('experiment_id') == experiment_id]
                if ((self.daily is not None or self.calls is not None) and own['day'] != today) or sum(x['charged_usd'] for x in own_entries)+maximum > own['maximum_usd']+1e-9:
                    raise BudgetExceeded('Trial paid reservation expired or exceeds its envelope; reconcile before admission')
            other = [r for k,r in experiments.items() if r['status']=='reserved' and k != experiment_id]
            def remaining(r):
                used=[x for x in entries if x.get('experiment_id')==r['experiment_id']]
                return max(0,r['maximum_usd']-sum(x['charged_usd'] for x in used)),max(0,r['maximum_calls']-len(used))
            future=sum(remaining(r)[0] for r in other)
            future_day=sum(remaining(r)[0] for r in other if r['day']==today)
            future_calls=sum(remaining(r)[1] for r in other if r['day']==today)
            if cost+future+maximum>self.total+1e-9 or (self.daily is not None and sum(x['charged_usd'] for x in day)+future_day+maximum>self.daily+1e-9) or (self.calls is not None and len(day)+future_calls>=self.calls):
                raise BudgetExceeded('Shared paid-call budget exhausted; no request sent')
            ledger['calls'][identity]={'at':now(),'maximum_usd':maximum,'charged_usd':maximum,'status':'reserved_unknown','experiment_id':experiment_id,
                                       'development_id':self.development['id'] if self.development else None}
            write_json(path,ledger)
    def settle(self, identity, actual, usage):
        with (self.root/'budget.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);path=self.root/'budget.json';ledger=json.loads(path.read_text())
            entry=ledger['calls'][identity]
            if actual>entry['maximum_usd']+1e-9:
                entry.update(status='usage_exceeded_reservation',charged_usd=actual,usage=usage)
                write_json(path,ledger);raise BudgetExceeded('Provider usage exceeded conservative reservation; investigate before further calls')
            entry.update(status='completed',charged_usd=actual,usage=usage);write_json(path,ledger)

    def provider_block(self,status,retry_seconds=None):
        with (self.root/'budget.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);path=self.root/'budget.json';ledger=json.loads(path.read_text())
            if status in (401,403):ledger['blocked']='provider_auth_or_access_challenge'
            elif status==429:
                until=dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=max(60,retry_seconds or 0))
                ledger['cooldown_until']=until.isoformat()
            write_json(path,ledger)
