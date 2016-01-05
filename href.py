from urlparse import urlparse
from re import match
    
def get_redirect(req_path, ref_url, slash_count=3):
    '''
    >>> get_redirect('/style.css', 'http://preview.local/foo/bar/baz/')
    '/foo/bar/baz/style.css'

    >>> get_redirect('/style.css', 'http://preview.local/foo/bar/baz/quux.html')
    '/foo/bar/baz/style.css'

    >>> get_redirect('/quux/style.css', 'http://preview.local/foo/bar/baz/')
    '/foo/bar/baz/quux/style.css'

    >>> get_redirect('/style.css', 'http://preview.local/foo/bar/br/anch/', 4)
    '/foo/bar/br/anch/style.css'

    >>> get_redirect('/style.css', 'http://preview.local/foo/bar/br/anch/quux.html', 4)
    '/foo/bar/br/anch/style.css'

    >>> get_redirect('/quux/style.css', 'http://preview.local/foo/bar/br/anch/', 4)
    '/foo/bar/br/anch/quux/style.css'

    >>> get_redirect('/style.css', 'http://preview.local/foo/barbaz/', 2)
    '/foo/barbaz/style.css'

    >>> get_redirect('/style.css', 'http://preview.local/foo/barbaz/quux.html', 2)
    '/foo/barbaz/style.css'

    >>> get_redirect('/quux/style.css', 'http://preview.local/foo/barbaz/', 2)
    '/foo/barbaz/quux/style.css'
    '''
    _, _, ref_path, _, _, _ = urlparse(ref_url)
    pattern = r'(?P<preamble>' + (r'/[^/]+' * slash_count) + r')'
    ref_git_preamble_match = match(pattern, ref_path)
    
    return ref_git_preamble_match.group('preamble') + req_path

def needs_redirect(req_host, req_path, ref_url, slash_count=3):
    '''
    Don't redirect when the request and referer hosts don't match:
    >>> needs_redirect('preview.local', '/style.css', 'http://example.com/foo/bar/baz/')
    False

    Don't redirect when the referer doesn't appear to include a git path.
    >>> needs_redirect('preview.local', '/style.css', 'http://preview.local/about/')
    False

    Don't redirect when the referer doesn't appear to include a git path.
    >>> needs_redirect('preview.local', '/style.css', 'http://preview.local/about/', 2)
    False

    Don't redirect when the referer doesn't appear to include a git path.
    >>> needs_redirect('preview.local', '/style.css', 'http://preview.local/foo/bar/', 3)
    False

    Don't redirect when the referer doesn't appear to include a git path.
    >>> needs_redirect('preview.local', '/style.css', 'http://preview.local/foo/bar/baz/', 4)
    False

    Don't redirect when the request path already includes the git preamble.
    >>> needs_redirect('preview.local', '/foo/bar/baz/style.css', 'http://preview.local/foo/bar/baz/')
    False

    Don't redirect when the request path already includes the git preamble.
    >>> needs_redirect('preview.local', '/foo/bar/br/anch/style.css', 'http://preview.local/foo/bar/br/anch/', 4)
    False

    Don't redirect when the request path already includes the git preamble.
    >>> needs_redirect('preview.local', '/foo/barbaz/style.css', 'http://preview.local/foo/barbaz/', 2)
    False

    >>> needs_redirect('preview.local', '/', 'http://preview.local/foo/bar/baz/')
    True

    >>> needs_redirect('preview.local', '/style.css', 'http://preview.local/foo/bar/baz/')
    True

    >>> needs_redirect('preview.local', '/fee/fi/fo/fum/style.css', 'http://preview.local/foo/bar/baz/')
    True

    >>> needs_redirect('preview.local', '/', 'http://preview.local/foo/bar/br/anch/')
    True

    >>> needs_redirect('preview.local', '/style.css', 'http://preview.local/foo/bar/br/anch/')
    True

    >>> needs_redirect('preview.local', '/fee/fi/fo/fum/style.css', 'http://preview.local/foo/bar/br/anch/', 4)
    True

    >>> needs_redirect('preview.local', '/fee/fi/fo/fum/style.css', 'http://preview.local/foo/barbaz/', 2)
    True
    '''
    _, ref_host, ref_path, _, _, _ = urlparse(ref_url)
    
    #
    # Don't redirect when the request and referer hosts don't match.
    #
    if req_host != ref_host:
        return False
    
    pattern = r'(?P<preamble>' + (r'/[^/]+' * slash_count) + r')'
    ref_git_preamble_match = match(pattern, ref_path)
    
    #
    # Don't redirect when the referer doesn't appear to include a git path.
    #
    if not ref_git_preamble_match:
        return False
    
    #
    # Don't redirect when the request path already includes the git preamble.
    #
    if req_path.startswith(ref_git_preamble_match.group('preamble')):
        return False
    
    return True

if __name__ == '__main__':
    import doctest
    doctest.testmod()
