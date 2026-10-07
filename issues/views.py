import json
import os

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from issues.models import CriticalIssue, Issue, LowPriorityIssue, Reporter

REPORTERS_FILE = os.path.join(settings.BASE_DIR, 'reporters.json')
ISSUES_FILE = os.path.join(settings.BASE_DIR, 'issues.json')

ISSUE_FIELDS = ('id', 'title', 'description', 'status', 'priority', 'reporter_id')
REPORTER_FIELDS = ('id', 'name', 'email', 'team')


def _json(data, status=200, safe=True):
    return JsonResponse(
        data,
        status=status,
        safe=safe,
        json_dumps_params={'ensure_ascii': False},
    )


def _load_records(path):
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as handle:
        raw = handle.read().strip()
    if not raw:
        return []
    return json.loads(raw)


def _save_records(path, records):
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(records, handle, indent=2)
        handle.write('\n')


def _read_body(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return None, _json({'error': 'Invalid JSON'}, status=400)
    if not isinstance(data, dict):
        return None, _json({'error': 'JSON body must be an object'}, status=400)
    return data, None


def _missing_field(data, fields):
    for field in fields:
        if field not in data:
            return _json({'error': f'{field} is required'}, status=400)
    return None


@csrf_exempt
def reporters_view(request):
    if request.method == 'GET':
        return _get_reporters(request)
    if request.method == 'POST':
        return _create_reporter(request)
    return _json({'error': 'Method not allowed'}, status=405)


def _get_reporters(request):
    reporters = _load_records(REPORTERS_FILE)
    reporter_id = request.GET.get('id')
    if reporter_id is None:
        return _json(reporters, safe=False, status=200)

    try:
        reporter_id = int(reporter_id)
    except ValueError:
        return _json({'error': 'Invalid id'}, status=400)

    for reporter in reporters:
        if reporter['id'] == reporter_id:
            return _json(reporter, status=200)
    return _json({'error': 'Reporter not found'}, status=404)


def _create_reporter(request):
    data, error = _read_body(request)
    if error:
        return error

    missing = _missing_field(data, REPORTER_FIELDS)
    if missing:
        return missing

    try:
        reporter_id = int(data['id'])
    except (TypeError, ValueError):
        return _json({'error': 'id must be an integer'}, status=400)

    reporter = Reporter(
        id=reporter_id,
        name=data['name'],
        email=data['email'],
        team=data['team'],
    )
    try:
        reporter.validate()
    except ValueError as exc:
        return _json({'error': str(exc)}, status=400)

    reporters = _load_records(REPORTERS_FILE)
    if any(record['id'] == reporter_id for record in reporters):
        return _json({'error': 'Reporter already exists'}, status=400)

    record = reporter.to_dict()
    reporters.append(record)
    _save_records(REPORTERS_FILE, reporters)
    return _json(record, status=201)


@csrf_exempt
def issues_view(request):
    if request.method == 'GET':
        return _get_issues(request)
    if request.method == 'POST':
        return _create_issue(request)
    return _json({'error': 'Method not allowed'}, status=405)


def _get_issues(request):
    issues = _load_records(ISSUES_FILE)
    issue_id = request.GET.get('id')
    status = request.GET.get('status')

    if issue_id is not None:
        try:
            issue_id = int(issue_id)
        except ValueError:
            return _json({'error': 'Invalid id'}, status=400)
        for issue in issues:
            if issue['id'] == issue_id:
                return _json(issue, status=200)
        return _json({'error': 'Issue not found'}, status=404)

    if status is not None:
        if status not in Issue.ALLOWED_STATUSES:
            return _json({'error': 'Invalid status'}, status=400)
        filtered = [issue for issue in issues if issue['status'] == status]
        return _json(filtered, safe=False, status=200)

    return _json(issues, safe=False, status=200)


def _create_issue(request):
    data, error = _read_body(request)
    if error:
        return error

    missing = _missing_field(data, ISSUE_FIELDS)
    if missing:
        return missing

    try:
        issue_id = int(data['id'])
        reporter_id = int(data['reporter_id'])
    except (TypeError, ValueError):
        return _json({'error': 'id and reporter_id must be integers'}, status=400)

    title = data['title']
    description = data['description']
    status = data['status']
    priority = data['priority']

    if priority == 'critical':
        issue = CriticalIssue(issue_id, title, description, status, priority, reporter_id)
    elif priority == 'low':
        issue = LowPriorityIssue(issue_id, title, description, status, priority, reporter_id)
    else:
        issue = Issue(issue_id, title, description, status, priority, reporter_id)

    try:
        issue.validate()
    except ValueError as exc:
        return _json({'error': str(exc)}, status=400)

    issues = _load_records(ISSUES_FILE)
    if any(record['id'] == issue.id for record in issues):
        return _json({'error': 'Issue already exists'}, status=400)

    record = issue.to_dict()
    issues.append(record)
    _save_records(ISSUES_FILE, issues)

    response_data = issue.to_dict()
    response_data['message'] = issue.describe()
    return _json(response_data, status=201)
