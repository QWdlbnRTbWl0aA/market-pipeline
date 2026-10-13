"""Observable preference evidence, never private model chain-of-thought."""
from collections import defaultdict
import re
from .storage import Invalid


def aggregate(state):
    candidates = {}; reviews = {}
    for frame in state['rounds']:
        candidates.update({c['id']: c for c in frame['candidates']})
        reviews.update(frame['reviews'])
    rows = []; aspects = defaultdict(lambda: defaultdict(lambda: {'accepted': [], 'rejected': []}))
    for identity, review in reviews.items():
        candidate = candidates.get(identity)
        if not candidate: continue
        group = 'accepted' if review['decision'].startswith('accept') else 'rejected'
        features = candidate.get('metadata', {}).get('features', {})
        rows.append({'id': identity, 'decision': review['decision'], 'comment': review['comment'],
                     'features': features, 'description': candidate.get('metadata', {}).get('description', ''),
                     'sha256': candidate['sha256']})
        for name, value in features.items(): aspects[name][value][group].append(identity)
    ids={r['id'] for r in rows[-80:]}
    bounded={name:{value:{group:[i for i in identifiers if i in ids] for group,identifiers in groups.items()} for value,groups in values.items()} for name,values in aspects.items()}
    return {'brief':state['brief'],'evidence': rows[-80:], 'aspects': bounded, 'negative_summary': state['negative_summary'],
            'whole_set_comments': [r['comments'] for r in state['rounds'] if r['comments']][-20:],
            'previous_understanding': state.get('understanding'),
            'note': 'Unique sample identities, latest explicit decision; replacements alone do not imply rejection.'}


def validate(value, evidence):
    if not isinstance(value, dict) or set(value) != {'summary', 'preferences', 'uncertainties', 'next_direction'}:
        raise Invalid('Structured understanding required')
    for name in ('summary', 'next_direction'):
        if not isinstance(value[name], str) or not 0 < len(value[name]) <= 5000: raise Invalid('Bounded understanding required')
    if not isinstance(value['uncertainties'], list) or len(value['uncertainties']) > 12 or any(not isinstance(s, str) or len(s)>1000 for s in value['uncertainties']): raise Invalid('Invalid uncertainties')
    if not isinstance(value['preferences'], list) or len(value['preferences']) > 20: raise Invalid('Invalid preferences')
    ids = {r['id'] for r in evidence}
    for row in value['preferences']:
        if not isinstance(row, dict) or set(row) != {'aspect', 'prefer', 'avoid', 'evidence_ids', 'confidence', 'explanation'}: raise Invalid('Invalid preference')
        if any(not isinstance(row[n], str) or len(row[n]) > 1000 for n in ('aspect','prefer','avoid','explanation')): raise Invalid('Invalid preference text')
        if row['confidence'] not in ('low','medium','high') or not isinstance(row['evidence_ids'],list) or not row['evidence_ids'] or set(row['evidence_ids'])-ids: raise Invalid('Preference requires real feedback evidence')
    return value


class LocalUnderstanding:
    def analyze(self, context, identity, project):
        preferences=[]
        for aspect, values in context['aspects'].items():
            positive=[(v,counts) for v,counts in values.items() if counts['accepted'] and not counts['rejected']]
            negative=[(v,counts) for v,counts in values.items() if counts['rejected'] and not counts['accepted']]
            if positive and negative:
                prefer, yes=max(positive,key=lambda item:len(item[1]['accepted']));avoid,no=max(negative,key=lambda item:len(item[1]['rejected']))
                preferences.append({'aspect':aspect,'prefer':prefer,'avoid':avoid,'confidence':'medium',
                    'evidence_ids':yes['accepted']+no['rejected'],'explanation':'מאפיין זה מבחין בין דוגמאות שאושרו לדוגמאות שנדחו; זו העדפה משוערת.'})
        return {'summary':'המשוב נשמר ומשמש לכיוון ההצעה הבאה.', 'preferences':preferences,
                'uncertainties':['הסקה מקומית בלבד; שילובים משותפים אינם הוכחה להעדפה.'],
                'next_direction':'Develop the accepted directions and follow explicit comments; avoid rejected distinguishing features.'}


def enforce(value, context):
    """Conservative guard: lone rejections do not prove unrelated dislikes.

    Explicit retain clauses protect named aspects; quotes are source feedback,
    not a deterministic invention of a product direction.
    """
    value=validate(value,context['evidence'])
    keywords={'palette':r'פלטה|צבע|גוון|גוונ|palette|colou?r|blue|red|yellow|green',
              'style':r'סגנון|אקוורל|צבעי מים|style|watercolo[u]?r|hand.paint|brush',
              'texture':r'מרקם|טקסטורה|texture|paper', 'composition':r'קומפוזיציה|פריסה|מבנה|layout|composition',
              'subject':r'דמות|ילד|ילדה|subject|boy|girl', 'typography':r'גופן|כיתוב|font|typography',
              'lighting':r'תאורה|lighting','background':r'רקע|background'}
    protected={}
    comments=list(context['evidence'])
    if comments:
        comments += [{'id':comments[-1]['id'],'comment':c} for c in context.get('whole_set_comments',[])]
    for row in comments:
        for match in re.finditer(r'(?:לשמור|להשאיר|retain|keep|preserve)\s+(.*?)(?:[.,;]|אך|אבל|\bbut\b|\bnot\b|$)',row['comment'],re.I):
            if re.search(r"(?:לא|don't|do not)\s*$",row['comment'][max(0,match.start()-12):match.start()],re.I):continue
            phrase=match.group(1).strip()
            for aspect,pattern in keywords.items():
                searchable=phrase.replace('צבעי מים','') if aspect=='palette' else phrase
                if re.search(pattern,searchable,re.I):protected[aspect]={'quote':phrase[:800],'id':row['id']}
    for preference in value['preferences']:
        aspect=preference['aspect']
        if aspect in protected:
            source=protected[aspect];preference.update(prefer=source['quote'],avoid='',confidence='high',evidence_ids=[source['id']],
                explanation='הערה מפורשת ביקשה לשמור על מאפיין זה; הדחייה אינה ראיה לכך שהוא לא רצוי.')
        else:
            counts=context['aspects'].get(aspect,{})
            accepted=sum(len(v['accepted']) for v in counts.values());rejected=sum(len(v['rejected']) for v in counts.values())
            if not accepted or not rejected:preference['confidence']='low'
    if protected:
        quotes=list(dict.fromkeys(p['quote'][:200] for p in protected.values()))
        value['summary']='המשוב מבקש לשמור: '+'; '.join(quotes)+'. יתר המסקנות הן הצעות ראשוניות לפי הדוגמאות וההערות.'
        value['next_direction']=('Explicit retain clauses take precedence over inferred dislikes: '+str(quotes)+'. '+value['next_direction'])[:5000]
    return value


SCHEMA = {'type':'object','additionalProperties':False,'required':['summary','preferences','uncertainties','next_direction'],
          'properties':{'summary':{'type':'string'},'next_direction':{'type':'string'},'uncertainties':{'type':'array','items':{'type':'string'}},
          'preferences':{'type':'array','items':{'type':'object','additionalProperties':False,
          'required':['aspect','prefer','avoid','evidence_ids','confidence','explanation'],
          'properties':{**{n:{'type':'string'} for n in ('aspect','prefer','avoid','explanation')},
             'confidence':{'type':'string','enum':['low','medium','high']},'evidence_ids':{'type':'array','items':{'type':'string'}}}}}}}
