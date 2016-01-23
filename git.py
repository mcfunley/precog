from os.path import relpath, join
from urlparse import urlparse
from logging import getLogger
from datetime import datetime
from base64 import b64decode
from os import environ
from time import time

from dateutil.parser import parse, tz
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
_GITHUB_HEADS_URL = 'https://api.github.com/repos/{owner}/{repo}/git/refs/heads'
_GITHUB_STATUS_URL = 'https://api.github.com/repos/{owner}/{repo}/statuses/{ref}'
_CIRCLECI_ARTIFACTS_URL = 'https://circleci.com/api/v1/project/{build}/artifacts?circle-token={token}'

_LONGTIME = 3600
_defaultcache = {}

class Getter:
    ''' Wrapper for HTTP GET from requests.
    '''
    def __init__(self, github_auth, cache=_defaultcache):
        self.github_auth = github_auth
        self.responses = cache
    
    def _flush(self):
        ''' Flush past-deadline responses.
        '''
        for (k, (r, d)) in self.responses.items():
            if (time() > d):
                self.responses.pop(k)
    
    def get(self, url, lifespan=5):
        self._flush()
        
        host = urlparse(url).hostname
        auth = self.github_auth if (host == 'api.github.com') else None
        key = (url, auth)
        
        if key in self.responses:
            return self.responses[key][0]
        
        if host == 'api.github.com':
            getLogger('precog').warning('GET {}'.format(url))

        resp = requests.get(url, auth=auth, headers=dict(Accept='application/json'), timeout=2)
        
        self.responses[key] = (resp, time() + lifespan)
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
    blob_resp = GET(blob_url, _LONGTIME)
    blob_yaml = b64decode(blob_resp.json()['content'])
    circle_config = yaml.load(blob_yaml)
    
    paths = circle_config.get('general', {}).get('artifacts', [])
    
    if not paths:
        return '$CIRCLE_ARTIFACTS'
    
    return join('/home/ubuntu/{}/'.format(repo), paths[0])

class Branch:
    def __init__(self, name, age, link):
        self.name = name
        self.link = link
        self.age = age

def get_branch_info(owner, repo, GET):
    ''' Return list of Branch instances.
    '''
    heads_url = _GITHUB_HEADS_URL.format(owner=owner, repo=repo)
    heads_resp = GET(heads_url)
    heads_list = heads_resp.json()

    next_url = heads_resp.links.get('next', {}).get('url')
    
    # Iterate over links, if any.
    while next_url:
        next_resp = GET(next_url)
        next_url = next_resp.links.get('next', {}).get('url')
        heads_list.extend(next_resp.json())
    
    branch_info = list()
    
    for head in heads_list:
        if head['object']['type'] != 'commit':
            continue
        
        obj_name = relpath(head['ref'], 'refs/heads/')
        obj_resp = GET(head['object']['url'], _LONGTIME)

        obj_date = parse(obj_resp.json().get('committer', {}).get('date', {}))
        obj_age = datetime.now(tz=obj_date.tzinfo) - obj_date
        
        branch_info.append(Branch(obj_name, obj_age, None))
    
    return branch_info

def get_branch_names(owner, repo, GET):
    ''' Return list of branch heads.
    '''
    heads_url = _GITHUB_HEADS_URL.format(owner=owner, repo=repo)
    heads_resp = GET(heads_url)
    heads_list = heads_resp.json()

    next_url = heads_resp.links.get('next', {}).get('url')
    
    # Iterate over links, if any.
    while next_url:
        next_resp = GET(next_url)
        next_url = next_resp.links.get('next', {}).get('url')
        heads_list.extend(next_resp.json())
    
    branch_names = [relpath(head['ref'], 'refs/heads/') for head in heads_list]
    return branch_names

def get_circle_artifacts(owner, repo, ref, GET):
    ''' Return dictionary of CircleCI artifacts for a given Github repo ref.
    '''
    circle_token = environ.get('CIRCLECI_TOKEN') or 'a17131792f4c4bcb97f2f66d9c58258a0ee0e621'
    
    status_url = _GITHUB_STATUS_URL.format(owner=owner, repo=repo, ref=ref)
    status_resp = GET(status_url)
    
    if status_resp.status_code == 404:
        raise RuntimeError(ERR_NO_REPOSITORY, None)
    elif status_resp.status_code != 200:
        raise RuntimeError('some other HTTP status: {}'.format(status_resp.status_code))
    
    statuses = [s for s in status_resp.json() if s['context'] == 'ci/circleci']
    
    if len(statuses) == 0:
        raise RuntimeError(ERR_NO_REF_STATUS, None)

    status = statuses[0]
    
    if status['state'] == 'pending':
        raise RuntimeError(ERR_TESTS_PENDING, status['target_url'])
    elif status['state'] in ('error', 'failure'):
        raise RuntimeError(ERR_TESTS_FAILED, status['target_url'])
    elif status['state'] != 'success':
        raise RuntimeError('some other test outcome: {state}'.format(**status))

    circle_url = status['target_url'] if (status['state'] == 'success') else None
    circle_build = relpath(urlparse(circle_url).path, '/gh/')

    artifacts_base = find_base_path(owner, repo, ref, GET)
    artifacts_url = _CIRCLECI_ARTIFACTS_URL.format(build=circle_build, token=circle_token)
    artifacts = {relpath(a['pretty_path'], artifacts_base): '{}?circle-token={}'.format(a['url'], circle_token)
                 for a in GET(artifacts_url, _LONGTIME).json()}
    
    return artifacts

def select_path(paths, path):
    '''
    '''
    if path in paths:
        return path
    
    if path == '':
        return 'index.html'

    return '{}/index.html'.format(path.rstrip('/'))
