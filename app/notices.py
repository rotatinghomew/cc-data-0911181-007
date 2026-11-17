from .storage import DataError


def send(store,journal,payload):
    with journal.transaction():
        case=journal.get('case',payload['case'])
        assistance=journal.get('assistance',case['case'])
        if assistance['status']!='allocated':
            raise DataError('no confirmed assistance')
        previous=[row for row in journal.all('notice') if row['notice']==payload['notice']]
        if previous:
            return previous[0]
        row=dict(notice=payload['notice'],case=case['case'],instance=case['instance'],person=case['person'],
                 owner=case['owner'],reason=case['reason'],message='assistance_assigned')
        return journal.put('notice',row['notice'],row)
