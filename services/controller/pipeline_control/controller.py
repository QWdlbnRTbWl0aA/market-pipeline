"""Passive refinement controller. Only exact reviewed, bounded experiments execute."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
import urllib.request
from .storage import clean_environment, digest, event, Guard, identity, local_url, LocalHTTP, now, read, run_identity, write

VERSION = 'bounded-refinement-v1.2'


def phrase(value):
    if not isinstance(value, str): raise ValueError('Keyword phrase required')
    value = ' '.join(value.casefold().split())
    if not 2 <= len(value) <= 160 or re.search(r'[\x00-\x1f<>`$;{}\\]', value): raise ValueError('Unsafe or unsupported phrase')
    return value


def config(path):
    clean_environment(); value = read(path)
    required = {'data_root', 'saved_runs_root', 'analyzer_output_root', 'product_data_root', 'collector_url', 'control_auth_file', 'execution_enabled', 'poll_seconds', 'paid_ledger_root', 'paid_policy', 'product_url'}
    if set(value) != required or type(value['execution_enabled']) is not bool: raise ValueError('Independent explicit controller configuration required')
    local_url(value['collector_url']); local_url(value['product_url'])
    if value['paid_policy'] != {'daily_usd':None,'total_usd':2.0,'daily_calls':None}: raise ValueError('Development/testing requires the approved $2 total envelope without daily caps')
    if type(value['poll_seconds']) is not int or not 1 <= value['poll_seconds'] <= 60: raise ValueError('Invalid polling bound')
    root, source = Path(value['data_root']).resolve(), Path(value['saved_runs_root']).resolve()
    if root == source or root.is_relative_to(source) or source.is_relative_to(root): raise ValueError('Separate controller output required')
    return value


class Controller:
    def __init__(self, settings, transport=None):
        clean_environment(); self.settings = settings; self.root = Path(settings['data_root'])
        self.source = Path(settings['saved_runs_root']).resolve(); self.transport = transport or LocalHTTP()
        self.root.mkdir(parents=True, exist_ok=True)

    def source_snapshot(self, run_id):
        run_identity(run_id); path = self.source / run_id / 'snapshot.json'
        if path.resolve().parent.parent != self.source: raise ValueError('Source escape')
        value = read(path, 100_000_000)
        if value.get('run_id') != run_id or value.get('status') != 'success' or not value.get('finished_at'):
            raise ValueError('Finalized successful source required')
        if value.get('mode') == 'tracking' or value.get('trigger') == 'count-probe': raise ValueError('Tracking/probes cannot create refinement loops')
        if read(path.parent / 'dqa.json') != value.get('dqa'): raise ValueError('Incomplete DQA finalization')
        return value, hashlib.sha256(path.read_bytes()).hexdigest()

    def receive(self, body):
        if not 0 < len(body) <= 5_000_000: raise ValueError('Bounded report required')
        payload = json.loads(body)
        from .storage import reject_secrets
        reject_secrets(payload)
        key = identity(payload.get('delivery_id'))
        if payload.get('service') != 'search_refinement' or payload.get('schema_version') != 1:
            raise ValueError('Compatible saved search-refinement report required')
        envelope = payload.get('envelope') or {}
        if envelope and (envelope.get('schema_version') != 1 or envelope.get('event_type') != 'analysis_completed'):
            raise ValueError('Unsupported envelope version')
        with Guard(self.root):
            path = self.root / 'inbox' / (key + '.json'); sha = hashlib.sha256(body).hexdigest()
            if path.exists():
                if read(path)['sha256'] != sha: raise ValueError('Delivery identity collision')
                return {'accepted': True, 'duplicate': True, 'delivery_id': key}
            # Write before acknowledgment; proposal preparation is independent.
            write(path, {'sha256': sha, 'received_at': now(), 'payload': payload})
            event(self.root, 'refinement_received', key, {'source_run_id': payload.get('source_run_id')})
        return {'accepted': True, 'duplicate': False, 'delivery_id': key}

    def prepare(self, key):
        identity(key)
        with Guard(self.root):
            target = self.root / 'proposals' / (key + '.json')
            if target.exists():
                previous = read(target)
                if previous.get('manifest', {}).get('recipe') == VERSION or previous.get('status') not in ('awaiting_approval','no_supported_proposal'):
                    return previous
                write(self.root / 'proposal-history' / key / (previous['manifest_sha256'] + '.json'), previous)
            report = read(self.root / 'inbox' / (key + '.json'))['payload']
            if report.get('status') != 'completed':
                row = {'proposal_id': key, 'status': 'ignored_failed_analysis', 'source_run_id': report.get('source_run_id')}
                write(target, row); return row
            source, sha = self.source_snapshot(report['source_run_id'])
            if report.get('source', {}).get('input_sha256') != sha: raise ValueError('Report source checksum does not match saved snapshot')
            lineage = source.get('lineage') or {}
            if lineage.get('iteration', 0) >= 1:
                row = {'proposal_id': key, 'status': 'iteration_limit', 'source_run_id': source['run_id']}
                write(target, row); return row
            originals = [phrase(n['keywords']) for n in source['settings']['niches']]
            citations = {str(r['listing_id']) for q in source.get('queries', []) for r in q.get('listings', [])}
            proposed, rejected = [], []
            for row in report.get('report', {}).get('recommendations', [])[:12]:
                try:
                    if not isinstance(row, dict): raise ValueError('Structured evidence-linked recommendation required')
                    excerpts = row.get('evidence_excerpts') or []
                    refs = row.get('evidence_ids') or []
                    if not refs or not excerpts or set(refs) - {e.get('evidence_id') for e in excerpts}: raise ValueError('Missing evidence references')
                    if any(str(e.get('listing_id', e.get('id', ''))).removeprefix('etsy:listing:') not in citations for e in excerpts): raise ValueError('Unknown listing citation')
                    query = phrase(row.get('alternative_keywords') or row.get('keywords'))
                    if query in originals or query in [r['keywords'] for r in proposed]: raise ValueError('Equivalent/original query')
                    linked = {str(e.get('listing_id',e.get('id',''))).removeprefix('etsy:listing:') for e in excerpts}
                    scores = {phrase(q['niche']['keywords']): len(linked & {str(r['listing_id']) for r in q.get('listings',[])}) for q in source['queries']}
                    best = max(scores.values(), default=0)
                    parents = [p for p,n in scores.items() if n == best and best > 0]
                    if not parents: raise ValueError('No cited parent query lineage')
                    parent = max(parents, key=lambda p: len(set(p.split()) & set(query.split())))
                    anchors = set(parent.split()) - {'printable','digital','download','template','jewish','holiday'}
                    if anchors and not (anchors & set(query.split())): raise ValueError('Refined phrase lost every parent intent anchor; requires a separately reviewed search')
                    proposed.append({'keywords': query, 'parent_keywords': parent, 'rationale': str(row.get('rationale', ''))[:3000],
                                     'listing_ids': [str(e.get('listing_id', e.get('id'))).removeprefix('etsy:listing:') for e in excerpts]})
                    if len(proposed) == 2: break
                except (ValueError, TypeError, KeyError) as error:
                    rejected.append({'reason': str(error), 'candidate_id': row.get('candidate_id') if isinstance(row, dict) else None})
            queries = list(dict.fromkeys([r['parent_keywords'] for r in proposed] + [r['keywords'] for r in proposed]))
            manifest = {'schema_version': 1, 'recipe': VERSION, 'proposal_id': key, 'source_run_id': source['run_id'], 'source_sha256': sha,
                        'root_cycle_id': lineage.get('root_cycle_id', source['run_id']), 'parent_run_id': source['run_id'], 'iteration': 1,
                        'phrases': proposed, 'rejected': rejected, 'searches': queries, 'shop_ids': list(source['settings'].get('shop_ids', [])),
                        'limits': {'results_per_phrase': 100, 'max_pages': 1, 'max_shops': 10, 'max_requests': 25, 'max_paid_calls': 4, 'paid_reservation_maximum_usd': .4284, 'iterations': 1},
                        'exclusions': {'exclude_fetched_listings': False, 'exclude_fetched_shops': False},
                        'comparison_policy': {'minimum_relevance_gain': .10, 'maximum_contamination_increase': 0, 'human_reference_required': True, 'human_sample_per_phrase': 10, 'sample_method': 'Stable listing-ID hash, up to ten unique identities per phrase; disclosed nonrepresentative reference sample'},
                        'review_rubric': 'Same bounded raw samples, blind reviewed printable relevance labels; novelty is not relevance.',
                        'created_at': now()}
            if len(queries) * max(1, len(manifest['shop_ids'])) + 10 > 25: raise ValueError('Chosen shops exceed experiment request envelope')
            row = {'proposal_id': key, 'source_run_id': source['run_id'], 'status': 'awaiting_approval' if proposed else 'no_supported_proposal',
                   'manifest': manifest, 'manifest_sha256': digest(manifest), 'approval': None}
            write(target, row); event(self.root, 'refinement_proposed', key, {'manifest_sha256': row['manifest_sha256'], 'status': row['status']})
            return row

    def decide(self, key, action, expected, reviewer, reference=None):
        identity(key)
        if action not in {'approve', 'reject', 'pause', 'cancel'} or not isinstance(reviewer, str) or not reviewer.strip(): raise ValueError('Explicit operator decision required')
        with Guard(self.root):
            path = self.root / 'proposals' / (key + '.json'); row = read(path)
            if expected != row.get('manifest_sha256'): raise ValueError('Manifest changed; review exact current parameters')
            if row['status'] in {'submitting', 'submitted', 'completed', 'submission_unknown'}: raise ValueError('Submitted experiments cannot be replayed or cancelled as unsent')
            if row['status'] == 'approved' and action == 'approve': return row
            if action == 'approve':
                if not row['manifest']['phrases']: raise ValueError('No supported phrase')
                if not isinstance(reference, dict) or set(reference) != {'rubric_accepted', 'minimum_relevance_gain', 'reference_listing_ids'} or reference['rubric_accepted'] is not True or reference['minimum_relevance_gain'] != row['manifest']['comparison_policy']['minimum_relevance_gain']:
                    raise ValueError('Approve the relevance rubric and named saved reference sample')
                known = {v for p in row['manifest']['phrases'] for v in p['listing_ids']}
                if not reference['reference_listing_ids'] or set(reference['reference_listing_ids']) - known: raise ValueError('Unknown human reference identities')
                # One approved follow-up per root, even when reports/configurations change.
                marker = self.root / 'roots' / (digest(row['manifest']['root_cycle_id']) + '.json')
                if marker.exists() and read(marker)['proposal_id'] != key: raise ValueError('Root cycle already has a reserved follow-up')
                write(marker, {'proposal_id': key, 'manifest_sha256': expected})
                row['approval'] = {'by': reviewer[:100], 'at': now(), 'manifest_sha256': expected, 'reference': reference,
                                   'expires_at': (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()}
            row['status'] = {'approve': 'approved', 'reject': 'rejected', 'pause': 'paused', 'cancel': 'cancelled'}[action]
            write(path, row); event(self.root, 'experiment_decided', key, {'action': action, 'by': reviewer[:100], 'manifest_sha256': expected})
            return row

    def submit(self, key):
        identity(key)
        with Guard(self.root):
            path = self.root / 'proposals' / (key + '.json'); row = read(path)
            if row['status'] in {'submitted', 'completed', 'submission_unknown', 'submitting'}: return row
            if not self.settings['execution_enabled']: raise ValueError('Controller execution disabled')
            approval = row.get('approval') or {}
            if row['status'] not in ('approved','budget_waiting') or approval.get('manifest_sha256') != digest(row['manifest']) or dt.datetime.now(dt.timezone.utc) >= dt.datetime.fromisoformat(approval['expires_at']): raise ValueError('Current exact unexpired approval required')
            if self.settings.get('paid_ledger_root'):
                from .admission import reserve
                try: row['paid_envelope'] = reserve(self.settings['paid_ledger_root'], key, self.settings['paid_policy'])
                except ValueError as error:
                    row.update(status='budget_waiting', reason=str(error)); write(path,row); return row
            m = row['manifest']; limit = m['limits']; slots = len(m['searches']) * max(1, len(m['shop_ids'])) + limit['max_shops']
            if slots > limit['max_requests']: raise ValueError('Request demand exceeds trial envelope')
            request = {'schema_version': 1, 'job_id': key, 'manifest_sha256': row['manifest_sha256'], 'kind': 'experiment',
                       'lineage': {k: m[k] for k in ('root_cycle_id', 'parent_run_id', 'iteration')} | {'experiment_id': key, 'max_paid_calls': limit['max_paid_calls']},
                       'parameters': {'niches': [{'category': 'Approved comparison', 'keywords': p} for p in m['searches']], 'limit': 100,
                                      'shop_ids': m['shop_ids'], **m['exclusions']},
                       'bounds': {'max_requests': slots, 'max_pages': 1, 'max_shops': limit['max_shops']},
                       'approval': {'manifest_sha256': row['manifest_sha256'], 'reviewed_by': approval['by'], 'expires_at': approval['expires_at']}}
            row.update(status='submitting', submission=request, reserved_requests=slots, reserved_paid_calls=4)
            write(path, row)  # Unknown network outcome can never trigger automatic resubmission.
            event(self.root, 'experiment_submission_reserved', key, {'requests': slots, 'paid_calls': 4})
        try:
            result = self.send_job(request); status = 'submitted'
        except Exception as error:
            result = {'error_type': type(error).__name__, 'automatic_retry': False}; status = 'submission_unknown'
        with Guard(self.root):
            row = read(path); row.update(status=status, collector_receipt=result, updated_at=now()); write(path, row)
            event(self.root, 'experiment_submitted', key, {'status': status, 'collector_receipt': result})
        return row

    def reconcile_submission(self,key):
        identity(key);path=self.root/'proposals'/(key+'.json')
        row=read(path)
        if row['status'] not in ('submission_unknown','submitting'):return row
        receipt=self.send_job(row['submission'],lookup=True)
        if receipt.get('request_sha256')!=digest(row['submission']):raise ValueError('Collector saved request checksum mismatch')
        run_identity(receipt.get('run_id'))
        with Guard(self.root):
            row=read(path)
            if row['status'] not in ('submission_unknown','submitting'):return row
            row.update(status='submitted',collector_receipt=receipt,reconciled_at=now());write(path,row)
            event(self.root,'experiment_submission_reconciled',key,{'run_id':receipt['run_id'],'source_calls':0})
        return row

    def send_job(self, request,lookup=False):
        import os, stat
        auth = Path(self.settings['control_auth_file'])
        fd = os.open(auth, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 256: raise ValueError('Dedicated owner-only control authentication file required')
            token = os.read(fd, 257).decode().strip()
            if not re.fullmatch('[a-f0-9]{64}', token): raise ValueError('Invalid dedicated control authentication')
        finally: os.close(fd)
        call = urllib.request.Request(local_url(self.settings['collector_url']) + '/api/control/jobs' + ('/'+request['job_id'] if lookup else ''), data=None if lookup else json.dumps(request).encode(),
                                      headers={'Content-Type': 'application/json', 'X-Pipeline-Control': token})
        with self.transport(call, timeout=10) as response:
            body = response.read(16385)
        if len(body) > 16384: raise ValueError('Collector receipt too large')
        result = json.loads(body)
        if result.get('job_id') != request['job_id']: raise ValueError('Collector receipt identity mismatch')
        return result

    def complete(self, key):
        path = self.root / 'proposals' / (key + '.json'); row = read(path)
        run_id = row.get('collector_receipt', {}).get('run_id')
        if not run_id: return row
        snapshot = self.source / run_identity(run_id) / 'snapshot.json'
        if not snapshot.exists(): return row
        source = read(snapshot, 100_000_000)
        if not source.get('finished_at'): return row
        if source.get('lineage',{}).get('experiment_id') != key: raise ValueError('Collector lineage collision')
        if source['status'] != 'success':
            row.update(status='collection_failed', source_run_id=run_id, stop_reason=source.get('stop_reason'), iterations_remaining=0)
        elif row.get('comparison') is None:
            from .comparison import compare
            result = compare(self.source,run_id,row['manifest'],self.root/'comparisons'/key)
            row.update(status='awaiting_human_labels', comparison=result, collected_run_id=run_id, iterations_remaining=0)
        write(path,row)
        if self.settings.get('paid_ledger_root'):
            states=[]
            for service in ('search_refinement','market_insights'):
                matching=[]
                for record in (Path(self.settings['analyzer_output_root'])/service).glob('*/state.json'):
                    value=read(record)
                    if value.get('source_run_id')==run_id and value.get('experiment_id')==key:matching.append(value)
                if matching:states.append(matching[-1])
            if len(states)==2 and all(s.get('analysis_status') in ('completed','failed','budget_waiting') and s.get('delivery_status')=='delivered' for s in states):
                from .admission import close
                close(self.settings['paid_ledger_root'],key)
        return row

    def labels(self,key,labels):
        identity(key)
        with Guard(self.root):
            path=self.root/'proposals'/(key+'.json');row=read(path)
            if row['status'] not in ('awaiting_human_labels','accepted','rejected_comparison'):raise ValueError('A completed trial is required')
            from .comparison import compare
            result=compare(self.source,row['collected_run_id'],row['manifest'],self.root/'comparisons'/key,labels)
            write(self.root/'label-reviews'/key/(digest(labels)+'.json'),labels)
            row.update(status=result['status'] if result['status']!='rejected' else 'rejected_comparison',comparison=result,iterations_remaining=0)
            write(path,row)
            if result['status']=='accepted':write(self.root/'qualifications'/(key+'.json'),result)
            event(self.root,'experiment_compared',key,{'status':result['status'],'snapshot_sha256':result['snapshot_sha256']})
            return row

    def qualified_delivery(self,key):
        row=read(self.root/'proposals'/(key+'.json'))
        if row['status']!='accepted' or not self.settings.get('product_url'):return
        folder=self.root/'qualified-outbox'/key;folder.mkdir(parents=True,exist_ok=True)
        receipt=folder/'delivery.json'
        if receipt.exists() and read(receipt).get('status')=='delivered':return
        outbound=folder/'outbound.json'
        if not outbound.exists():
            reports=[]
            for path in (Path(self.settings['analyzer_output_root'])/'market_insights').glob('*/outbound.json'):
                report=read(path,5_000_000)
                if report.get('status')=='completed' and report.get('source_run_id')==row['collected_run_id'] and report.get('envelope',{}).get('experiment_id')==key:reports.append(report)
            if not reports:return
            payload=reports[-1];original=payload['delivery_id']
            payload['qualification']={'comparison_sha256':digest(row['comparison']),'experiment_id':key,'status':'accepted','original_delivery_id':original,'purchase_demand_verified':False}
            payload['delivery_id']=digest({'original_delivery':original,'qualification':payload['qualification']})
            write(outbound,payload)
        payload=read(outbound,5_000_000);prior=read(receipt) if receipt.exists() else {}
        if prior.get('attempts',0)>=5:return
        request=urllib.request.Request(local_url(self.settings['product_url'])+'/market-insights',data=outbound.read_bytes(),headers={'Content-Type':'application/json','Idempotency-Key':payload['delivery_id']})
        try:
            with self.transport(request,timeout=10) as response:accepted=200<=response.status<300
            result={'status':'delivered' if accepted else 'pending','at':now(),'attempts':prior.get('attempts',0)+1,'delivery_id':payload['delivery_id']}
        except Exception as e:result={'status':'pending','error_type':type(e).__name__,'at':now(),'attempts':prior.get('attempts',0)+1}
        write(receipt,result)

    def tick(self):
        results = []
        for path in sorted((self.root / 'inbox').glob('*.json')):
            try:
                row = self.prepare(path.stem)
                if row['status'] in ('approved','budget_waiting') and self.settings['execution_enabled']: row = self.submit(path.stem)
                if row['status'] in ('submitted','awaiting_human_labels','accepted','rejected_comparison'): row = self.complete(path.stem)
                if row['status']=='accepted': self.qualified_delivery(path.stem)
                results.append({'proposal_id': path.stem, 'status': row['status']})
            except Exception as error:
                write(self.root / 'errors' / (path.stem + '.json'), {'at': now(), 'error_type': type(error).__name__, 'message': str(error)[:300], 'automatic_retry': False})
        from .tracking import tick as tracking_tick
        tracking_tick(self, self.send_job)
        write(self.root / 'heartbeat.json', {'at': now(), 'status': 'running', 'execution_enabled': self.settings['execution_enabled'], 'proposals': results})
        return results
