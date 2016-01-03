from os.path import join, exists, dirname
from os import getcwd, mkdir, environ
from logging import getLogger

from requests_oauthlib import OAuth2Session
from requests import get

github_client_id = environ.get('GITHUB_CLIENT_ID') or r'e62e0d541bb6d0125b62'
github_client_secret = environ.get('GITHUB_CLIENT_SECRET') or r'1f488407e92a59beb897814e9240b5a06a2020e3'

jlogger = getLogger('jekit')

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
    if status_resp.status_code != 200: raise PrivateRepoException()
    status = status_resp.json()[0]

    circle_url = status['target_url'] if (status['state'] == 'success') else None
    circle_build = os.path.relpath(urlparse.urlparse(circle_url).path, '/gh/')

    artifacts_url = 'https://circleci.com/api/v1/project/{}/artifacts?circle-token={}'.format(circle_build, circle_token)
    artifacts = {os.path.relpath(a['pretty_path'], '$CIRCLE_ARTIFACTS'): '{}?circle-token={}'.format(a['url'], circle_token)
                 for a in requests.get(artifacts_url, headers=dict(Accept='application/json')).json()}
    
    return artifacts
