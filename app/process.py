"""学习办理过程分析。

只使用明确归属（含人工纠正后归属）的事件计算环节耗时；未归属事件永不自动配对，
仅按人员与时间窗列出候选实例。耗时精度受输入限制：任一端为 day 精度时只给出
整天粒度，不产生分钟级数值。未结束流程按校区观察窗口右端计算删失等待并单列
分类，既不当作失败，也不默默丢弃。
"""
from datetime import date, datetime
from statistics import median

from .storage import DataError

SECONDS_PER_DAY = 86400


def event_date(event):
    if event['precision'] == 'second':
        return datetime.fromisoformat(event['time']).date()
    return date.fromisoformat(event['time'])


def segment_duration(first, second):
    if first['precision'] == 'second' and second['precision'] == 'second':
        seconds = (datetime.fromisoformat(second['time'])
                   - datetime.fromisoformat(first['time'])).total_seconds()
        return {'days': seconds / SECONDS_PER_DAY, 'seconds': seconds,
                'granularity': 'second'}
    return {'days': (event_date(second) - event_date(first)).days,
            'granularity': 'day'}


def corrections_map(journal):
    if journal is None:
        return {}
    mapping = {}
    for row in journal.all('correction'):
        mapping[row['event']] = row
    return mapping


def effective_events(store, journal):
    mapping = corrections_map(journal)
    events = store.table('events')
    for event in events:
        correction = mapping.get(event['event'])
        if correction is not None:
            event['instance'] = correction['to_instance']
            event['course'] = correction['to_course']
            event['corrected_by'] = correction['correction']
    return events


def prepare(store, journal=None):
    events = effective_events(store, journal)
    instances = store.table('instances')
    windows = {row['campus']: row for row in store.table('windows')}
    owners = {row['campus']: row['owner'] for row in store.table('case_owners')}
    by_instance = {row['instance']: [] for row in instances}
    unassigned = []
    for event in events:
        if event['instance'] is None:
            unassigned.append(event)
        else:
            by_instance.setdefault(event['instance'], []).append(event)
    for rows in by_instance.values():
        rows.sort(key=lambda event: (event['time'], event['event']))
    cohorts = {}
    for header in instances:
        evs = by_instance.get(header['instance'], [])
        for first, second in zip(evs, evs[1:]):
            if first['kind'] in ('reopened', 'pause_requested'):
                continue
            if second['kind'] in ('reopened', 'pause_requested'):
                continue
            duration = segment_duration(first, second)
            cohorts.setdefault((header['campus'], first['kind']), []).append(
                {'instance': header['instance'], 'from_event': first['event'],
                 'to_event': second['event'], 'to_kind': second['kind'],
                 'days': duration['days'], 'granularity': duration['granularity']})
    return {'store': store, 'journal': journal, 'events': events,
            'instances': instances, 'windows': windows, 'owners': owners,
            'by_instance': by_instance, 'unassigned': unassigned,
            'pauses': store.table('pauses'), 'cohorts': cohorts,
            'dependencies': store.table('dependencies')}


def instance_span(ctx, header):
    start = date.fromisoformat(header['opened'])
    evs = ctx['by_instance'].get(header['instance'], [])
    completed = [event for event in evs if event['kind'] == 'completed']
    if completed:
        return start, event_date(completed[-1])
    window = ctx['windows'].get(header['campus'])
    end = date.fromisoformat(window['end']) if window else start
    return start, end


def active_pause(ctx, instance_id, moment):
    for pause in ctx['pauses']:
        if pause['instance'] != instance_id:
            continue
        start = date.fromisoformat(pause['start'])
        end = date.fromisoformat(pause['end']) if pause['end'] else None
        if start <= moment and (end is None or end >= moment):
            return pause
    return None


def classify_current(ctx, header, evs, horizon):
    last = evs[-1]
    last_date = event_date(last)
    current = {'since_event': last['event'], 'since_kind': last['kind'],
               'wait_days': (horizon - last_date).days if horizon else None,
               'granularity': 'day'}
    if last['kind'] == 'reopened':
        current['category'] = 'repeated'
        return current
    pause = active_pause(ctx, header['instance'], horizon or last_date)
    if pause is not None:
        current['category'] = 'paused'
        current['pause'] = pause['pause']
        current['pause_reason'] = pause['reason']
        return current
    pending = sorted(event['event'] for event in ctx['unassigned']
                     if event['person'] == header['person']
                     and event_date(event) > last_date
                     and (horizon is None or event_date(event) <= horizon))
    if pending:
        current['category'] = 'indeterminate'
        current['pending_events'] = pending
        return current
    current['category'] = 'waiting'
    return current


def evaluate_wait(ctx, campus, since_kind, wait_days):
    cohort = ctx['cohorts'].get((campus, since_kind), [])
    if not cohort or wait_days is None:
        return 'waiting', None
    days = [row['days'] for row in cohort]
    reference = {'cohort': len(days), 'median_days': median(days),
                 'max_days': max(days)}
    if wait_days > max(days):
        return 'stuck', reference
    return 'waiting', reference


