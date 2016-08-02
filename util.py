from __future__ import division
from fcntl import flock, LOCK_EX, LOCK_UN
from contextlib import contextmanager
from traceback import format_exc
from datetime import timedelta
from logging import getLogger
from functools import wraps
from urllib import urlencode
from urlparse import urlparse, urlunparse, parse_qsl

from flask import make_response, Response, render_template
from requests.exceptions import RequestException, ReadTimeout

jlogger = getLogger('precog')

ERR_NO_REPOSITORY = 'Missing repository'
ERR_TESTS_PENDING = 'Test in progress'
ERR_TESTS_FAILED = 'Test failed'
ERR_NO_REF_STATUS = 'Missing statuses for ref'

err_codes = dict(NO_REPOSITORY=ERR_NO_REPOSITORY, TESTS_PENDING=ERR_TESTS_PENDING,
                 TESTS_FAILED=ERR_TESTS_FAILED, NO_REF_STATUS=ERR_NO_REF_STATUS)

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

def errors_logged(route_function):
    '''
    '''
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        try:
            result = route_function(*args, **kwargs)
        except RequestException as error:
            jlogger.error(format_exc())
            jlogger.error('Failed to {} {}'.format(error.request.method, error.request.url))
            hostname = urlparse(error.request.url).netloc
            message = 'An upstream connection to {} failed'.format(hostname)
            kwargs = dict(codes=err_codes, error=Exception(message))
            return make_response(render_template('error-runtime.html', **kwargs), 500)
        except Exception as e:
            jlogger.error(format_exc())
            raise
            return Response('Nope.', headers={'Content-Type': 'text/plain'}, status=500)
        else:
            return result
    
    return wrapper

def nice_relative_time(delta):
    '''
    >>> nice_relative_time(timedelta(days=2))
    '2 days'
    >>> nice_relative_time(timedelta(hours=37))
    '2 days'
    >>> nice_relative_time(timedelta(hours=36))
    '36 hours'
    >>> nice_relative_time(timedelta(days=1))
    '24 hours'

    >>> nice_relative_time(timedelta(hours=2))
    '2 hours'
    >>> nice_relative_time(timedelta(minutes=91))
    '2 hours'
    >>> nice_relative_time(timedelta(minutes=90))
    '90 minutes'
    >>> nice_relative_time(timedelta(hours=1))
    '60 minutes'

    >>> nice_relative_time(timedelta(minutes=2))
    '2 minutes'
    >>> nice_relative_time(timedelta(seconds=91))
    '2 minutes'
    >>> nice_relative_time(timedelta(seconds=90))
    '90 seconds'
    >>> nice_relative_time(timedelta(minutes=1))
    '60 seconds'
    '''
    seconds = delta.seconds + delta.days * 86400
    
    if seconds > 1.5 * 86400:
        return '{:.0f} days'.format(seconds / 86400)
    
    if seconds > 1.5 * 3600:
        return '{:.0f} hours'.format(seconds / 3600)
    
    if seconds > 1.5 * 60:
        return '{:.0f} minutes'.format(seconds / 60)
    
    return '{:.0f} seconds'.format(seconds)

def parse_webhook_config(*strings):
    '''
    >>> parse_webhook_config('')
    {}

    >>> parse_webhook_config()
    {}

    >>> parse_webhook_config('mapzen/blog:abc:def') \
        == {'mapzen/blog': dict(secret='abc', token='def')}
    True

    >>> parse_webhook_config('mapzen/blog:abc:def:ghi') \
        == {'mapzen/blog': dict(secret='abc', token='def:ghi')}
    True

    >>> parse_webhook_config('mapzen/blog:abc:def mapzen/style:ghi:jkl') \
        == {'mapzen/blog': dict(secret='abc', token='def'), \
            'mapzen/style': dict(secret='ghi', token='jkl')}
    True

    >>> parse_webhook_config('mapzen/blog:abc:def', 'mapzen/style:ghi:jkl') \
        == {'mapzen/blog': dict(secret='abc', token='def'), \
            'mapzen/style': dict(secret='ghi', token='jkl')}
    True

    >>> parse_webhook_config('mapzen/blog:abc:def', 'mapzen/style:ghi:jkl', 'mapzen/blog:mno:pqr') \
        == {'mapzen/blog': dict(secret='mno', token='pqr'), \
            'mapzen/style': dict(secret='ghi', token='jkl')}
    True
    '''
    sites = dict()
    for site in ' '.join(strings).split():
        name, secret, token = site.split(':', 2)
        sites[name] = dict(secret=secret, token=token)
    
    return sites

def extend_querystring(url, new_args):
    '''
    >>> extend_querystring('http://example.com/path', dict())
    'http://example.com/path'

    >>> extend_querystring('http://example.com/path', dict(foo='bar'))
    'http://example.com/path?foo=bar'

    >>> extend_querystring('http://example.com/path?foo=bar', dict())
    'http://example.com/path?foo=bar'

    >>> extend_querystring('http://example.com/path?foo=bar', dict(foo='new'))
    'http://example.com/path?foo=new'

    >>> 'foo=bar' in extend_querystring('http://example.com/path?foo=bar', dict(doo='new'))
    True

    >>> 'doo=new' in extend_querystring('http://example.com/path?foo=bar', dict(doo='new'))
    True
    '''
    scheme, host, path, params, query, frag = urlparse(url)
    query_dict = dict(parse_qsl(query))
    query_dict.update(new_args)
    
    return urlunparse((scheme, host, path, params, urlencode(query_dict), frag))

if __name__ == '__main__':
    import doctest
    doctest.testmod()
