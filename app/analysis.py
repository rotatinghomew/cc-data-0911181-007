from . import process
from .domain import explicit_timeline
from .storage import DataError, single


def timelines(store,query,journal=None):
    person=single(query,'person')
    rows=[row for row in store.table('instances') if person is None or row['person']==person]
    return {'instances':[explicit_timeline(store,row['instance']) for row in rows],
            'unassigned_events':[row for row in store.table('events') if row['instance'] is None
                                 and (person is None or row['person']==person)]}


def states(store,query,journal=None):
    counts={}
    for row in store.table('instances'):
        counts[row['state']]=counts.get(row['state'],0)+1
    return {'states':counts,'observation_windows':store.table('windows')}


def process_instances(store,query,journal=None):
    ctx=process.prepare(store,journal)
    instance=single(query,'instance')
    person=single(query,'person')
    headers=ctx['instances']
    if instance is not None:
        headers=[row for row in headers if row['instance']==instance]
        if not headers:
            raise DataError('unknown instance: '+instance)
    if person is not None:
        headers=[row for row in headers if row['person']==person]
    return {'instances':[process.instance_view(ctx,row['instance']) for row in headers]}


def process_stages(store,query,journal=None):
    return process.stage_report(process.prepare(store,journal))


def process_campuses(store,query,journal=None):
    return process.campus_report(process.prepare(store,journal))


def process_findings(store,query,journal=None):
    return process.findings(process.prepare(store,journal))


def process_plan(store,query,journal=None):
    return process.assistance_plan(process.prepare(store,journal))


ROUTES={'/api/timelines':timelines,'/api/states':states,
        '/api/process/instances':process_instances,
        '/api/process/stages':process_stages,
        '/api/process/campuses':process_campuses,
        '/api/process/findings':process_findings,
        '/api/process/plan':process_plan}
