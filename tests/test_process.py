import json
from pathlib import Path
import shutil
import tempfile
import unittest

from app import assistance, coordination, corrections, notices
from app.journal import Journal
from app.service import dispatch
from app.storage import DataError, Store

DATA = Path(__file__).parents[1] / 'data'


class ProcessAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(DATA)
        self.journal = Journal()

    def tearDown(self):
        self.journal.close()

    def view(self, instance):
        result = dispatch(self.store, '/api/process/instances',
                          {'instance': [instance]}, self.journal)
        return result['instances'][0]

    def findings(self):
        return dispatch(self.store, '/api/process/findings', {}, self.journal)

    def test_stuck_instances_carry_evidence(self):
        stuck = {entry['instance']: entry for entry in self.findings()['stuck']}
        self.assertEqual(set(stuck), {'J0', 'J8', 'J12', 'J16', 'J20', 'J24', 'J28'})
        self.assertEqual(stuck['J0']['wait_days'], 55)
        self.assertEqual(stuck['J0']['owner'], 'east-desk')
        self.assertEqual(stuck['J0']['granularity'], 'day')
        self.assertNotIn('seconds', stuck['J0'])
        self.assertEqual(stuck['J0']['reference']['max_days'], 43)
        self.assertEqual(stuck['J0']['reference']['cohort'], 7)
        self.assertEqual(stuck['J0']['parallel_instances'], ['J12', 'J24'])
        ordered = [entry['instance'] for entry in self.findings()['stuck']]
        self.assertEqual(ordered, ['J0', 'J20', 'J12', 'J24', 'J16', 'J28', 'J8'])

    def test_paused_wait_is_not_stuck(self):
        result = self.findings()
        self.assertNotIn('J4', {entry['instance'] for entry in result['stuck']})
        paused = result['not_actionable']['paused']
        self.assertEqual([entry['instance'] for entry in paused], ['J4'])
        self.assertEqual(paused[0]['pause'], 'P1')
        self.assertEqual(paused[0]['reason'], 'personal')

    def test_reopened_flow_is_repeated_not_stuck(self):
        view = self.view('J1')
        self.assertTrue(view['reopened'])
        self.assertEqual(view['current']['category'], 'repeated')
        self.assertEqual(view['current']['wait_days'], 2)
        self.assertNotIn('J1', {entry['instance'] for entry in self.findings()['stuck']})

    def test_day_precision_never_produces_minutes(self):
        view = self.view('J0')
        self.assertTrue(view['segments'])
        for segment in view['segments']:
            self.assertEqual(segment['duration']['granularity'], 'day')
            self.assertNotIn('seconds', segment['duration'])
        first = self.view('J1')['segments'][0]
        self.assertEqual(first['duration']['granularity'], 'second')
        self.assertEqual(first['duration']['seconds'], 86400)

    def test_unassigned_events_are_never_paired(self):
        view = self.view('J0')
        self.assertNotIn('E0-documents_received',
                         {event['event'] for event in view['events']})
        self.assertEqual([item['event'] for item in view['unassigned_candidates']],
                         ['E0-documents_received'])
        other = self.view('J12')
        self.assertEqual({event['event'] for event in other['events']},
                         {'E12-applied', 'E12-documents_received', 'E12-approved',
                          'E12-first_class'})
        unassigned = {entry['event']: entry
                      for entry in self.findings()['unassigned_events']}
        self.assertEqual(unassigned['E0-documents_received']['candidates'], ['J0'])
        self.assertEqual(unassigned['E28-documents_received']['candidates'],
                         ['J16', 'J28', 'J4'])
        self.assertFalse(unassigned['E28-documents_received']['attributed'])

    def test_campus_windows_get_comparable_explanation(self):
        result = dispatch(self.store, '/api/process/campuses', {}, self.journal)
        self.assertEqual(result['overlap']['start'], '2026-09-08')
        self.assertEqual(result['overlap']['end'], '2026-10-25')
        self.assertEqual(result['overlap']['campuses']['east']['completed'], 1)
        self.assertEqual(result['overlap']['campuses']['west']['completed'], 6)
        self.assertEqual(result['overlap']['campuses']['east']['median_completion_days'], 41)
        self.assertEqual(result['overlap']['campuses']['west']['median_completion_days'], 41)
        self.assertEqual(len(result['campuses']['west']['left_truncated']), 9)
        self.assertEqual(result['campuses']['east']['left_truncated'], [])
        self.assertEqual(len(result['campuses']['east']['in_flight']), 8)
        self.assertEqual(result['campuses']['west']['reopened_after_completion'], ['J1'])

    def test_in_flight_flows_are_censored_not_failed(self):
        result = dispatch(self.store, '/api/process/stages', {}, self.journal)
        tails = result['campuses']['east']['censored_tails']
        self.assertEqual(len(tails), 8)
        self.assertEqual({tail['category'] for tail in tails}, {'stuck', 'paused'})
        transition = next(row for row in result['campuses']['east']['transitions']
                          if row['from'] == 'first_class' and row['to'] == 'completed')
        self.assertEqual(transition['count'], 7)
        self.assertEqual(transition['max_days'], 43)
        self.assertEqual({row['instance'] for row in transition['segments']},
                         {'J2', 'J6', 'J10', 'J14', 'J18', 'J22', 'J26'})

    def test_plan_limits_slots_and_marks_uncovered_unresolved(self):
        plan = dispatch(self.store, '/api/process/plan', {}, self.journal)
        east = plan['owners']['east-desk']
        self.assertEqual(east['slots'], 2)
        dispositions = [entry['disposition'] for entry in east['instances']]
        self.assertEqual(dispositions.count('recommended'), 2)
        uncovered = [entry for entry in east['instances']
                     if entry['disposition'] == 'uncovered']
        self.assertEqual(len(uncovered), 5)
        self.assertTrue(all(entry['status'] == 'unresolved' for entry in uncovered))
        self.assertEqual(east['paused'], ['J4'])
        self.assertEqual(plan['owners']['west-desk']['instances'], [])

    def test_unknown_instance_rejected(self):
        with self.assertRaises(DataError):
            dispatch(self.store, '/api/process/instances',
                     {'instance': ['nope']}, self.journal)


class AnalysisDrivenWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(DATA)
        self.journal = Journal()

    def tearDown(self):
        self.journal.close()

    def test_shared_material_does_not_create_conflicting_cases(self):
        first = coordination.open_case(self.store, self.journal, dict(
            case='c-a', instance='J16', reason='stuck',
            evidence=['E28-documents_received']))
        second = coordination.open_case(self.store, self.journal, dict(
            case='c-b', instance='J28', reason='stuck',
            evidence=['E28-documents_received']))
        self.assertTrue(second['deduplicated'])
        self.assertEqual(second['case'], first['case'])
        self.assertEqual(second['shared_material'], ['E28-documents_received'])
        self.assertEqual(len(self.journal.all('case')), 1)

    def test_open_case_validates_evidence(self):
        with self.assertRaises(DataError):
            coordination.open_case(self.store, self.journal, dict(
                case='c-x', instance='J28', reason='x', evidence=['E16-approved']))
        with self.assertRaises(DataError):
            coordination.open_case(self.store, self.journal, dict(
                case='c-y', instance='J0', reason='y', evidence=['no-such-event']))
        with self.assertRaises(DataError):
            coordination.open_case(self.store, self.journal, dict(
                case='c-z', instance='J0', reason='z', evidence=['E1-applied']))

    def test_open_case_is_idempotent(self):
        first = coordination.open_case(self.store, self.journal, dict(
            case='c-i', instance='J0', reason='r'))
        again = coordination.open_case(self.store, self.journal, dict(
            case='c-i', instance='J0', reason='r'))
        self.assertEqual(first, again)
        self.assertEqual(len(self.journal.all('case')), 1)

    def test_correction_moves_delay_and_frees_former_owner(self):
        coordination.open_case(self.store, self.journal, dict(
            case='c-a', instance='J16', reason='stuck',
            evidence=['E28-documents_received']))
        assistance.allocate(self.store, self.journal, dict(case='c-a'))
        notice = notices.send(self.store, self.journal, dict(case='c-a', notice='n-a'))
        self.assertEqual(notice['basis']['category'], 'stuck')
        corrections.reassign(self.store, self.journal, dict(
            correction='fix-1', event='E28-documents_received',
            to_instance='J28', reason='misfiled to another enrollment'))
        case = self.journal.get('case', 'c-a')
        self.assertEqual(case['status'], 'evidence_moved')
        self.assertEqual(case['moved_to'], 'J28')
        self.assertEqual(self.journal.get('assistance', 'c-a')['status'], 'released')
        view = dispatch(self.store, '/api/process/instances',
                        {'instance': ['J28']}, self.journal)['instances'][0]
        self.assertIn('E28-documents_received',
                      {event['event'] for event in view['events']})
        result = dispatch(self.store, '/api/process/findings', {}, self.journal)
        self.assertEqual([row['correction'] for row in result['corrections']], ['fix-1'])
        self.assertNotIn('E28-documents_received',
                         {row['event'] for row in result['unassigned_events']})
        self.assertEqual(self.journal.get('notice', 'n-a')['basis'], notice['basis'])
        coordination.open_case(self.store, self.journal, dict(
            case='c-b', instance='J28', reason='stuck',
            evidence=['E28-documents_received']))
        assistance.allocate(self.store, self.journal, dict(case='c-b'))
        self.assertEqual(self.journal.get('assistance', 'c-b')['status'], 'allocated')

    def test_correction_validates_consistency(self):
        with self.assertRaises(DataError):
            corrections.reassign(self.store, self.journal, dict(
                correction='bad-1', event='no-such-event', to_instance='J0',
                reason='x'))
        with self.assertRaises(DataError):
            corrections.reassign(self.store, self.journal, dict(
                correction='bad-2', event='E0-documents_received',
                to_instance='J4', reason='person mismatch'))
        with self.assertRaises(DataError):
            corrections.reassign(self.store, self.journal, dict(
                correction='bad-3', event='E0-approved', to_instance='J0',
                reason='already there'))

    def test_paused_instance_is_not_urged(self):
        coordination.open_case(self.store, self.journal, dict(
            case='c-p', instance='J4', reason='check'))
        assistance.allocate(self.store, self.journal, dict(case='c-p'))
        with self.assertRaises(DataError):
            notices.send(self.store, self.journal, dict(case='c-p', notice='n-p'))

    def test_indeterminate_wait_is_not_urged_or_called_stuck(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'data'
            shutil.copytree(DATA, target)
            events = json.loads((target / 'events.json').read_text())
            events.append({'event': 'X-1', 'instance': None, 'person': 'L0',
                           'course': None, 'kind': 'documents_received',
                           'time': '2026-10-15', 'precision': 'day'})
            (target / 'events.json').write_text(json.dumps(events))
            store = Store(target)
            journal = Journal()
            try:
                view = dispatch(store, '/api/process/instances',
                                {'instance': ['J0']}, journal)['instances'][0]
                self.assertEqual(view['current']['category'], 'indeterminate')
                self.assertEqual(view['current']['pending_events'], ['X-1'])
                result = dispatch(store, '/api/process/findings', {}, journal)
                self.assertEqual({entry['instance'] for entry in result['stuck']},
                                 {'J8', 'J16', 'J20', 'J28'})
                self.assertEqual({entry['instance'] for entry in
                                  result['not_actionable']['indeterminate']},
                                 {'J0', 'J12', 'J24'})
                coordination.open_case(store, journal, dict(
                    case='c-x', instance='J0', reason='check'))
                assistance.allocate(store, journal, dict(case='c-x'))
                with self.assertRaises(DataError):
                    notices.send(store, journal, dict(case='c-x', notice='n-x'))
            finally:
                journal.close()

    def test_notice_records_basis_and_resend_returns_it(self):
        coordination.open_case(self.store, self.journal, dict(
            case='c-n', instance='J0', reason='stuck'))
        assistance.allocate(self.store, self.journal, dict(case='c-n'))
        notice = notices.send(self.store, self.journal, dict(case='c-n', notice='n-n'))
        self.assertEqual(notice['basis']['category'], 'stuck')
        self.assertEqual(notice['basis']['wait_days'], 55)
        self.assertEqual(notice['basis']['window_end'], '2026-11-01')
        self.assertEqual(notice['basis']['dataset'], self.store.fingerprint())
        again = notices.send(self.store, self.journal, dict(case='c-n', notice='n-n'))
        self.assertEqual(again, notice)

    def test_plan_reflects_existing_allocation(self):
        coordination.open_case(self.store, self.journal, dict(
            case='c-0', instance='J0', reason='stuck'))
        assistance.allocate(self.store, self.journal, dict(case='c-0'))
        plan = dispatch(self.store, '/api/process/plan', {}, self.journal)
        east = plan['owners']['east-desk']['instances']
        by_instance = {entry['instance']: entry for entry in east}
        self.assertEqual(by_instance['J0']['disposition'], 'covered')
        self.assertEqual(by_instance['J0']['case'], 'c-0')
        dispositions = [entry['disposition'] for entry in east]
        self.assertEqual(dispositions.count('recommended'), 1)
        self.assertEqual(dispositions.count('uncovered'), 5)
