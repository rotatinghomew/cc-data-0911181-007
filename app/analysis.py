from .domain import explicit_timeline
from .storage import single


def timelines(store,query):
    person=single(query,'person')
    rows=[row for row in store.table('instances') if person is None or row['person']==person]
    return {'instances':[explicit_timeline(store,row['instance']) for row in rows],
            'unassigned_events':[row for row in store.table('events') if row['instance'] is None
                                 and (person is None or row['person']==person)]}


def states(store,query):
    counts={}
    for row in store.table('instances'):
        counts[row['state']]=counts.get(row['state'],0)+1
    return {'states':counts,'observation_windows':store.table('windows')}


ROUTES={'/api/timelines':timelines,'/api/states':states}
