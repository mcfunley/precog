from os import utime, stat, listdir
from fcntl import flock, LOCK_EX, LOCK_UN
from contextlib import contextmanager
from subprocess import Popen, PIPE
from mimetypes import guess_type
from traceback import format_exc
from logging import getLogger
from functools import wraps
from os.path import join
from time import time

from flask import Response

jlogger = getLogger('jekit')

@contextmanager
def locked_file(path):
    ''' Create a file, lock it, then unlock it. Use as a context manager.
    
        Yields nothing.
    '''
    jlogger.debug('Locking ' + path)
    
    try:
        file = open(path, 'a')
        flock(file, LOCK_EX)
        
        yield

    finally:
        jlogger.debug('Unlocking ' + path)
        flock(file, LOCK_UN)

def is_fresh(path):
    ''' Return true if path is younger than 10 seconds.
    '''
    return stat(path).st_mtime > time() - 10

def touch(path):
    ''' Touch the path to bring its modified timestamp to now.
    '''
    jlogger.debug('Touching ' + path)
    utime(path, None)

def run_cmd(args, cwd=None):
    ''' Runs a single command in a new process, returns its stdout.
    '''
    command = Popen(args, stdout=PIPE, stderr=PIPE, cwd=cwd)
    command.wait()
    
    if command.returncode != 0:
        raise RuntimeError(command.stderr.read())
    
    return command.stdout.read()

def get_file_response(path):
    ''' Return a flask Response for a simple file.
    '''
    mimetype, encoding = guess_type(path)
    
    with open(path) as file:
        return Response(file.read(), headers={'Content-Type': mimetype, 'Cache-Control': 'no-store private'})

def get_directory_response(path):
    ''' Return a flask Response for a directory listing.
    '''
    names = sorted(listdir(path))

    if 'index.html' in names:
        return get_file_response(join(path, 'index.html'))
    
    items = ['<li><a href="%s">%s</a></li>' % (n, n) for n in names]
    html = '<ul>' + ''.join(items) + '</ul>'
    
    return Response(html, headers={'Content-Type': 'text/html', 'Cache-Control': 'no-store private'})

def get_circle_artifacts(owner, repo, ref, github_token):
    '''
    '''
    import requests, urlparse, os.path
    
    circle_token = 'a17131792f4c4bcb97f2f66d9c58258a0ee0e621'

    github_auth = github_token.get('access_token'), 'x-oauth-basic'
    status_url = 'https://api.github.com/repos/{owner}/{repo}/statuses/{ref}'.format(**locals())
    status = requests.get(status_url, auth=github_auth).json()[0]

    circle_url = status['target_url'] if (status['state'] == 'success') else None
    circle_build = os.path.relpath(urlparse.urlparse(circle_url).path, '/gh/')

    artifacts_url = 'https://circleci.com/api/v1/project/{}/artifacts?circle-token={}'.format(circle_build, circle_token)
    artifacts = {os.path.relpath(a['pretty_path'], '$CIRCLE_ARTIFACTS'): '{}?circle-token={}'.format(a['url'], circle_token)
                 for a in requests.get(artifacts_url, headers=dict(Accept='application/json')).json()}
    
    return artifacts

def errors_logged(route_function):
    '''
    '''
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        try:
            result = route_function(*args, **kwargs)
        except Exception, e:
            jlogger.error(format_exc())
            return Response('Nope.', headers={'Content-Type': 'text/plain'}, status=500)
        else:
            return result
    
    return wrapper