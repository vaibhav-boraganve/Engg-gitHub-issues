import json
import os
import tempfile
from unittest.mock import patch

from django.test import TestCase

from issues.models import CriticalIssue, Issue, LowPriorityIssue, Reporter


class ReporterModelTests(TestCase):
    def test_validate_rejects_empty_name(self):
        reporter = Reporter(1, '', 'ada@example.com', 'backend')
        with self.assertRaisesMessage(ValueError, 'Name cannot be empty'):
            reporter.validate()

    def test_validate_rejects_email_without_at(self):
        reporter = Reporter(1, 'Ada Lovelace', 'ada.example.com', 'backend')
        with self.assertRaisesMessage(ValueError, 'Invalid email'):
            reporter.validate()

    def test_to_dict_returns_fields(self):
        reporter = Reporter(1, 'Ada Lovelace', 'ada@example.com', 'backend')
        self.assertEqual(
            reporter.to_dict(),
            {
                'id': 1,
                'name': 'Ada Lovelace',
                'email': 'ada@example.com',
                'team': 'backend',
            },
        )


class IssueModelTests(TestCase):
    def test_validate_rejects_empty_title(self):
        issue = Issue(1, '', 'details', 'open', 'high', 1)
        with self.assertRaisesMessage(ValueError, 'Title cannot be empty'):
            issue.validate()

    def test_validate_rejects_unknown_status_and_priority(self):
        bad_status = Issue(1, 'Login bug', 'details', 'done', 'high', 1)
        with self.assertRaisesMessage(ValueError, 'Invalid status'):
            bad_status.validate()

        bad_priority = Issue(1, 'Login bug', 'details', 'open', 'urgent', 1)
        with self.assertRaisesMessage(ValueError, 'Invalid priority'):
            bad_priority.validate()

    def test_describe_uses_priority_subclass(self):
        base = Issue(1, 'Slow query', 'details', 'open', 'medium', 1)
        critical = CriticalIssue(2, 'Login button not working on mobile', 'details', 'open', 'critical', 1)
        low = LowPriorityIssue(3, 'Rename label', 'details', 'open', 'low', 1)

        self.assertEqual(base.describe(), 'Slow query [medium]')
        self.assertEqual(
            critical.describe(),
            '[URGENT] Login button not working on mobile — needs immediate attention',
        )
        self.assertEqual(low.describe(), 'Rename label — low priority, handle when free')


class ApiTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reporters_file = os.path.join(self.tmp.name, 'reporters.json')
        self.issues_file = os.path.join(self.tmp.name, 'issues.json')
        self.patches = [
            patch('issues.views.REPORTERS_FILE', self.reporters_file),
            patch('issues.views.ISSUES_FILE', self.issues_file),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def _post(self, path, payload):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_reporter_create_list_and_lookup(self):
        created = self._post('/api/reporters/', {
            'id': 1,
            'name': 'Ada Lovelace',
            'email': 'ada@example.com',
            'team': 'backend',
        })
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()['email'], 'ada@example.com')

        empty_name = self._post('/api/reporters/', {
            'id': 2,
            'name': '',
            'email': 'ada@example.com',
            'team': 'backend',
        })
        self.assertEqual(empty_name.status_code, 400)
        self.assertEqual(empty_name.json(), {'error': 'Name cannot be empty'})

        bad_email = self._post('/api/reporters/', {
            'id': 2,
            'name': 'Grace Hopper',
            'email': 'grace.example.com',
            'team': 'devops',
        })
        self.assertEqual(bad_email.status_code, 400)
        self.assertEqual(bad_email.json(), {'error': 'Invalid email'})

        listing = self.client.get('/api/reporters/')
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)

        one = self.client.get('/api/reporters/?id=1')
        self.assertEqual(one.status_code, 200)
        self.assertEqual(one.json()['name'], 'Ada Lovelace')

        missing = self.client.get('/api/reporters/?id=99')
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {'error': 'Reporter not found'})

    def test_issue_create_uses_priority_subclass_message(self):
        payload = {
            'id': 1,
            'title': 'Login button not working on mobile',
            'description': 'Users on iOS 17 cannot tap the login button',
            'status': 'open',
            'priority': 'critical',
            'reporter_id': 1,
        }
        created = self._post('/api/issues/', payload)
        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertEqual(body['id'], 1)
        self.assertEqual(body['title'], payload['title'])
        self.assertEqual(body['description'], payload['description'])
        self.assertEqual(body['status'], 'open')
        self.assertEqual(body['priority'], 'critical')
        self.assertEqual(body['reporter_id'], 1)
        self.assertIn('created_at', body)
        self.assertEqual(
            body['message'],
            '[URGENT] Login button not working on mobile — needs immediate attention',
        )

        low = self._post('/api/issues/', {
            'id': 2,
            'title': 'Rename label',
            'description': 'Copy tweak',
            'status': 'open',
            'priority': 'low',
            'reporter_id': 1,
        })
        self.assertEqual(
            low.json()['message'],
            'Rename label — low priority, handle when free',
        )

        medium = self._post('/api/issues/', {
            'id': 3,
            'title': 'Slow query',
            'description': 'Dashboard timeout',
            'status': 'in_progress',
            'priority': 'medium',
            'reporter_id': 1,
        })
        self.assertEqual(medium.json()['message'], 'Slow query [medium]')

        high = self._post('/api/issues/', {
            'id': 4,
            'title': 'Payment retry',
            'description': 'Webhook drops events',
            'status': 'resolved',
            'priority': 'high',
            'reporter_id': 1,
        })
        self.assertEqual(high.json()['message'], 'Payment retry [high]')

    def test_issue_validation_and_filters(self):
        empty_title = self._post('/api/issues/', {
            'id': 1,
            'title': '',
            'description': 'details',
            'status': 'open',
            'priority': 'high',
            'reporter_id': 1,
        })
        self.assertEqual(empty_title.status_code, 400)
        self.assertEqual(empty_title.json(), {'error': 'Title cannot be empty'})

        bad_status = self._post('/api/issues/', {
            'id': 1,
            'title': 'Login bug',
            'description': 'details',
            'status': 'done',
            'priority': 'high',
            'reporter_id': 1,
        })
        self.assertEqual(bad_status.status_code, 400)
        self.assertEqual(bad_status.json(), {'error': 'Invalid status'})

        created = self._post('/api/issues/', {
            'id': 1,
            'title': 'Login bug',
            'description': 'details',
            'status': 'open',
            'priority': 'high',
            'reporter_id': 1,
        })
        self.assertEqual(created.status_code, 201)

        duplicate = self._post('/api/issues/', {
            'id': 1,
            'title': 'Another bug',
            'description': 'details',
            'status': 'closed',
            'priority': 'low',
            'reporter_id': 1,
        })
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate.json(), {'error': 'Issue already exists'})

        one = self.client.get('/api/issues/?id=1')
        self.assertEqual(one.status_code, 200)
        self.assertEqual(one.json()['title'], 'Login bug')
        self.assertNotIn('message', one.json())

        missing = self.client.get('/api/issues/?id=42')
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {'error': 'Issue not found'})

        opened = self.client.get('/api/issues/?status=open')
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(len(opened.json()), 1)

        closed = self.client.get('/api/issues/?status=closed')
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.json(), [])

        invalid_status = self.client.get('/api/issues/?status=done')
        self.assertEqual(invalid_status.status_code, 400)
        self.assertEqual(invalid_status.json(), {'error': 'Invalid status'})
