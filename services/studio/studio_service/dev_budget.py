"""Explicit Studio envelope, persisted across products/restarts (legacy default $1).

Integer microdollars; unknown outcomes stay charged and stop all new calls.
Never reset this ledger to replenish a development period.
"""
from .storage import guard, read, write, now, Invalid
import math

LIMIT = 1_000_000
ALLOCATIONS={'comparison':4_000_000,'production':10_000_000,'mockups':3_000_000,'listing':2_000_000,'trial':6_000_000}


def group(stage):
    return 'production' if stage=='production_artwork' else 'listing' if stage=='listing_copy' else 'comparison' if stage in ('direction_generation','direction_edit','model_comparison','draft_generation') else 'trial'


class BudgetBlocked(Invalid): pass


class Budget:
    def __init__(self, root, limit_usd=1):
        if type(limit_usd) not in (int,float) or not math.isfinite(limit_usd) or not 0<limit_usd<=25:raise BudgetBlocked('Studio trial ceiling cannot exceed $25')
        self.root=root;self.limit=round(limit_usd*1e6)
    def authorize(self, total_usd, reason, initialize_empty=False, prior_total_usd=None):
        target=Budget(self.root,total_usd).limit
        if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise BudgetBlocked('Record the explicit budget authorization')
        with guard(self.root):
            path=self.root/'budget.json'
            if not path.exists() and not initialize_empty:raise BudgetBlocked('Use the existing ledger; explicitly initialize only when there is no prior Studio usage')
            ledger=read(path) if path.exists() else {'limit_micro_usd':LIMIT,'calls':{}}
            charged=sum(c['charged_micro_usd'] for c in ledger['calls'].values())
            if prior_total_usd is not None:
                if type(prior_total_usd) not in (int,float) or not math.isfinite(prior_total_usd) or prior_total_usd<0:raise BudgetBlocked('Invalid confirmed prior Studio total')
                confirmed=round(prior_total_usd*1e6)
                if any(c['status']!='completed' for c in ledger['calls'].values()):raise BudgetBlocked('Reconcile unknown outcomes before recording prior spend')
                if confirmed<charged:raise BudgetBlocked('Confirmed total cannot erase preserved charges')
                if confirmed>charged:
                    identifier='prior-usage-'+str(len(ledger['calls']))
                    ledger['calls'][identifier]={'product_id':'prior-studio-use','stage':'prior_usage','at':now(),'maximum_micro_usd':confirmed-charged,
                        'charged_micro_usd':confirmed-charged,'status':'completed','usage':{'source':'explicit_user_confirmed_total','reason':reason}}
                charged=confirmed
            if target<charged:raise BudgetBlocked('Limit is below preserved charges/reservations')
            ledger.setdefault('authorization_history',[]).append({'at':now(),'previous_limit_micro_usd':ledger['limit_micro_usd'],'new_limit_micro_usd':target,'reason':reason})
            ledger['limit_micro_usd']=target;write(path,ledger)
    def reserve(self, identity, product, maximum, stage):
        with guard(self.root):
            path=self.root/'budget.json'
            if not path.exists() and self.limit!=LIMIT:raise BudgetBlocked('Authorize the trial ledger explicitly and carry forward all prior Studio spend before use')
            ledger=read(path) if path.exists() else {'limit_micro_usd':self.limit,'calls':{}}
            if ledger.get('limit_micro_usd') != self.limit: raise BudgetBlocked('Budget policy differs from saved ledger; explicit authorization/migration required')
            if any(c['status']!='completed' for c in ledger['calls'].values()): raise BudgetBlocked('Unknown API outcome; explicit reconciliation required')
            if identity in ledger['calls']: raise BudgetBlocked('Request already reserved; recover saved response')
            if type(maximum) is not int or maximum<=0 or sum(c['charged_micro_usd'] for c in ledger['calls'].values())+maximum>self.limit:
                raise BudgetBlocked('תקציב הפיתוח אינו מספיק לבקשה נוספת; המשוב נשמר.')
            category=group(stage)
            if self.limit==25_000_000 and sum(c['charged_micro_usd'] for c in ledger['calls'].values() if group(c['stage'])==category)+maximum>ALLOCATIONS[category]:
                raise BudgetBlocked('Stage reservation exceeds the approved trial allocation; no request sent')
            ledger['calls'][identity]={'product_id':product,'stage':stage,'at':now(),'maximum_micro_usd':maximum,
                                       'charged_micro_usd':maximum,'status':'reserved_unknown'}
            write(path,ledger)
    def settle(self, identity, actual, usage):
        with guard(self.root):
            path=self.root/'budget.json';ledger=read(path);row=ledger['calls'][identity]
            if type(actual) is not int or actual<0: raise BudgetBlocked('Invalid provider accounting')
            row.update(charged_micro_usd=actual,usage=usage,status='completed' if actual<=row['maximum_micro_usd'] else 'usage_exceeded_reservation')
            write(path,ledger)
            if row['status']!='completed':raise BudgetBlocked('Provider usage exceeded reservation; no further requests admitted')
    def summary(self, product):
        with guard(self.root):
            path=self.root/'budget.json';ledger=read(path) if path.exists() else {'calls':{}}
            rows=list(ledger['calls'].values());own=[c for c in rows if c['product_id']==product]
            charged=sum(c['charged_micro_usd'] for c in rows)
            active=ledger.get('limit_micro_usd',self.limit)
            return {'limit_usd':active/1e6,'configured_limit_usd':self.limit/1e6,'authorization_required':active!=self.limit or (not path.exists() and self.limit!=LIMIT),'charged_or_reserved_usd':charged/1e6,'remaining_usd':max(0,min(active,self.limit)-charged)/1e6,
                    'product_usd':sum(c['charged_micro_usd'] for c in own)/1e6,'product_calls':len(own),
                    'unknown_outcomes':sum(c['status']!='completed' for c in rows)}
