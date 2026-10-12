"""One-dollar Studio development envelope, persisted across products/restarts.

Integer microdollars; unknown outcomes stay charged and stop all new calls.
Never reset this ledger to replenish a development period.
"""
from .storage import guard, read, write, now, Invalid

LIMIT = 1_000_000


class BudgetBlocked(Invalid): pass


class Budget:
    def __init__(self, root): self.root=root
    def reserve(self, identity, product, maximum, stage):
        with guard(self.root):
            path=self.root/'budget.json'; ledger=read(path) if path.exists() else {'limit_micro_usd':LIMIT,'calls':{}}
            if ledger.get('limit_micro_usd') != LIMIT: raise BudgetBlocked('Studio budget ledger requires reconciliation')
            if any(c['status']!='completed' for c in ledger['calls'].values()): raise BudgetBlocked('Unknown API outcome; explicit reconciliation required')
            if identity in ledger['calls']: raise BudgetBlocked('Request already reserved; recover saved response')
            if type(maximum) is not int or maximum<=0 or sum(c['charged_micro_usd'] for c in ledger['calls'].values())+maximum>LIMIT:
                raise BudgetBlocked('תקציב הפיתוח אינו מספיק לבקשה נוספת; המשוב נשמר.')
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
            return {'limit_usd':1.0,'charged_or_reserved_usd':charged/1e6,'remaining_usd':max(0,LIMIT-charged)/1e6,
                    'product_usd':sum(c['charged_micro_usd'] for c in own)/1e6,'product_calls':len(own),
                    'unknown_outcomes':sum(c['status']!='completed' for c in rows)}
