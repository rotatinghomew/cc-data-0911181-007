from .storage import DataError
from . import process


def send(store,journal,payload):
    with journal.transaction():
        case=journal.get('case',payload['case'])
        assistance=journal.get('assistance',case['case'])
        if assistance['status']!='allocated':
            raise DataError('no confirmed assistance')
        previous=[row for row in journal.all('notice') if row['notice']==payload['notice']]
        if previous:
            return previous[0]
        view=process.instance_view(process.prepare(store,journal),case['instance'])
        current=view['current']
        if current is not None and current['category'] in ('paused','indeterminate'):
            raise DataError('current wait is '+current['category']+'; not urgeable')
        basis=None
        if current is not None:
            basis={'category':current['category'],'since_event':current['since_event'],
                   'wait_days':current['wait_days'],'granularity':current['granularity'],
                   'window_end':view['window']['end'] if view['window'] else None,
                   'dataset':store.fingerprint()}
        row=dict(notice=payload['notice'],case=case['case'],instance=case['instance'],person=case['person'],
                 owner=case['owner'],reason=case['reason'],message='assistance_assigned',basis=basis)
        return journal.put('notice',row['notice'],row)
