from os.path import join, exists, dirname
from os import getcwd, mkdir, environ
from logging import getLogger

from requests_oauthlib import OAuth2Session
from requests import get

github_client_id = environ.get('GITHUB_CLIENT_ID') or r'e62e0d541bb6d0125b62'
github_client_secret = environ.get('GITHUB_CLIENT_SECRET') or r'1f488407e92a59beb897814e9240b5a06a2020e3'

jlogger = getLogger('jekit')

ERR_NO_REPOSITORY = 'Missing repository'
ERR_PENDING_MESSAGE = 'Test in progress'
ERR_NO_REF_STATUS = 'Missing statuses for ref'

class PrivateRepoException (Exception): pass

class MissingRepoException (Exception): pass

class MissingRefException (Exception): pass

def get_circle_artifacts(owner, repo, ref, github_token):
    '''
    '''
    import requests, urlparse, os.path
    
    circle_token = environ.get('CIRCLECI_TOKEN') or 'a17131792f4c4bcb97f2f66d9c58258a0ee0e621'
    
    github_auth = github_token.get('access_token'), 'x-oauth-basic'
    status_url = 'https://api.github.com/repos/{owner}/{repo}/statuses/{ref}'.format(**locals())
    status_resp = requests.get(status_url, auth=github_auth)
    
    if status_resp.status_code == 404:
        raise RuntimeError(ERR_NO_REPOSITORY)
    elif status_resp.status_code != 200:
        raise RuntimeError('some other HTTP status: {}'.format(status_resp.status_code))
    
    if len(status_resp.json()) == 0:
        raise RuntimeError(ERR_NO_REF_STATUS)

    status = status_resp.json()[0]
    
    if status['state'] == 'pending':
        raise RuntimeError(ERR_PENDING_MESSAGE)
    elif status['state'] != 'success':
        raise RuntimeError('some other test outcome: {state}'.format(**status))

    circle_url = status['target_url'] if (status['state'] == 'success') else None
    circle_build = os.path.relpath(urlparse.urlparse(circle_url).path, '/gh/')

    artifacts_url = 'https://circleci.com/api/v1/project/{}/artifacts?circle-token={}'.format(circle_build, circle_token)
    artifacts = {os.path.relpath(a['pretty_path'], '$CIRCLE_ARTIFACTS'): '{}?circle-token={}'.format(a['url'], circle_token)
                 for a in requests.get(artifacts_url, headers=dict(Accept='application/json')).json()}
    
    return artifacts

#
# Messy test crap.
#
import unittest
from httmock import HTTMock, response

