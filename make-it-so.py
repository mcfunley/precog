from logging import DEBUG, INFO, getLogger, FileHandler, StreamHandler, Formatter
from os.path import join, isdir, isfile
from traceback import format_exc
from urllib import urlencode
from functools import wraps
from urlparse import urlparse
from os import environ
from uuid import uuid4
from time import time

from flask import Flask, Response, redirect, request, make_response, render_template, session
import requests

from requests import post
from requests_oauthlib import OAuth2Session
from git import Getter, is_authenticated, repo_exists, split_branch_path, get_circle_artifacts, select_path, _LONGTIME, get_branch_names
from href import needs_redirect, get_redirect
from util import errors_logged

from git import github_client_id, github_client_secret
flask_secret_key = 'poop'

app = Flask(__name__)
app.secret_key = flask_secret_key

@app.before_first_request
def adjust_log_level():
    getLogger('precog').setLevel(DEBUG if app.debug else INFO)

def make_redirect(slash_count):
    ''' Return a flask.redirect for the current flask.request.
    '''
    referer_url = request.headers.get('Referer')

    other = redirect(get_redirect(request.path, referer_url, slash_count), 302)
    other.headers['Cache-Control'] = 'no-store private'
    other.headers['Vary'] = 'Referer'

    return other

def handle_redirects(route_function):
    '''
    '''
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        GET = Getter((get_token().get('access_token'), 'x-oauth-basic')).get
        
        # Look for a missing trailing slash at the repository root.
        split_req = request.path.lstrip('/').split('/', 2)
        
        if len(split_req) == 3 and split_req[2] != '':
            # There are three full components in the path: owner, repo, and ref.
            req_owner, req_repo, req_ref_path = split_req
            req_ref, req_path = split_branch_path(req_owner, req_repo, req_ref_path, GET)
            
            if req_path == '' and not req_ref_path.endswith('/'):
                # Missing a trailing slash at the root of the repository.
                return redirect('{}/'.format(request.path), 302)

        # See if there's a referer at all.
        referer_url = request.headers.get('Referer')
        
        if not referer_url:
            # No referer, no redirect.
            return route_function(*args, **kwargs)

        # See if the referer path is long enough to suggest a redirect.
        referer_path = urlparse(referer_url).path
        split_path = referer_path.lstrip('/').split('/', 2)
        
        if len(split_path) != 3:
            # Not long enough.
            return route_function(*args, **kwargs)
        
        # Talk to Github about the path and find a ref name.
        path_owner, path_repo, path_ref = split_path

        if not repo_exists(path_owner, path_repo, GET):
            # No repo by this name, no redirect.
            return route_function(*args, **kwargs)
        
        ref, _ = split_branch_path(path_owner, path_repo, path_ref, GET)
        
        if ref is None:
            # No ref identified, no redirect.
            return route_function(*args, **kwargs)
        
        # Usually 3, but maybe more?
        slash_count = 2 + len(ref.split('/'))
        
        # See if a redirect is necessary.
        if needs_redirect(request.host, request.path, referer_url, slash_count):
            return make_redirect(slash_count)
        
        # Otherwise, proceed as normal.
        return route_function(*args, **kwargs)
    
    return wrapper

def get_token():
    ''' Get OAuth token from flask.session, or a fake one guaranteed to fail.
    '''
    token = dict(token_type='bearer', access_token='<fake token, will fail>')
    token.update(session.get('token', {}))
    
    return token

def make_401_response():
    ''' Create an HTTP 401 Not Authorized response to trigger Github OAuth.
    
        Start by redirecting the user to Github OAuth authorization page:
        http://developer.github.com/v3/oauth/#redirect-users-to-request-github-access
    '''
    state_id = str(uuid4())
    states = session.get('states', {})
    states[state_id] = dict(redirect=request.url, created=time())
    session['states'] = states
    
    data = dict(scope='user,repo', client_id=github_client_id, state=state_id)
    
    auth = redirect('https://github.com/login/oauth/authorize?' + urlencode(data), 302)
    auth.headers['Cache-Control'] = 'no-store private'
    auth.headers['Vary'] = 'Referer'

    return auth

def make_404_response(template, vars):
    '''
    '''
    return make_response(render_template(template, **vars), 404)

def make_500_response(error, traceback):
    '''
    '''
    try:
        message = unicode(error)
    except UnicodeDecodeError:
        message = str(error).decode('latin-1')
    
    vars = dict(error=message, traceback=traceback)
    
    return make_response(render_template('error-runtime.html', **vars), 500)

@app.route('/')
@errors_logged
@handle_redirects
def hello_world():
    id = session.get('id', None)
    
    script = '''
    javascript:(
        function ()
        {
            document.getElementsByTagName('head')[0].appendChild(document.createElement('script')).src='http://host:port/bookmarklet.js';
        }()
    );
    '''
    
    script = script.replace('http', request.scheme)
    script = script.replace('host:port', request.host)
    script = script.replace(' ', '').replace('\n', '')
    
    return render_template('index.html', id=id, script=script, request=request)

@app.route('/.well-known/status')
@errors_logged
@handle_redirects
def wellknown_status():
    status = '''
    {
      "status": "ok",
      "updated": %d,
      "dependencies": [ ],
      "resources": { }
    }
    ''' % time()
    
    resp = make_response(status, 200)
    resp.headers['Content-Type'] = 'application/json'

    return resp

