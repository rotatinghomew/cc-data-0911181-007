from pathlib import Path
import tempfile
import unittest
from app.journal import Journal
from app.storage import DataError,Store

DATA=Path(__file__).parents[1]/'data'


class BusinessChainTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(DATA)
        self.journal=Journal()

    def tearDown(self):
        self.journal.close()

    def test_business_chain(self):
        self.exercise(self.store,self.journal)

    def test_rollback_on_failure(self):
        with self.assertRaises(DataError):
            with self.journal.transaction():
                self.journal.put('test','a',{'value':1})
                raise DataError('aborted')
        self.assertEqual(self.journal.all('test'),[])

    def test_restart_retains_business_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'workflow.sqlite3'
            journal=Journal(path)
            try:
                self.exercise(self.store,journal)
                before={kind[0] for kind in journal.connection.execute('SELECT DISTINCT kind FROM documents')}
                snapshot={kind:journal.all(kind) for kind in before}
            finally:
                journal.close()
            reopened=Journal(path)
            try:
                self.assertEqual(snapshot,{kind:reopened.all(kind) for kind in before})
            finally:
                reopened.close()

    def exercise(self,store,journal):
        from app import coordination,assistance,notices
        coordination.open_case(store,journal,dict(case='c1',instance='J1',reason='manual review'))
        assistance.allocate(store,journal,dict(case='c1'))
        notice=notices.send(store,journal,dict(case='c1',notice='n1'))
        self.assertEqual(notice['person'],'L1')
        coordination.open_case(store,journal,dict(case='c2',instance='J3',reason='manual review'))
        with self.assertRaises(DataError):
            assistance.allocate(store,journal,dict(case='c2'))
        self.assertEqual(notices.send(store,journal,dict(case='c1',notice='n1')),notice)
