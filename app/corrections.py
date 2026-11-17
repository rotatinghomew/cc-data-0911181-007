from .storage import DataError
from . import process


def reassign(store,journal,payload):
    events={event['event']:event for event in process.effective_events(store,journal)}
    event=events.get(payload['event'])
    if event is None:
        raise DataError('unknown event: '+str(payload['event']))
    target=store.find('instances',instance=payload['to_instance'])
    if event['person']!=target['person']:
        raise DataError('event person does not match target instance')
    if event['instance']==target['instance']:
        raise DataError('event already assigned to target instance')
    with journal.transaction():
        for row in journal.all('correction'):
            if row['correction']==payload['correction']:
                return row
        row=dict(correction=payload['correction'],event=event['event'],
                 from_instance=event['instance'],from_course=event['course'],
                 to_instance=target['instance'],to_course=target['course'],
                 reason=payload['reason'])
        journal.put('correction',row['correction'],row)
        for case in journal.all('case'):
            if case.get('status')=='open' and event['event'] in case.get('evidence',[]):
                case['status']='evidence_moved'
                case['moved_to']=target['instance']
                case['correction']=row['correction']
                journal.put('case',case['case'],case)
                try:
                    allocation=journal.get('assistance',case['case'])
                except DataError:
                    continue
                if allocation['status']=='allocated':
                    allocation['status']='released'
                    allocation['release_reason']='evidence_moved'
                    journal.put('assistance',allocation['case'],allocation)
        return row
