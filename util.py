from __future__ import division
from fcntl import flock, LOCK_EX, LOCK_UN
from contextlib import contextmanager
from traceback import format_exc
from datetime import timedelta
from logging import getLogger
from functools import wraps

from flask import Response

jlogger = getLogger('precog')

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
        except Exception, e:
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

if __name__ == '__main__':
    import doctest
    doctest.testmod()
