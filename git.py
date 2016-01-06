from os.path import join, exists, dirname
from os import getcwd, mkdir, environ
from logging import getLogger

from requests_oauthlib import OAuth2Session
import requests

github_client_id = environ.get('GITHUB_CLIENT_ID') or r'e62e0d541bb6d0125b62'
github_client_secret = environ.get('GITHUB_CLIENT_SECRET') or r'1f488407e92a59beb897814e9240b5a06a2020e3'

jlogger = getLogger('jekit')

ERR_NO_REPOSITORY = 'Missing repository'
ERR_PENDING_MESSAGE = 'Test in progress'
ERR_NO_REF_STATUS = 'Missing statuses for ref'

class PrivateRepoException (Exception): pass

class MissingRepoException (Exception): pass

class MissingRefException (Exception): pass

def is_authenticated(access_token):
    '''
    '''
    github_auth = access_token, 'x-oauth-basic'
    user_resp = requests.get('https://api.github.com/user', auth=github_auth)
    
    return bool(user_resp.status_code == 200)

def repo_exists(owner, repo, access_token):
    '''
    '''
    github_auth = access_token, 'x-oauth-basic'
    repo_url = 'https://api.github.com/repos/{owner}/{repo}'.format(**locals())
    repo_resp = requests.get(repo_url, auth=github_auth)
    
    return bool(repo_resp.status_code == 200)

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

        if MHP == ('GET', 'api.github.com', '/repos/migurski/circlejek/statuses/no-branch'):
            data = u'''[\r\r]'''
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

        if MHPQ == ('GET', 'circleci.com', '/api/v1/project/migurski/circlejek/13/artifacts', 'circle-token=a17131792f4c4bcb97f2f66d9c58258a0ee0e621'):
            data = u'''[{"path":"/tmp/circle-artifacts.6VLZE7m/goodbye.html","pretty_path":"$CIRCLE_ARTIFACTS/goodbye.html","node_index":0,"url":"https://circle-artifacts.com/gh/migurski/circlejek/13/artifacts/0/tmp/circle-artifacts.6VLZE7m/goodbye.html"},{"path":"/tmp/circle-artifacts.6VLZE7m/index.html","pretty_path":"$CIRCLE_ARTIFACTS/index.html","node_index":0,"url":"https://circle-artifacts.com/gh/migurski/circlejek/13/artifacts/0/tmp/circle-artifacts.6VLZE7m/index.html"}]'''
            return response(200, data.encode('utf8'), headers=response_headers)

        raise Exception(MHPQ)
    
    def test_authenticated_user(self):
        with HTTMock(self.response_content):
            self.assertFalse(is_authenticated('invalid'))
            self.assertTrue(is_authenticated('valid'))
    
    def test_existing_repo(self):
        with HTTMock(self.response_content):
            self.assertFalse(repo_exists('migurski', 'no-repo', {}))
            self.assertTrue(repo_exists('migurski', 'circlejek', {}))
    
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
