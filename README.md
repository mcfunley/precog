Precog
======

Previously [known as Git-Jekyll Preview](http://github.com/codeforamerica/git-jekyll-preview).

Preview your static websites built with CircleCI before making them live.
Use it to check your plain static or [Jekyll](http://jekyllrb.com/)-generated
websites before you make them live to [Github Pages](http://pages.github.com/)
or to your own server. Requires configured and working
[CircleCI artifacts](https://circleci.com/docs/build-artifacts).

Try it live at [precog.mapzen.com](http://precog.mapzen.com).

Status, Contact
---------------

Precog is mostly a singleton-app, built only to be run at a single
location. For the time being, it's not intended for general redeployment but
improvements for [precog.mapzen.com](http://precog.mapzen.com)
are welcomed.

[Michal Migurski](https://github.com/migurski) is currently maintainer.

Install
-------

The application is a [Flask](http://flask.pocoo.org)-based Python server.
[OAuth](http://developer.github.com/v3/oauth/) is used for authentication;
put your client ID and secret in environment variables `GITHUB_CLIENT_ID`
and `GITHUB_CLIENT_SECRET`, and your CircleCI developer key in `CIRCLECI_TOKEN`.

To run for testing:

    python make-it-so.py

To run in production, with [Gunicorn](http://gunicorn.org):

    gunicorn make-it-so:app