@app.route('/bookmarklet.js')
@errors_logged
@handle_redirects
def bookmarklet_script():
    js = open('scripts/bookmarklet.js').read()

    script = make_response(js.replace('host:port', request.host), 200)
    script.headers['Content-Type'] = 'text/javascript'
    script.headers['Cache-Control'] = 'no-store private'

    return script

@app.route('/oauth/callback')
@errors_logged
def get_oauth_callback():
    ''' Handle Github's OAuth callback after a user authorizes.
    
        http://developer.github.com/v3/oauth/#github-redirects-back-to-your-site
    '''
    if 'error' in request.args:
        return render_template('error-oauth.html', reason="you didn't authorize access to your account.")
    
    try:
        code, state_id = request.args['code'], request.args['state']
    except:
        return render_template('error-oauth.html', reason='missing code or state in callback.')
    
    try:
        state = session['states'].pop(state_id)
    except:
        return render_template('error-oauth.html', reason='state "%s" not found?' % state_id)
    
    #
    # Exchange the temporary code for an access token:
    # http://developer.github.com/v3/oauth/#parameters-1
    #
    data = dict(client_id=github_client_id, code=code, client_secret=github_client_secret)
    resp = post('https://github.com/login/oauth/access_token', urlencode(data),
                headers={'Accept': 'application/json'})
    auth = resp.json()
    
    if 'error' in auth:
        return render_template('error-oauth.html', reason='Github said "%(error)s".' % auth)
    
    elif 'access_token' not in auth:
        return render_template('error-oauth.html', reason="missing `access_token`.")
    
    session['token'] = auth
    
    #
    # Figure out who's here.
    #
    url = 'https://api.github.com/user'
    id = OAuth2Session(github_client_id, token=session['token']).get(url).json()
    id = dict(login=id['login'], avatar_url=id['avatar_url'], html_url=id['html_url'])
    session['id'] = id
    
    other = redirect(state['redirect'], 302)
    other.headers['Cache-Control'] = 'no-store private'
    other.headers['Vary'] = 'Referer'

    return other

@app.route('/logout', methods=['POST'])
@errors_logged
def logout():
    '''
    '''
    if 'id' in session:
        session.pop('id')

    if 'token' in session:
        session.pop('token')
    
    return redirect('/', 302)

@app.route('/<account>/<repo>')
@errors_logged
@handle_redirects
def repo_only(account, repo):
    ''' Add a slash.
    '''
    return redirect('/%s/%s/' % (account, repo), 302)

@app.route('/<account>/<repo>/')
@errors_logged
@handle_redirects
def repo_only_slash(account, repo):
    ''' Show a list of branch names.
    '''
    access_token = get_token().get('access_token')
    GET = Getter((access_token, 'x-oauth-basic')).get
    template_args = dict(account=account, repo=repo)
    branch_names = sorted(get_branch_names(account, repo, GET))
    
    return render_template('branches.html', branch_names=branch_names, **template_args)

@app.route('/<account>/<repo>/<ref>')
@errors_logged
@handle_redirects
def repo_ref(account, repo, ref):
    ''' Redirect to add trailing slash.
    '''
    return redirect('/%s/%s/%s/' % (account, repo, ref), 302)

@app.route('/<account>/<repo>/<path:ref_path>')
@errors_logged
@handle_redirects
def repo_ref_path(account, repo, ref_path):
    access_token = get_token().get('access_token')
    GET = Getter((access_token, 'x-oauth-basic')).get
    template_args = dict(account=account, repo=repo)
    
    if access_token is None or not is_authenticated(GET):
        return make_401_response()
    elif not repo_exists(account, repo, GET):
        return make_404_response('no-such-repo.html', template_args)
    
    ref, path = split_branch_path(account, repo, ref_path, GET)
    
    if ref is None:
        return make_404_response('no-such-ref.html', dict(ref=ref_path, **template_args))
    
    try:
        artifacts = get_circle_artifacts(account, repo, ref, GET)
        artifact_url = artifacts.get(select_path(artifacts, path))
    except RuntimeError as err:
        return make_response(render_template('error-runtime.html', error=err), 400)
    
    if artifact_url is None:
        return make_404_response('error-404.html', dict(ref=ref, path=path, **template_args))

    try:
        artifact_resp = GET(artifact_url, _LONGTIME)
        if artifact_resp.status_code != 200:
            raise IOError('Bad response from CircleCI: HTTP {}'.format(artifact_resp.status_code))
        content = artifact_resp.content
        mimetype = artifact_resp.headers.get('Content-Type', '')
    except IOError as err:
        return make_response(render_template('error-runtime.html', error=err), 500)
    
    return Response(content, headers={'Content-Type': mimetype, 'Cache-Control': 'no-store private'})

@app.route('/<path:path>')
@errors_logged
@handle_redirects
def all_other_paths(path):
    '''
    '''
    return 'Shrug.'

if environ.get('app-logfile', None):
    handler = FileHandler(environ['app-logfile'])
    handler.setFormatter(Formatter('%(process)05s %(asctime)s %(levelname)06s: %(message)s'))

else:
    handler = StreamHandler()
    handler.setFormatter(Formatter('%(process)05s %(levelname)06s: %(message)s'))

getLogger('precog').addHandler(handler)

if __name__ == '__main__':
    app.run('localhost', debug=True)
