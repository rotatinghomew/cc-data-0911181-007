def explicit_timeline(store,instance):
    header=store.find('instances',instance=instance)
    events=sorted(store.select('events',instance=instance),key=lambda row:(row['time'],row['event']))
    pauses=store.select('pauses',instance=instance)
    event_ids={row['event'] for row in events}
    links=[row for row in store.table('dependencies')
           if row['before'] in event_ids and row['after'] in event_ids]
    return dict(header,events=events,pauses=pauses,known_dependencies=links)
