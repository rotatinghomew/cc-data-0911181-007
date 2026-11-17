from .storage import DataError


def allocate(store,journal,payload):
    with journal.transaction():
        case=journal.get('case',payload['case'])
        pool=store.find('assistance_pool',owner=case['owner'])
        existing=journal.all('assistance')
        if any(row['case']==case['case'] for row in existing):
            return next(row for row in existing if row['case']==case['case'])
        if sum(row['owner']==case['owner'] for row in existing)>=pool['slots']:
            raise DataError('no assistance slots')
        return journal.put('assistance',case['case'],dict(case=case['case'],owner=case['owner'],status='allocated'))
