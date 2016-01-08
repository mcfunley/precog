from os.path import relpath, join
from urlparse import urlparse
from logging import getLogger
from base64 import b64decode
from os import environ
from time import time

from requests_oauthlib import OAuth2Session
import requests
import yaml

github_client_id = environ.get('GITHUB_CLIENT_ID') or r'e62e0d541bb6d0125b62'
github_client_secret = environ.get('GITHUB_CLIENT_SECRET') or r'1f488407e92a59beb897814e9240b5a06a2020e3'

ERR_NO_REPOSITORY = 'Missing repository'
ERR_TESTS_PENDING = 'Test in progress'
ERR_TESTS_FAILED = 'Test failed'
ERR_NO_REF_STATUS = 'Missing statuses for ref'

_GITHUB_USER_URL = 'https://api.github.com/user'
_GITHUB_REPO_URL = 'https://api.github.com/repos/{owner}/{repo}'
_GITHUB_REPO_HEAD_URL = 'https://api.github.com/repos/{owner}/{repo}/git/{head}'
_GITHUB_COMMIT_URL = 'https://api.github.com/repos/{owner}/{repo}/commits/{sha}'
_GITHUB_TREE_URL = 'https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}'
_GITHUB_STATUS_URL = 'https://api.github.com/repos/{owner}/{repo}/statuses/{ref}'
_CIRCLECI_ARTIFACTS_URL = 'https://circleci.com/api/v1/project/{build}/artifacts?circle-token={token}'

class Getter:
    ''' Wrapper for HTTP GET from requests.
    '''
    def __init__(self, github_auth, cache={}):
        self.github_auth = github_auth
        self.responses = cache
    
    def _flush(self):
        ''' Flush past-deadline responses.
        '''
        for (k, (r, d)) in self.responses.items():
            if (time() > d):
                self.responses.pop(k)
    
    def get(self, url):
        self._flush()
        
        host = urlparse(url).hostname
        auth = self.github_auth if (host == 'api.github.com') else None
        key = (url, auth)
        
        if key in self.responses:
            return self.responses[key][0]
        
        if host == 'api.github.com':
            getLogger('precog').warning('GET {}'.format(url))

        resp = requests.get(url, auth=auth, headers=dict(Accept='application/json'), timeout=2)
        
        self.responses[key] = (resp, time() + 15)
        return resp

def is_authenticated(GET):
    ''' Return True if given username/password is valid for a Github user.
    '''
    user_resp = GET(_GITHUB_USER_URL)
    
    return bool(user_resp.status_code == 200)

def repo_exists(owner, repo, GET):
    ''' Return True if given owner/repo exists in Github.
    '''
    repo_url = _GITHUB_REPO_URL.format(owner=owner, repo=repo)
    repo_resp = GET(repo_url)
    
    return bool(repo_resp.status_code == 200)

def split_branch_path(owner, repo, path, GET):
    ''' Return existing branch name and remaining path for a given path.
        
        Branch name might contain slashes.
    '''
    branch_parts, path_parts = [], path.split('/')
    
    while path_parts:
        branch_parts.append(path_parts.pop(0))
        ref = '/'.join(branch_parts)
        
        if len(branch_parts) == 1:
            # See if it's a regular commit first.
            commit_url = _GITHUB_COMMIT_URL.format(owner=owner, repo=repo, sha=ref)
            commit_resp = GET(commit_url)
            
            if commit_resp.status_code == 200:  
                # Stop early, we've found a commit.
                return ref, '/'.join(path_parts)
    
        head = 'refs/heads/{}'.format(ref)
        head_url = _GITHUB_REPO_HEAD_URL.format(owner=owner, repo=repo, head=head)
        head_resp = GET(head_url)
        
        if head_resp.status_code != 200:
            # Not found at all.
            continue
        
        if not hasattr(head_resp.json(), 'get'):
            # There are more refs under this path, get more specific.
            continue
        
        if head_resp.json().get('ref') != head:
            # Found a single ref and it is wrong.
            break
            
        return ref, '/'.join(path_parts)

    return None, path

def find_base_path(owner, repo, ref, GET):
    ''' Return artifacts base path after reading Circle config.
    '''
    tree_url = _GITHUB_TREE_URL.format(owner=owner, repo=repo, ref=ref)
    tree_resp = GET(tree_url)
    
    paths = {item['path']: item['url'] for item in tree_resp.json()['tree']}
    
    if 'circle.yml' not in paths:
        return '$CIRCLE_ARTIFACTS'
    
    blob_url = paths['circle.yml']
    blob_resp = GET(blob_url)
    blob_yaml = b64decode(blob_resp.json()['content'])
    circle_config = yaml.load(blob_yaml)
    
    paths = circle_config.get('general', {}).get('artifacts', [])
    
    if not paths:
        return '$CIRCLE_ARTIFACTS'
    
    return join('/home/ubuntu/{}/'.format(repo), paths[0])