class TestGit (unittest.TestCase):

    def response_content(self, url, request):
        '''
        '''
        MHP = request.method, url.hostname, url.path
        MHPQ = request.method, url.hostname, url.path, url.query
        GH, CC = 'api.github.com', 'circleci.com'
        response_headers = {'Content-Type': 'application/json; charset=utf-8'}

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/statuses/master'):
            data = u'''[\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403320253,\r    "state": "success",\r    "description": "Your tests passed on CircleCI!",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/13",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T22:49:42Z",\r    "updated_at": "2015-12-30T22:49:42Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403319747,\r    "state": "pending",\r    "description": "CircleCI is running your tests",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/13",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T22:48:48Z",\r    "updated_at": "2015-12-30T22:48:48Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403319729,\r    "state": "pending",\r    "description": "Your tests are queued behind your running builds",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/13",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T22:48:47Z",\r    "updated_at": "2015-12-30T22:48:47Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403274989,\r    "state": "success",\r    "description": "Your tests passed on CircleCI!",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/12",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:38:53Z",\r    "updated_at": "2015-12-30T21:38:53Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403274443,\r    "state": "pending",\r    "description": "CircleCI is running your tests",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/12",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:38:00Z",\r    "updated_at": "2015-12-30T21:38:00Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403274434,\r    "state": "pending",\r    "description": "Your tests are queued behind your running builds",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/12",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:37:59Z",\r    "updated_at": "2015-12-30T21:37:59Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  }\r]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/statuses/no-branch'):
            data = u'''[\r\r]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/no-repo/statuses/master'):
            data = u'''{\r  "message": "Not Found",\r  "documentation_url": "https://developer.github.com/v3"\r}'''
            return response(404, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/statuses/4872caf32'):
            data = u'''[\r    {\r        "context": "ci/circleci",\r        "created_at": "2016-01-06T05:36:44Z",\r        "creator": {\r            "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r            "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r            "followers_url": "https://api.github.com/users/migurski/followers",\r            "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r            "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r            "gravatar_id": "",\r            "html_url": "https://github.com/migurski",\r            "id": 58730,\r            "login": "migurski",\r            "organizations_url": "https://api.github.com/users/migurski/orgs",\r            "received_events_url": "https://api.github.com/users/migurski/received_events",\r            "repos_url": "https://api.github.com/users/migurski/repos",\r            "site_admin": false,\r            "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r            "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r            "type": "User",\r            "url": "https://api.github.com/users/migurski"\r        },\r        "description": "CircleCI is running your tests",\r        "id": 406914381,\r        "state": "pending",\r        "target_url": "https://circleci.com/gh/migurski/circlejek/21",\r        "updated_at": "2016-01-06T05:36:44Z",\r        "url": "https://api.github.com/repos/migurski/circlejek/statuses/4872caf3203972ebbe13e3863e4c47c407ee4bbf"\r    },\r    {\r        "context": "ci/circleci",\r        "created_at": "2016-01-06T05:36:43Z",\r        "creator": {\r            "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r            "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r            "followers_url": "https://api.github.com/users/migurski/followers",\r            "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r            "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r            "gravatar_id": "",\r            "html_url": "https://github.com/migurski",\r            "id": 58730,\r            "login": "migurski",\r            "organizations_url": "https://api.github.com/users/migurski/orgs",\r            "received_events_url": "https://api.github.com/users/migurski/received_events",\r            "repos_url": "https://api.github.com/users/migurski/repos",\r            "site_admin": false,\r            "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r            "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r            "type": "User",\r            "url": "https://api.github.com/users/migurski"\r        },\r        "description": "Your tests are queued behind your running builds",\r        "id": 406914377,\r        "state": "pending",\r        "target_url": "https://circleci.com/gh/migurski/circlejek/21",\r        "updated_at": "2016-01-06T05:36:43Z",\r        "url": "https://api.github.com/repos/migurski/circlejek/statuses/4872caf3203972ebbe13e3863e4c47c407ee4bbf"\r    }\r]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHPQ == ('GET', 'circleci.com', '/api/v1/project/migurski/circlejek/13/artifacts', 'circle-token=a17131792f4c4bcb97f2f66d9c58258a0ee0e621'):
            data = u'''[{"path":"/tmp/circle-artifacts.6VLZE7m/goodbye.html","pretty_path":"$CIRCLE_ARTIFACTS/goodbye.html","node_index":0,"url":"https://circle-artifacts.com/gh/migurski/circlejek/13/artifacts/0/tmp/circle-artifacts.6VLZE7m/goodbye.html"},{"path":"/tmp/circle-artifacts.6VLZE7m/index.html","pretty_path":"$CIRCLE_ARTIFACTS/index.html","node_index":0,"url":"https://circle-artifacts.com/gh/migurski/circlejek/13/artifacts/0/tmp/circle-artifacts.6VLZE7m/index.html"}]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        raise Exception(MHPQ)
    
    def test_existing_master(self):
        with HTTMock(self.response_content):
            artifacts = get_circle_artifacts('migurski', 'circlejek', 'master', {})
            self.assertIn('index.html', artifacts)
    
    def test_nonexistent_branch(self):
        with HTTMock(self.response_content):
            with self.assertRaises(RuntimeError) as r:
                get_circle_artifacts('migurski', 'circlejek', 'no-branch', {})
                self.assertEqual(r.exception.message, ERR_NO_REF_STATUS)
    
    def test_nonexistent_repository(self):
        with HTTMock(self.response_content):
            with self.assertRaises(RuntimeError) as r:
                get_circle_artifacts('migurski', 'no-repo', 'master', {})
                self.assertEqual(r.exception.message, ERR_NO_REPOSITORY)
    
    def test_unfinished_test(self):
        with HTTMock(self.response_content):
            with self.assertRaises(RuntimeError) as r:
                get_circle_artifacts('migurski', 'circlejek', '4872caf32', {})
                self.assertEqual(r.exception.message, ERR_PENDING_MESSAGE)
