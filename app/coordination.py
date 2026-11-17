def open_case(store,journal,payload):
    instance=store.find('instances',instance=payload['instance'])
    owner=store.find('case_owners',campus=instance['campus'])['owner']
    row=dict(case=payload['case'],instance=instance['instance'],person=instance['person'],owner=owner,status='open',reason=payload['reason'])
    with journal.transaction():
        return journal.put('case',row['case'],row)