def get_circle_artifacts(owner, repo, ref, GET):
    ''' Return dictionary of CircleCI artifacts for a given Github repo ref.
    '''
    circle_token = environ.get('CIRCLECI_TOKEN') or 'a17131792f4c4bcb97f2f66d9c58258a0ee0e621'
    
    status_url = _GITHUB_STATUS_URL.format(owner=owner, repo=repo, ref=ref)
    status_resp = GET(status_url)
    
    if status_resp.status_code == 404:
        raise RuntimeError(ERR_NO_REPOSITORY)
    elif status_resp.status_code != 200:
        raise RuntimeError('some other HTTP status: {}'.format(status_resp.status_code))
    
    if len(status_resp.json()) == 0:
        raise RuntimeError(ERR_NO_REF_STATUS)

    status = status_resp.json()[0]
    
    if status['state'] == 'pending':
        raise RuntimeError(ERR_TESTS_PENDING)
    elif status['state'] == 'error':
        raise RuntimeError(ERR_TESTS_FAILED)
    elif status['state'] != 'success':
        raise RuntimeError('some other test outcome: {state}'.format(**status))

    circle_url = status['target_url'] if (status['state'] == 'success') else None
    circle_build = relpath(urlparse(circle_url).path, '/gh/')

    artifacts_base = find_base_path(owner, repo, ref, GET)
    artifacts_url = _CIRCLECI_ARTIFACTS_URL.format(build=circle_build, token=circle_token)
    artifacts = {relpath(a['pretty_path'], artifacts_base): '{}?circle-token={}'.format(a['url'], circle_token)
                 for a in GET(artifacts_url).json()}
    
    return artifacts

def select_path(paths, path):
    '''
    '''
    if path in paths:
        return path
    
    if path == '':
        return 'index.html'

    return '{}/index.html'.format(path.rstrip('/'))

#
# Messy test crap.
#
import unittest
from httmock import HTTMock, response

