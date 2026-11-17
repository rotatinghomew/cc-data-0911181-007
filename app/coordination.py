from .storage import DataError
from . import process


def open_case(store,journal,payload):
    instance=store.find('instances',instance=payload['instance'])
    owner=store.find('case_owners',campus=instance['campus'])['owner']
    evidence=payload.get('evidence',[])
    if not isinstance(evidence,list) or not all(isinstance(item,str) for item in evidence):
        raise DataError('evidence must be a list of event ids')
    events={event['event']:event for event in process.effective_events(store,journal)}
    for event_id in evidence:
        event=events.get(event_id)
        if event is None:
            raise DataError('unknown event: '+event_id)
        if event['person']!=instance['person']:
            raise DataError('evidence person mismatch: '+event_id)
        if event['instance'] is not None and event['instance']!=instance['instance']:
            raise DataError('evidence assigned to another instance: '+event_id)
    with journal.transaction():
        existing=journal.all('case')
        for row in existing:
            if row['case']==payload['case']:
                return row
        for row in existing:
            if row['status']!='open':
                continue
            shared=sorted(set(row.get('evidence',[]))&set(evidence))
            if shared:
                return dict(row,deduplicated=True,shared_material=shared)
        row=dict(case=payload['case'],instance=instance['instance'],person=instance['person'],
                 owner=owner,status='open',reason=payload['reason'],evidence=evidence)
        return journal.put('case',row['case'],row)