def instance_view(ctx, instance_id):
    matches = [row for row in ctx['instances'] if row['instance'] == instance_id]
    if not matches:
        raise DataError('unknown instance: ' + str(instance_id))
    header = matches[0]
    evs = ctx['by_instance'].get(instance_id, [])
    window = ctx['windows'].get(header['campus'])
    horizon = date.fromisoformat(window['end']) if window else None
    segments = []
    for first, second in zip(evs, evs[1:]):
        segments.append({'from_event': first['event'], 'to_event': second['event'],
                         'from_kind': first['kind'], 'to_kind': second['kind'],
                         'duration': segment_duration(first, second),
                         'category': 'repeated' if first['kind'] == 'reopened'
                         else 'completed'})
    finished = bool(evs) and evs[-1]['kind'] == 'completed'
    current = None
    if evs and not finished:
        current = classify_current(ctx, header, evs, horizon)
        if current['category'] == 'waiting':
            category, reference = evaluate_wait(ctx, header['campus'],
                                                current['since_kind'],
                                                current['wait_days'])
            current['category'] = category
            if reference is not None:
                current['reference'] = reference
    start, end = instance_span(ctx, header)
    parallel = []
    for other in ctx['instances']:
        if other['instance'] == instance_id or other['person'] != header['person']:
            continue
        other_start, other_end = instance_span(ctx, other)
        if other_start <= end and start <= other_end:
            parallel.append(other['instance'])
    candidates = [{'event': event['event'], 'kind': event['kind'], 'time': event['time']}
                  for event in ctx['unassigned']
                  if event['person'] == header['person']
                  and start <= event_date(event) <= end]
    event_ids = {event['event'] for event in evs}
    links = [row for row in ctx['dependencies']
             if row['before'] in event_ids and row['after'] in event_ids]
    return {'instance': header['instance'], 'person': header['person'],
            'course': header['course'], 'campus': header['campus'],
            'state': header['state'], 'opened': header['opened'],
            'owner': ctx['owners'].get(header['campus']), 'window': window,
            'events': evs, 'segments': segments, 'current': current,
            'pauses': [row for row in ctx['pauses'] if row['instance'] == instance_id],
            'parallel_instances': sorted(parallel),
            'reopened': any(event['kind'] == 'reopened' for event in evs),
            'unassigned_candidates': candidates,
            'known_dependencies': links}


def unassigned_report(ctx):
    report = []
    for event in ctx['unassigned']:
        candidates = []
        for header in ctx['instances']:
            if header['person'] != event['person']:
                continue
            start, end = instance_span(ctx, header)
            if start <= event_date(event) <= end:
                candidates.append(header['instance'])
        report.append({'event': event['event'], 'person': event['person'],
                       'kind': event['kind'], 'time': event['time'],
                       'precision': event['precision'],
                       'candidates': sorted(candidates), 'attributed': False})
    return report


def findings(ctx):
    stuck, waiting, paused, indeterminate, repeated = [], [], [], [], []
    for header in ctx['instances']:
        view = instance_view(ctx, header['instance'])
        current = view['current']
        if current is None:
            continue
        entry = {'instance': header['instance'], 'person': header['person'],
                 'campus': header['campus'], 'owner': view['owner'],
                 'since_kind': current['since_kind'],
                 'since_event': current['since_event'],
                 'wait_days': current['wait_days'], 'granularity': 'day'}
        category = current['category']
        if category == 'stuck':
            entry['reference'] = current.get('reference')
            entry['parallel_instances'] = view['parallel_instances']
            stuck.append(entry)
        elif category == 'waiting':
            if current.get('reference') is not None:
                entry['reference'] = current['reference']
            waiting.append(entry)
        elif category == 'paused':
            entry['pause'] = current['pause']
            entry['reason'] = current['pause_reason']
            paused.append(entry)
        elif category == 'indeterminate':
            entry['pending_events'] = current['pending_events']
            indeterminate.append(entry)
        else:
            repeated.append(entry)
    stuck.sort(key=lambda entry: (-entry['wait_days'], entry['instance']))
    return {'stuck': stuck, 'waiting': waiting,
            'not_actionable': {'paused': paused, 'indeterminate': indeterminate,
                               'repeated': repeated},
            'unassigned_events': unassigned_report(ctx),
            'corrections': ctx['journal'].all('correction') if ctx['journal'] else [],
            'windows': ctx['windows']}