class TestGit (unittest.TestCase):

    def setUp(self):
        self.GET = Getter(tuple(), dict()).get

    def response_content(self, url, request):
        '''
        '''
        MHP = request.method, url.hostname, url.path
        MHPQ = request.method, url.hostname, url.path, url.query
        GH, CC = 'api.github.com', 'circleci.com'
        response_headers = {'Content-Type': 'application/json; charset=utf-8'}
        
        if MHP == ('GET', 'api.github.com', '/user'):
            if request.headers.get('Authorization') == 'Basic dmFsaWQ6eC1vYXV0aC1iYXNpYw==':
                data = u'''{\r  "login": "migurski",\r  "id": 58730,\r  "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r  "gravatar_id": "",\r  "url": "https://api.github.com/users/migurski",\r  "html_url": "https://github.com/migurski",\r  "followers_url": "https://api.github.com/users/migurski/followers",\r  "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r  "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r  "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r  "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r  "organizations_url": "https://api.github.com/users/migurski/orgs",\r  "repos_url": "https://api.github.com/users/migurski/repos",\r  "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r  "received_events_url": "https://api.github.com/users/migurski/received_events",\r  "type": "User",\r  "site_admin": false,\r  "name": null,\r  "company": null,\r  "blog": null,\r  "location": null,\r  "email": "mike-github@teczno.com",\r  "hireable": null,\r  "bio": null,\r  "public_repos": 91,\r  "public_gists": 45,\r  "followers": 439,\r  "following": 94,\r  "created_at": "2009-02-27T23:44:32Z",\r  "updated_at": "2015-12-26T20:09:55Z",\r  "private_gists": 23,\r  "total_private_repos": 1,\r  "owned_private_repos": 0,\r  "disk_usage": 249156,\r  "collaborators": 0,\r  "plan": {\r    "name": "free",\r    "space": 976562499,\r    "collaborators": 0,\r    "private_repos": 0\r  }\r}'''
                return response(200, data.encode('utf8'), headers=response_headers)
            else:
                data = u'''{\r  "message": "Bad credentials",\r  "documentation_url": "https://developer.github.com/v3"\r}'''
                return response(401, data.encode('utf8'), headers=response_headers)
        
        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/statuses/master'):
            data = u'''[\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403320253,\r    "state": "success",\r    "description": "Your tests passed on CircleCI!",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/13",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T22:49:42Z",\r    "updated_at": "2015-12-30T22:49:42Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403319747,\r    "state": "pending",\r    "description": "CircleCI is running your tests",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/13",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T22:48:48Z",\r    "updated_at": "2015-12-30T22:48:48Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403319729,\r    "state": "pending",\r    "description": "Your tests are queued behind your running builds",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/13",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T22:48:47Z",\r    "updated_at": "2015-12-30T22:48:47Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403274989,\r    "state": "success",\r    "description": "Your tests passed on CircleCI!",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/12",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:38:53Z",\r    "updated_at": "2015-12-30T21:38:53Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403274443,\r    "state": "pending",\r    "description": "CircleCI is running your tests",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/12",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:38:00Z",\r    "updated_at": "2015-12-30T21:38:00Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/6f82dac4d909926b2d099ef9ef2db7bd3e97e1a7",\r    "id": 403274434,\r    "state": "pending",\r    "description": "Your tests are queued behind your running builds",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/12",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:37:59Z",\r    "updated_at": "2015-12-30T21:37:59Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  }\r]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/statuses/untested'):
            data = u'''[\r\r]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/mapzen/blog/git/refs/heads/drew/dc-transit-events-2016/blog/mapzen-in-dc') \
        or MHP == ('GET', 'api.github.com', '/repos/mapzen/blog/git/refs/heads/drew/dc-transit-events-2016/blog/') \
        or MHP == ('GET', 'api.github.com', '/repos/mapzen/blog/git/refs/heads/drew/dc-transit-events-2016/blog') \
        or MHP == ('GET', 'api.github.com', '/repos/mapzen/blog/git/refs/heads/drew/dc-transit-events-2016/') \
        or MHP == ('GET', 'api.github.com', '/repos/mapzen/blog/commits/drew'):
            data = u'''{\r  "message": "Not Found",\r  "documentation_url": "https://developer.github.com/v3"\r}'''
            return response(404, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/mapzen/blog/git/refs/heads/drew'):
            data = u'''[\r  {\r    "ref": "refs/heads/drew/dc-transit-events-2016",\r    "url": "https://api.github.com/repos/mapzen/blog/git/refs/heads/drew/dc-transit-events-2016",\r    "object": {\r      "sha": "8ee949969fe93f3cffa0e2f4d0e208fa848d4028",\r      "type": "commit",\r      "url": "https://api.github.com/repos/mapzen/blog/git/commits/8ee949969fe93f3cffa0e2f4d0e208fa848d4028"\r    }\r  },\r  {\r    "ref": "refs/heads/drew/period",\r    "url": "https://api.github.com/repos/mapzen/blog/git/refs/heads/drew/period",\r    "object": {\r      "sha": "7b6a60ee7f70bc73a9866cf15aef9632470571ec",\r      "type": "commit",\r      "url": "https://api.github.com/repos/mapzen/blog/git/commits/7b6a60ee7f70bc73a9866cf15aef9632470571ec"\r    }\r  }\r]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/mapzen/blog/commits/8d0c610'):
            data = u'''{\r  "sha": "8d0c61056cf9d04deaa85193abab1c621dfe9ac3",\r  "commit": {\r    "author": {\r      "name": "burritojustice",\r      "email": "john@mapzen.com",\r      "date": "2016-01-06T20:00:24Z"\r    },\r    "committer": {\r      "name": "burritojustice",\r      "email": "john@mapzen.com",\r      "date": "2016-01-06T20:00:24Z"\r    },\r    "message": "Merge pull request #645 from mapzen/drew/dc-transit-events-2016\\n\\nTransportation Research Board 2016 blog post",\r    "tree": {\r      "sha": "8979e25929b9c9fce63c75e65b08b2d3edaafac6",\r      "url": "https://api.github.com/repos/mapzen/blog/git/trees/8979e25929b9c9fce63c75e65b08b2d3edaafac6"\r    },\r    "url": "https://api.github.com/repos/mapzen/blog/git/commits/8d0c61056cf9d04deaa85193abab1c621dfe9ac3",\r    "comment_count": 0\r  },\r  "url": "https://api.github.com/repos/mapzen/blog/commits/8d0c61056cf9d04deaa85193abab1c621dfe9ac3",\r  "html_url": "https://github.com/mapzen/blog/commit/8d0c61056cf9d04deaa85193abab1c621dfe9ac3",\r  "comments_url": "https://api.github.com/repos/mapzen/blog/commits/8d0c61056cf9d04deaa85193abab1c621dfe9ac3/comments",\r  "author": {\r    "login": "burritojustice",\r    "id": 3979711,\r    "avatar_url": "https://avatars.githubusercontent.com/u/3979711?v=3",\r    "gravatar_id": "",\r    "url": "https://api.github.com/users/burritojustice",\r    "html_url": "https://github.com/burritojustice",\r    "followers_url": "https://api.github.com/users/burritojustice/followers",\r    "following_url": "https://api.github.com/users/burritojustice/following{/other_user}",\r    "gists_url": "https://api.github.com/users/burritojustice/gists{/gist_id}",\r    "starred_url": "https://api.github.com/users/burritojustice/starred{/owner}{/repo}",\r    "subscriptions_url": "https://api.github.com/users/burritojustice/subscriptions",\r    "organizations_url": "https://api.github.com/users/burritojustice/orgs",\r    "repos_url": "https://api.github.com/users/burritojustice/repos",\r    "events_url": "https://api.github.com/users/burritojustice/events{/privacy}",\r    "received_events_url": "https://api.github.com/users/burritojustice/received_events",\r    "type": "User",\r    "site_admin": false\r  },\r  "committer": {\r    "login": "burritojustice",\r    "id": 3979711,\r    "avatar_url": "https://avatars.githubusercontent.com/u/3979711?v=3",\r    "gravatar_id": "",\r    "url": "https://api.github.com/users/burritojustice",\r    "html_url": "https://github.com/burritojustice",\r    "followers_url": "https://api.github.com/users/burritojustice/followers",\r    "following_url": "https://api.github.com/users/burritojustice/following{/other_user}",\r    "gists_url": "https://api.github.com/users/burritojustice/gists{/gist_id}",\r    "starred_url": "https://api.github.com/users/burritojustice/starred{/owner}{/repo}",\r    "subscriptions_url": "https://api.github.com/users/burritojustice/subscriptions",\r    "organizations_url": "https://api.github.com/users/burritojustice/orgs",\r    "repos_url": "https://api.github.com/users/burritojustice/repos",\r    "events_url": "https://api.github.com/users/burritojustice/events{/privacy}",\r    "received_events_url": "https://api.github.com/users/burritojustice/received_events",\r    "type": "User",\r    "site_admin": false\r  },\r  "parents": [\r    {\r      "sha": "682362db1dba88cf90b5123b801e3e4be9203ebc",\r      "url": "https://api.github.com/repos/mapzen/blog/commits/682362db1dba88cf90b5123b801e3e4be9203ebc",\r      "html_url": "https://github.com/mapzen/blog/commit/682362db1dba88cf90b5123b801e3e4be9203ebc"\r    },\r    {\r      "sha": "8ee949969fe93f3cffa0e2f4d0e208fa848d4028",\r      "url": "https://api.github.com/repos/mapzen/blog/commits/8ee949969fe93f3cffa0e2f4d0e208fa848d4028",\r      "html_url": "https://github.com/mapzen/blog/commit/8ee949969fe93f3cffa0e2f4d0e208fa848d4028"\r    }\r  ],\r  "stats": {\r    "total": 21,\r    "additions": 21,\r    "deletions": 0\r  },\r  "files": [\r    {\r      "sha": "736a678befc18eb0b65078e2ed009329d381c917",\r      "filename": "_posts/2016-01-05-mapzen-in-dc.md",\r      "status": "added",\r      "additions": 21,\r      "deletions": 0,\r      "changes": 21,\r      "blob_url": "https://github.com/mapzen/blog/blob/8d0c61056cf9d04deaa85193abab1c621dfe9ac3/_posts/2016-01-05-mapzen-in-dc.md",\r      "raw_url": "https://github.com/mapzen/blog/raw/8d0c61056cf9d04deaa85193abab1c621dfe9ac3/_posts/2016-01-05-mapzen-in-dc.md",\r      "contents_url": "https://api.github.com/repos/mapzen/blog/contents/_posts/2016-01-05-mapzen-in-dc.md?ref=8d0c61056cf9d04deaa85193abab1c621dfe9ac3",\r      "patch": "@@ -0,0 +1,21 @@\\n+---\\n+layout: page\\n+category: blog\\n+published: true\\n+title: Mapzen \"transpo\" in DC\\n+excerpt: Mapzen's joining thousands of enthusiasts and professionals in Washington, D.C. to start off a new year of transportation research, planning, and advocacy.\\n+image: \"/images/mapzen-in-dc/dcmetro.jpg\"\\n+authors: [drewda]\\n+tags: [transitland]\\n+---\\n+![DC Metro](/images/mapzen-in-dc/dcmetro.jpg)\\n+\\n+Each January brings thousands of \"transpo\" professionals and enthusiasts to Washington, D.C. to discuss train schedules, road pavement, bridge engineering, and the many other intricacies of transportation. [Transportation Camp](http://transportationcamp.org/events/dc-2016/) is an unconference that welcomes enthusiasts of all stripes, while the [Transportation Research Board's annual meeting](http://www.trb.org/AnnualMeeting/AnnualMeeting.aspx) is a more staid if also more massive meeting of professionals.\\n+\\n+Mapzen will be at the TRB meeting to discuss the [Transitland open transit data service](https://transit.land) and the [Mapzen Turn-by-Turn routing engine](https://mapzen.com/projects/valhalla). We'll be presenting at a TRB workshop called ***[Transformative Trends in Transit Data: General Transit Feed Specifications Bonanza](https://annualmeeting.mytrb.org/Workshop/Details/2446)*** on Sunday, January 10. Bring a laptop and learn how to create transit data from our colleagues at [The World Bank](http://www.worldbank.org/en/topic/transport), [Trillium Solutions](http://trilliumtransit.com/), [SUNY Albany](http://www.albany.edu/avail/), [MIT](http://www.civicdatadesignlab.org/), and [Azavea](http://www.azavea.com/). (TRB registration is required to attend.)\\n+\\n+And for a second year in a row, Mapzen is joining up with our colleagues at [Conveyal](http://conveyal.com/) and [TransitScreen](http://transitscreen.com/) to host a happy hour for mapping and \"transpo\" types of all sorts. All are welcome on the evening of Tuesday, January 12&mdash;TRB registration is not required to attend&mdash;but ***[please RSVP if you'll be joining us at the happy hour](https://trbparty.splashthat.com/)***. \\n+\\n+Can't make it to D.C. next week? Transportation Camp is popping up in at least [four more cities around the U.S. later in 2016](http://transportationcamp.org/). And in the meantime, you're invited to try out [Transitland](https://transit.land) and [Mapzen Turn-by-Turn](https://mapzen.com/projects/valhalla) here on the Internet.\\n+\\n+*[photo by Jeremy Segrott](https://www.flickr.com/photos/126337928@N05/18246320916/), CC BY 2.0*"\r    }\r  ]\r}'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/mapzen/blog/git/refs/heads/drew/dc-transit-events-2016'):
            data = u'''{\r    "object": {\r        "sha": "d2bb1bd6ef04bb0a0542acc6d5e07e150c960118",\r        "type": "commit",\r        "url": "https://api.github.com/repos/mapzen/blog/git/commits/d2bb1bd6ef04bb0a0542acc6d5e07e150c960118"\r    },\r    "ref": "refs/heads/drew/dc-transit-events-2016",\r    "url": "https://api.github.com/repos/mapzen/blog/git/refs/heads/drew/dc-transit-events-2016"\r}'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/git/trees/master'):
            data = u'''{\r  "sha": "4872caf3203972ebbe13e3863e4c47c407ee4bbf",\r  "url": "https://api.github.com/repos/migurski/circlejek/git/trees/4872caf3203972ebbe13e3863e4c47c407ee4bbf",\r  "tree": [\r    {\r      "path": "Gemfile",\r      "mode": "100644",\r      "type": "blob",\r      "sha": "e8a7006386e7ce6b8920b6d6e4283d0d833455d8",\r      "size": 44,\r      "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/e8a7006386e7ce6b8920b6d6e4283d0d833455d8"\r    },\r    {\r      "path": "_config.yml",\r      "mode": "100644",\r      "type": "blob",\r      "sha": "2701f62dc8b87aa6770518de051a938e7aa4e0fa",\r      "size": 53,\r      "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/2701f62dc8b87aa6770518de051a938e7aa4e0fa"\r    },\r    {\r      "path": "circle.yml",\r      "mode": "100644",\r      "type": "blob",\r      "sha": "52184fb8556ceb99165444a3388867e6664386d0",\r      "size": 106,\r      "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/52184fb8556ceb99165444a3388867e6664386d0"\r    },\r    {\r      "path": "goodbye.md",\r      "mode": "100644",\r      "type": "blob",\r      "sha": "2e4003d64f16a43a6d1e03de11c94b48e02fb1ff",\r      "size": 39,\r      "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/2e4003d64f16a43a6d1e03de11c94b48e02fb1ff"\r    },\r    {\r      "path": "index.md",\r      "mode": "100644",\r      "type": "blob",\r      "sha": "67e14c453494b9e4ee84b4d393a4ef5854ca9b33",\r      "size": 41,\r      "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/67e14c453494b9e4ee84b4d393a4ef5854ca9b33"\r    }\r  ],\r  "truncated": false\r}'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/git/blobs/52184fb8556ceb99165444a3388867e6664386d0'):
            data = u'''{\r  "sha": "52184fb8556ceb99165444a3388867e6664386d0",\r  "size": 106,\r  "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/52184fb8556ceb99165444a3388867e6664386d0",\r  "content": "bWFjaGluZToKICBydWJ5OgogICAgdmVyc2lvbjogMi4yLjMKdGVzdDoKICBv\\ndmVycmlkZToKICAgIC0gYnVuZGxlIGV4ZWMgamVreWxsIGJ1aWxkIC1kICRD\\nSVJDTEVfQVJUSUZBQ1RTCg==\\n",\r  "encoding": "base64"\r}'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/git/trees/tinker-with-config'):
            data = u'''{\r  "sha": "3c6431c3c1fa730b792bc039877623ef60435a77",\r  "url": "https://api.github.com/repos/migurski/circlejek/git/trees/3c6431c3c1fa730b792bc039877623ef60435a77",\r  "tree": [\r    {\r      "path": "Gemfile",\r      "mode": "100644",\r      "type": "blob",\r      "sha": "e8a7006386e7ce6b8920b6d6e4283d0d833455d8",\r      "size": 44,\r      "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/e8a7006386e7ce6b8920b6d6e4283d0d833455d8"\r    },\r    {\r      "path": "_config.yml",\r      "mode": "100644",\r      "type": "blob",\r      "sha": "2701f62dc8b87aa6770518de051a938e7aa4e0fa",\r      "size": 53,\r      "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/2701f62dc8b87aa6770518de051a938e7aa4e0fa"\r    },\r    {\r      "path": "circle.yml",\r      "mode": "100644",\r      "type": "blob",\r      "sha": "8bcc4f764bf2213d8fdfc34395e80abce9866e5d",\r      "size": 195,\r      "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/8bcc4f764bf2213d8fdfc34395e80abce9866e5d"\r    },\r    {\r      "path": "goodbye.md",\r      "mode": "100644",\r      "type": "blob",\r      "sha": "2e4003d64f16a43a6d1e03de11c94b48e02fb1ff",\r      "size": 39,\r      "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/2e4003d64f16a43a6d1e03de11c94b48e02fb1ff"\r    },\r    {\r      "path": "index.md",\r      "mode": "100644",\r      "type": "blob",\r      "sha": "67e14c453494b9e4ee84b4d393a4ef5854ca9b33",\r      "size": 41,\r      "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/67e14c453494b9e4ee84b4d393a4ef5854ca9b33"\r    }\r  ],\r  "truncated": false\r}'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/git/blobs/8bcc4f764bf2213d8fdfc34395e80abce9866e5d'):
            data = u'''{\r  "sha": "8bcc4f764bf2213d8fdfc34395e80abce9866e5d",\r  "size": 195,\r  "url": "https://api.github.com/repos/migurski/circlejek/git/blobs/8bcc4f764bf2213d8fdfc34395e80abce9866e5d",\r  "content": "bWFjaGluZToKICBydWJ5OgogICAgdmVyc2lvbjogMi4yLjMKdGVzdDoKICBv\\ndmVycmlkZToKICAgIC0gYnVuZGxlIGV4ZWMgamVreWxsIGJ1aWxkCiAgICAt\\nIGNwIC0tcmVjdXJzaXZlIC0tbm8tdGFyZ2V0LWRpcmVjdG9yeSAtLWxpbmsg\\nX3NpdGUgJENJUkNMRV9BUlRJRkFDVFMKZ2VuZXJhbDoKICBhcnRpZmFjdHM6\\nCiAgICAtICJfc2l0ZSIK\\n",\r  "encoding": "base64"\r}'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek'):
            data = u'''{\r  "id": 48819185,\r  "name": "circlejek",\r  "full_name": "migurski/circlejek",\r  "owner": {\r    "login": "migurski",\r    "id": 58730,\r    "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r    "gravatar_id": "",\r    "url": "https://api.github.com/users/migurski",\r    "html_url": "https://github.com/migurski",\r    "followers_url": "https://api.github.com/users/migurski/followers",\r    "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r    "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r    "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r    "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r    "organizations_url": "https://api.github.com/users/migurski/orgs",\r    "repos_url": "https://api.github.com/users/migurski/repos",\r    "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r    "received_events_url": "https://api.github.com/users/migurski/received_events",\r    "type": "User",\r    "site_admin": false\r  },\r  "private": false,\r  "html_url": "https://github.com/migurski/circlejek",\r  "description": "",\r  "fork": false,\r  "url": "https://api.github.com/repos/migurski/circlejek",\r  "forks_url": "https://api.github.com/repos/migurski/circlejek/forks",\r  "keys_url": "https://api.github.com/repos/migurski/circlejek/keys{/key_id}",\r  "collaborators_url": "https://api.github.com/repos/migurski/circlejek/collaborators{/collaborator}",\r  "teams_url": "https://api.github.com/repos/migurski/circlejek/teams",\r  "hooks_url": "https://api.github.com/repos/migurski/circlejek/hooks",\r  "issue_events_url": "https://api.github.com/repos/migurski/circlejek/issues/events{/number}",\r  "events_url": "https://api.github.com/repos/migurski/circlejek/events",\r  "assignees_url": "https://api.github.com/repos/migurski/circlejek/assignees{/user}",\r  "branches_url": "https://api.github.com/repos/migurski/circlejek/branches{/branch}",\r  "tags_url": "https://api.github.com/repos/migurski/circlejek/tags",\r  "blobs_url": "https://api.github.com/repos/migurski/circlejek/git/blobs{/sha}",\r  "git_tags_url": "https://api.github.com/repos/migurski/circlejek/git/tags{/sha}",\r  "git_refs_url": "https://api.github.com/repos/migurski/circlejek/git/refs{/sha}",\r  "trees_url": "https://api.github.com/repos/migurski/circlejek/git/trees{/sha}",\r  "statuses_url": "https://api.github.com/repos/migurski/circlejek/statuses/{sha}",\r  "languages_url": "https://api.github.com/repos/migurski/circlejek/languages",\r  "stargazers_url": "https://api.github.com/repos/migurski/circlejek/stargazers",\r  "contributors_url": "https://api.github.com/repos/migurski/circlejek/contributors",\r  "subscribers_url": "https://api.github.com/repos/migurski/circlejek/subscribers",\r  "subscription_url": "https://api.github.com/repos/migurski/circlejek/subscription",\r  "commits_url": "https://api.github.com/repos/migurski/circlejek/commits{/sha}",\r  "git_commits_url": "https://api.github.com/repos/migurski/circlejek/git/commits{/sha}",\r  "comments_url": "https://api.github.com/repos/migurski/circlejek/comments{/number}",\r  "issue_comment_url": "https://api.github.com/repos/migurski/circlejek/issues/comments{/number}",\r  "contents_url": "https://api.github.com/repos/migurski/circlejek/contents/{+path}",\r  "compare_url": "https://api.github.com/repos/migurski/circlejek/compare/{base}...{head}",\r  "merges_url": "https://api.github.com/repos/migurski/circlejek/merges",\r  "archive_url": "https://api.github.com/repos/migurski/circlejek/{archive_format}{/ref}",\r  "downloads_url": "https://api.github.com/repos/migurski/circlejek/downloads",\r  "issues_url": "https://api.github.com/repos/migurski/circlejek/issues{/number}",\r  "pulls_url": "https://api.github.com/repos/migurski/circlejek/pulls{/number}",\r  "milestones_url": "https://api.github.com/repos/migurski/circlejek/milestones{/number}",\r  "notifications_url": "https://api.github.com/repos/migurski/circlejek/notifications{?since,all,participating}",\r  "labels_url": "https://api.github.com/repos/migurski/circlejek/labels{/name}",\r  "releases_url": "https://api.github.com/repos/migurski/circlejek/releases{/id}",\r  "created_at": "2015-12-30T20:58:26Z",\r  "updated_at": "2015-12-30T21:03:10Z",\r  "pushed_at": "2016-01-06T05:36:42Z",\r  "git_url": "git://github.com/migurski/circlejek.git",\r  "ssh_url": "git@github.com:migurski/circlejek.git",\r  "clone_url": "https://github.com/migurski/circlejek.git",\r  "svn_url": "https://github.com/migurski/circlejek",\r  "homepage": null,\r  "size": 6,\r  "stargazers_count": 0,\r  "watchers_count": 0,\r  "language": "Ruby",\r  "has_issues": true,\r  "has_downloads": true,\r  "has_wiki": true,\r  "has_pages": false,\r  "forks_count": 0,\r  "mirror_url": null,\r  "open_issues_count": 0,\r  "forks": 0,\r  "open_issues": 0,\r  "watchers": 0,\r  "default_branch": "master",\r  "permissions": {\r    "admin": true,\r    "push": true,\r    "pull": true\r  },\r  "network_count": 0,\r  "subscribers_count": 1\r}'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/no-repo'):
            data = u'''{\r  "message": "Not Found",\r  "documentation_url": "https://developer.github.com/v3"\r}'''
            return response(404, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/no-repo/statuses/master'):
            data = u'''{\r  "message": "Not Found",\r  "documentation_url": "https://developer.github.com/v3"\r}'''
            return response(404, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/statuses/4872caf32'):
            data = u'''[\r    {\r        "context": "ci/circleci",\r        "created_at": "2016-01-06T05:36:44Z",\r        "creator": {\r            "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r            "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r            "followers_url": "https://api.github.com/users/migurski/followers",\r            "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r            "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r            "gravatar_id": "",\r            "html_url": "https://github.com/migurski",\r            "id": 58730,\r            "login": "migurski",\r            "organizations_url": "https://api.github.com/users/migurski/orgs",\r            "received_events_url": "https://api.github.com/users/migurski/received_events",\r            "repos_url": "https://api.github.com/users/migurski/repos",\r            "site_admin": false,\r            "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r            "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r            "type": "User",\r            "url": "https://api.github.com/users/migurski"\r        },\r        "description": "CircleCI is running your tests",\r        "id": 406914381,\r        "state": "pending",\r        "target_url": "https://circleci.com/gh/migurski/circlejek/21",\r        "updated_at": "2016-01-06T05:36:44Z",\r        "url": "https://api.github.com/repos/migurski/circlejek/statuses/4872caf3203972ebbe13e3863e4c47c407ee4bbf"\r    },\r    {\r        "context": "ci/circleci",\r        "created_at": "2016-01-06T05:36:43Z",\r        "creator": {\r            "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r            "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r            "followers_url": "https://api.github.com/users/migurski/followers",\r            "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r            "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r            "gravatar_id": "",\r            "html_url": "https://github.com/migurski",\r            "id": 58730,\r            "login": "migurski",\r            "organizations_url": "https://api.github.com/users/migurski/orgs",\r            "received_events_url": "https://api.github.com/users/migurski/received_events",\r            "repos_url": "https://api.github.com/users/migurski/repos",\r            "site_admin": false,\r            "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r            "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r            "type": "User",\r            "url": "https://api.github.com/users/migurski"\r        },\r        "description": "Your tests are queued behind your running builds",\r        "id": 406914377,\r        "state": "pending",\r        "target_url": "https://circleci.com/gh/migurski/circlejek/21",\r        "updated_at": "2016-01-06T05:36:43Z",\r        "url": "https://api.github.com/repos/migurski/circlejek/statuses/4872caf3203972ebbe13e3863e4c47c407ee4bbf"\r    }\r]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/statuses/d6f1c445e'):
            data = u'''[\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/d6f1c445e6525fa34cbd172d86caeb0e80ba92a6",\r    "id": 403269845,\r    "state": "error",\r    "description": "Your CircleCI tests were canceled",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/7",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:30:43Z",\r    "updated_at": "2015-12-30T21:30:43Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/d6f1c445e6525fa34cbd172d86caeb0e80ba92a6",\r    "id": 403269837,\r    "state": "error",\r    "description": "Your CircleCI tests were canceled",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/7",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:30:43Z",\r    "updated_at": "2015-12-30T21:30:43Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/d6f1c445e6525fa34cbd172d86caeb0e80ba92a6",\r    "id": 403264982,\r    "state": "pending",\r    "description": "CircleCI is running your tests",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/7",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:23:08Z",\r    "updated_at": "2015-12-30T21:23:08Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/d6f1c445e6525fa34cbd172d86caeb0e80ba92a6",\r    "id": 403264972,\r    "state": "pending",\r    "description": "Your tests have been scheduled to run again",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/7",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:23:07Z",\r    "updated_at": "2015-12-30T21:23:07Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/d6f1c445e6525fa34cbd172d86caeb0e80ba92a6",\r    "id": 403264971,\r    "state": "pending",\r    "description": "Your tests have been scheduled to run again",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/7",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:23:07Z",\r    "updated_at": "2015-12-30T21:23:07Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/d6f1c445e6525fa34cbd172d86caeb0e80ba92a6",\r    "id": 403264783,\r    "state": "failure",\r    "description": "Your tests failed on CircleCI",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/6",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:22:52Z",\r    "updated_at": "2015-12-30T21:22:52Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/d6f1c445e6525fa34cbd172d86caeb0e80ba92a6",\r    "id": 403263934,\r    "state": "pending",\r    "description": "CircleCI is running your tests",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/6",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:21:44Z",\r    "updated_at": "2015-12-30T21:21:44Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  },\r  {\r    "url": "https://api.github.com/repos/migurski/circlejek/statuses/d6f1c445e6525fa34cbd172d86caeb0e80ba92a6",\r    "id": 403263911,\r    "state": "pending",\r    "description": "Your tests are queued behind your running builds",\r    "target_url": "https://circleci.com/gh/migurski/circlejek/6",\r    "context": "ci/circleci",\r    "created_at": "2015-12-30T21:21:43Z",\r    "updated_at": "2015-12-30T21:21:43Z",\r    "creator": {\r      "login": "migurski",\r      "id": 58730,\r      "avatar_url": "https://avatars.githubusercontent.com/u/58730?v=3",\r      "gravatar_id": "",\r      "url": "https://api.github.com/users/migurski",\r      "html_url": "https://github.com/migurski",\r      "followers_url": "https://api.github.com/users/migurski/followers",\r      "following_url": "https://api.github.com/users/migurski/following{/other_user}",\r      "gists_url": "https://api.github.com/users/migurski/gists{/gist_id}",\r      "starred_url": "https://api.github.com/users/migurski/starred{/owner}{/repo}",\r      "subscriptions_url": "https://api.github.com/users/migurski/subscriptions",\r      "organizations_url": "https://api.github.com/users/migurski/orgs",\r      "repos_url": "https://api.github.com/users/migurski/repos",\r      "events_url": "https://api.github.com/users/migurski/events{/privacy}",\r      "received_events_url": "https://api.github.com/users/migurski/received_events",\r      "type": "User",\r      "site_admin": false\r    }\r  }\r]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        if MHPQ == ('GET', 'circleci.com', '/api/v1/project/migurski/circlejek/13/artifacts', 'circle-token=a17131792f4c4bcb97f2f66d9c58258a0ee0e621'):
            data = u'''[{"path":"/tmp/circle-artifacts.6VLZE7m/goodbye.html","pretty_path":"$CIRCLE_ARTIFACTS/goodbye.html","node_index":0,"url":"https://circle-artifacts.com/gh/migurski/circlejek/13/artifacts/0/tmp/circle-artifacts.6VLZE7m/goodbye.html"},{"path":"/tmp/circle-artifacts.6VLZE7m/index.html","pretty_path":"$CIRCLE_ARTIFACTS/index.html","node_index":0,"url":"https://circle-artifacts.com/gh/migurski/circlejek/13/artifacts/0/tmp/circle-artifacts.6VLZE7m/index.html"}]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        raise Exception(MHPQ)
    
    def test_authenticated_user(self):
        with HTTMock(self.response_content):
            self.assertFalse(is_authenticated(Getter(('invalid', 'x-oauth-basic')).get))
            self.assertTrue(is_authenticated(Getter(('valid', 'x-oauth-basic')).get))
    
    def test_existing_repo(self):
        with HTTMock(self.response_content):
            self.assertFalse(repo_exists('migurski', 'no-repo', self.GET))
            self.assertTrue(repo_exists('migurski', 'circlejek', self.GET))
    
    def test_split_branch_path(self):
        with HTTMock(self.response_content):
            self.assertEqual(split_branch_path('mapzen', 'blog', 'drew/dc-transit-events-2016/blog/mapzen-in-dc', self.GET), ('drew/dc-transit-events-2016', 'blog/mapzen-in-dc'))
            self.assertEqual(split_branch_path('mapzen', 'blog', 'drew/dc-transit-events-2016/blog/', self.GET), ('drew/dc-transit-events-2016', 'blog/'))
            self.assertEqual(split_branch_path('mapzen', 'blog', 'drew/dc-transit-events-2016/', self.GET), ('drew/dc-transit-events-2016', ''))
            self.assertEqual(split_branch_path('mapzen', 'blog', 'drew/dc-transit-events-2016', self.GET), ('drew/dc-transit-events-2016', ''))
            self.assertEqual(split_branch_path('mapzen', 'blog', 'drew', self.GET), (None, 'drew'))
            self.assertEqual(split_branch_path('mapzen', 'blog', '8d0c610/etc.', self.GET), ('8d0c610', 'etc.'))
    
    def test_find_base_path(self):
        with HTTMock(self.response_content):
            self.assertEqual(find_base_path('migurski', 'circlejek', 'master', self.GET), '$CIRCLE_ARTIFACTS')
            self.assertEqual(find_base_path('migurski', 'circlejek', 'tinker-with-config', self.GET), '/home/ubuntu/circlejek/_site')
    
    def test_existing_master(self):
        with HTTMock(self.response_content):
            artifacts = get_circle_artifacts('migurski', 'circlejek', 'master', self.GET)
            self.assertIn('index.html', artifacts)
    
    def test_untested_branch(self):
        with HTTMock(self.response_content):
            with self.assertRaises(RuntimeError) as r:
                get_circle_artifacts('migurski', 'circlejek', 'untested', self.GET)
            self.assertEqual(r.exception.message, ERR_NO_REF_STATUS)
    
    def test_nonexistent_repository(self):
        with HTTMock(self.response_content):
            with self.assertRaises(RuntimeError) as r:
                get_circle_artifacts('migurski', 'no-repo', 'master', self.GET)
            self.assertEqual(r.exception.message, ERR_NO_REPOSITORY)
    
    def test_unfinished_test(self):
        with HTTMock(self.response_content):
            with self.assertRaises(RuntimeError) as r:
                get_circle_artifacts('migurski', 'circlejek', '4872caf32', self.GET)
            self.assertEqual(r.exception.message, ERR_TESTS_PENDING)
    
    def test_failed_test(self):
        with HTTMock(self.response_content):
            with self.assertRaises(RuntimeError) as r:
                get_circle_artifacts('migurski', 'circlejek', 'd6f1c445e', self.GET)
            self.assertEqual(r.exception.message, ERR_TESTS_FAILED)
    
    def test_select_path(self):
        self.assertEqual(select_path(tuple(), ''), 'index.html')
        self.assertEqual(select_path(tuple(), 'foo'), 'foo/index.html')
        self.assertEqual(select_path(('foo', ), 'foo'), 'foo')