def stage_report(ctx):
    campuses = {}
    for campus, window in ctx['windows'].items():
        transitions = []
        kinds = sorted({kind for (site, kind) in ctx['cohorts'] if site == campus})
        for kind in kinds:
            pairs = {}
            for row in ctx['cohorts'][(campus, kind)]:
                pairs.setdefault(row['to_kind'], []).append(row)
            for to_kind in sorted(pairs):
                segments = pairs[to_kind]
                days = [row['days'] for row in segments]
                transitions.append({'from': kind, 'to': to_kind,
                                    'count': len(segments),
                                    'median_days': median(days),
                                    'min_days': min(days), 'max_days': max(days),
                                    'segments': segments})
        censored = []
        for header in ctx['instances']:
            if header['campus'] != campus:
                continue
            current = instance_view(ctx, header['instance'])['current']
            if current is not None:
                censored.append({'instance': header['instance'],
                                 'since_kind': current['since_kind'],
                                 'wait_days': current['wait_days'],
                                 'category': current['category']})
        campuses[campus] = {'window': window, 'transitions': transitions,
                            'censored_tails': censored}
    return {'campuses': campuses}


def campus_report(ctx):
    campuses = {}
    for campus, window in ctx['windows'].items():
        headers = [row for row in ctx['instances'] if row['campus'] == campus]
        durations = []
        in_flight, reopened = [], []
        for header in headers:
            evs = ctx['by_instance'].get(header['instance'], [])
            completed = [event for event in evs if event['kind'] == 'completed']
            if completed:
                durations.append((event_date(completed[-1])
                                  - date.fromisoformat(header['opened'])).days)
            else:
                in_flight.append(header['instance'])
            if any(event['kind'] == 'reopened' for event in evs):
                reopened.append(header['instance'])
        left_truncated = [row['instance'] for row in headers
                          if date.fromisoformat(row['opened'])
                          < date.fromisoformat(window['start'])]
        campuses[campus] = {
            'window': window, 'instances': len(headers),
            'completed': len(durations), 'in_flight': sorted(in_flight),
            'reopened_after_completion': sorted(reopened),
            'left_truncated': sorted(left_truncated),
            'completion_days': {
                'count': len(durations),
                'median_days': median(durations) if durations else None,
                'min_days': min(durations) if durations else None,
                'max_days': max(durations) if durations else None}}
    overlap = None
    starts = [date.fromisoformat(row['start']) for row in ctx['windows'].values()]
    ends = [date.fromisoformat(row['end']) for row in ctx['windows'].values()]
    if starts and max(starts) <= min(ends):
        start, end = max(starts), min(ends)
        per_campus = {}
        for campus in ctx['windows']:
            durations = []
            for header in ctx['instances']:
                if header['campus'] != campus:
                    continue
                opened = date.fromisoformat(header['opened'])
                evs = ctx['by_instance'].get(header['instance'], [])
                completed = [event for event in evs if event['kind'] == 'completed']
                if opened >= start and completed and event_date(completed[-1]) <= end:
                    durations.append((event_date(completed[-1]) - opened).days)
            per_campus[campus] = {
                'completed': len(durations),
                'median_completion_days': median(durations) if durations else None}
        overlap = {'start': start.isoformat(), 'end': end.isoformat(),
                   'campuses': per_campus,
                   'note': '仅统计两校区窗口重叠期内完整观察到的实例，窗口外数据不可直接比较'}
    return {'campuses': campuses, 'overlap': overlap,
            'notes': ['校区观察窗口不同，直接比较总耗时会偏倚；overlap 段给出可比较口径',
                      '未结束流程按删失等待单列，不计入已完成耗时，也不视为失败']}


def assistance_plan(ctx):
    journal = ctx['journal']
    cases = journal.all('case') if journal else []
    allocations = [row for row in (journal.all('assistance') if journal else [])
                   if row['status'] == 'allocated']
    pools = {row['owner']: row['slots'] for row in ctx['store'].table('assistance_pool')}
    report = findings(ctx)
    by_campus = {}
    for entry in report['stuck']:
        by_campus.setdefault(entry['campus'], []).append(entry)
    owners = {}
    for owner, slots in pools.items():
        campus = next((site for site, name in ctx['owners'].items() if name == owner),
                      None)
        allocated = [row for row in allocations if row['owner'] == owner]
        remaining = slots - len(allocated)
        entries = []
        for item in by_campus.get(campus, []):
            case = next((row for row in cases
                         if row['instance'] == item['instance']
                         and row['status'] == 'open'), None)
            if case and any(row['case'] == case['case'] for row in allocated):
                disposition = 'covered'
            elif remaining > 0:
                disposition = 'recommended'
                remaining -= 1
            else:
                disposition = 'uncovered'
            entry = {'instance': item['instance'], 'wait_days': item['wait_days'],
                     'case': case['case'] if case else None,
                     'disposition': disposition}
            if disposition == 'uncovered':
                entry['status'] = 'unresolved'
            entries.append(entry)
        owners[owner] = {'campus': campus, 'slots': slots,
                         'allocated': [row['case'] for row in allocated],
                         'instances': entries,
                         'paused': [row['instance']
                                    for row in report['not_actionable']['paused']
                                    if row['campus'] == campus]}
    return {'owners': owners}
