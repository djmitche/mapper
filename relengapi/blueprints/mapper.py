# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import re
import time
import calendar
import sqlalchemy as sa
import dateutil.parser
from sqlalchemy import orm
from relengapi import db
from flask import Blueprint
from flask import g
from flask import abort
from flask import request
from flask import jsonify
from flask_login import login_required

bp = Blueprint('mapper', __name__)
rev_regex = re.compile('''^[a-f0-9]{1,40}$''')

# TODO: replace abort with a custom exception - http://flask.pocoo.org/docs/patterns/apierrors/

class Project(db.declarative_base('mapper')):
    __tablename__ = 'projects'

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String(255), nullable=False, unique=True)


class Hash(db.declarative_base('mapper')):
    __tablename__ = 'hashes'

    hg_changeset = sa.Column(sa.String(40), nullable=False)
    git_changeset = sa.Column(sa.String(40), nullable=False)
    project_id = sa.Column(sa.Integer, sa.ForeignKey('projects.id'), nullable=False)
    project = orm.relationship(Project, primaryjoin=(project_id == Project.id))
    date_added = sa.Column(sa.Integer, nullable=False)

    project_name = property(lambda self: self.project.name)

    def as_json(self):
        return jsonify(**{n: getattr(self, n)
                          for n in ('hg_changeset', 'git_changeset', 'date_added', 'project_name')})

    __table_args__ = (
        # TODO: (needs verification) all queries specifying a hash are for (project, hash), so these aren't used
        sa.Index('hg_changeset', 'hg_changeset'),
        sa.Index('git_changeset', 'git_changeset'),
        # TODO: this index is a prefix of others and will never be used
        sa.Index('project_id', 'project_id'),
        sa.Index('project_id__date_added', 'project_id', 'date_added'),
        sa.Index('project_id__hg_changeset', 'project_id', 'hg_changeset', unique=True),
        sa.Index('project_id__git_changeset', 'project_id', 'git_changeset', unique=True),
    )

    __mapper_args__ = {
        # tell the SQLAlchemy ORM about one of the unique indexes; it doesn't matter which
        'primary_key': [project_id, hg_changeset],
    }


def _project_filter(project_arg):
    """ Helper method that returns the select sql clause for the project
    name(s) specified for a project name field.  This can be comma-delimited,
    which is the way we combine queries across multiple projects.

    Args:
        project_arg: a string from the route, which may be comma-separated

    Returns:
        An SQLAlchemy filter expression
    """
    if ',' in project_arg:
        return Project.name.in_(project_arg.split(','))
    else:
        return Project.name == project_arg


def _build_mapfile(q):
    """ Helper method to build the full mapfile from a query
    Args:
        q: query

    Returns:
        Text output, which is 40 characters of hg changeset sha, a space,
        40 characters of git changeset sha, and a newline; or None if the query
        yields no results.

    Exceptions:
        HTTPError 404: No results found
    """
    contents = '\n'.join('%s %s' % (r.hg_changeset, r.git_changeset) for r in q)
    if contents:
        return contents + '\n'


def _check_existing_sha(project, vcs_type, changeset):
    """ Helper method to check for an existing changeset.
    Args:
        project: the project name(s) string, comma-delimited
        vcs_type: the vcs name string (hg or git)
        changeset: the changeset string to look for

    Returns:
        The first db row if it exists; otherwise None.
    """
    q = Hash.query.filter(_project_filter(project))
    q = q.filter("%s_changeset == :changeset" % (vcs_type,)).params(changeset=changeset)
    return q.first()


def _check_well_formed_sha(sha, exact_length=40):
    """Helper method to check for a well-formed sha.
    Args:
        sha: string to check against the well-formed sha regex.

    Returns:
        None on success.

    Exceptions:
        HTTPError 400: on non-well-formed sha, via flask.abort()
    """
    if not rev_regex.match(sha):
        abort(400, "Bad sha %s!" % str(sha))
    if exact_length is not None and len(sha) != exact_length:
        abort(400, "Bad sha %s!" % str(sha))


def _get_project(session, project):
    p = Project.query.filter_by(name=project).first()
    if not p:
        abort(404)
    return p


def _add_hash(session, hg_changeset, git_changeset, project):
    _check_well_formed_sha(hg_changeset)
    _check_well_formed_sha(git_changeset)
    h = Hash(hg_changeset=hg_changeset, git_changeset=git_changeset, project=project, date_added=time.time())
    session.add(h)


@bp.route('/<project>/rev/<vcs_type>/<changeset>')
def get_rev(project, vcs_type, changeset):
    """Translate git/hg revisions.

    Args:
        project: comma-delimited project names(s) string
        vcs: hg or git, string
        changeset: revision or partial revision string

    Returns:
        A string row if the query matches.

    Exceptions:
        HTTPError 400: if an unknown vcs
        HTTPError 400: if a badly formed sha
        HTTPError 404: if row not found.
    """
    if vcs_type not in ("git", "hg"):
        abort(400, "Unknown vcs type %s" % vcs_type)
    _check_well_formed_sha(changeset, exact_length=None)
    q = Hash.query.filter(_project_filter(project))
    q = q.filter("%s_changeset like :cspatttern" % (vcs_type,)).params(cspatttern=changeset+"%")
    row = q.first()
    if row:
        return "%s %s" % (row.hg_changeset, row.git_changeset)
    else:
        return "not found", 404


@bp.route('/<project>/mapfile/full')
def get_full_mapfile(project):
    """Get a full mapfile. <project> can be a comma-delimited set of projects

    Args:
        project: comma-delimited project names(s) string

    Yields:
        full mapfile for the given project

    Exceptions:
        HTTPError 404: No results found
    """
    q = Hash.query.filter(_project_filter(project))
    q = q.order_by(Hash.git_changeset)
    mapfile = _build_mapfile(q)
    if not mapfile:
        abort(404, 'not found')
    return mapfile


@bp.route('/<project>/mapfile/since/<since>')
def get_mapfile_since(project, since):
    """Get a mapfile since date.  <project> can be a comma-delimited set of projects

    Args:
        project: comma-delimited project names(s) string
        since: a timestamp, in a format parsed by [dateutil.parser.parse](https://labix.org/python-dateutil)

    Yields:
        Partial mapfile since date, from _build_mapfile

    Exceptions:
        HTTPError 404: No results found, via _build_mapfile
    """
    try:
        since_dt = dateutil.parser.parse(since)
    except Exception:
        abort(400, 'invalid date; see https://labix.org/python-dateutil')
    since_epoch = calendar.timegm(since_dt.utctimetuple())
    q = Hash.query.filter(_project_filter(project))
    q = q.order_by(Hash.git_changeset)
    q = q.filter(Hash.date_added > since_epoch)
    print q
    mapfile = _build_mapfile(q)
    if not mapfile:
        abort(404, 'not found')
    return mapfile


def _insert_many(project, dups=False):
    """Update the db with many lines.

    Args:
        project: single project name string (not comma-delimited list)
        dups: boolean.  If False, abort on duplicate entries without inserting
        anything

    Returns:
        200 on success

    Exceptions:
        HTTPError 409: if dups=False and there were duplicate entries.
        HTTPError 400: if the content-type is incorrect
    """
    if request.content_type != 'text/plain':
        abort(400, "content-type must be text/plain")
    session = g.db.session('mapper')
    proj = _get_project(session, project)
    for line in request.stream.readlines():
        line = line.rstrip()
        try:
            (hg_changeset, git_changeset) = line.split(' ')
        except ValueError:
            # header/footer won't match this format
            continue
        _add_hash(session, hg_changeset, git_changeset, proj)
        if dups:
            try:
                session.commit()
            except sa.exc.IntegrityError:
                session.rollback()
    if not dups:
        try:
            session.commit()
        except sa.exc.IntegrityError:
            abort(409, "some of the given mappings already exist")
    return jsonify()


#@check_client_ip
@bp.route('/<project>/insert', methods=('POST',))
@login_required
def insert_many_no_dups(project):
    """Insert many mapfile entries via POST, and error on duplicate SHAs.

    Args:
        project: single project name string (not comma-delimited list)
        POST data: mapfile lines (hg_changeset git_changeset\n)
        Content-Type: text/plain

    Returns:
        A string of unsuccessful entries.

    Exceptions:
        HTTPError 206: if there were duplicate entries.
    """
    return _insert_many(project, dups=False)


#@check_client_ip
@bp.route('/<project>/insert/ignoredups', methods=('POST',))
@login_required
def insert_many_allow_dups(project):
    """Insert many mapfile entries via POST, and don't error on duplicate SHAs.

    Args:
        project: single project name string (not comma-delimited list)
        POST data: mapfile lines (hg_changeset git_changeset\n)
        Content-Type: text/plain

    Returns:
        A string of unsuccessful entries.
    """
    return _insert_many(project, dups=True)


#@check_client_ip
@bp.route('/<project>/insert/<hg_changeset>/<git_changeset>')
@login_required
def insert_one(project, hg_changeset, git_changeset):
    """Insert a single mapping

    Args:
        project: single project name string (not comma-delimited list)
        hg_changeset: 40 char hexadecimal string.
        git_changeset: 40 char hexadecimal string.

    Returns:
        A string row on success

    Exceptions:
        HTTPError 500: No results found
        HTTPError 409: Mapping already exists for this project
        HTTPError 400: Badly formed sha.
    """
    session = g.db.session('mapper')
    proj = _get_project(session, project)
    _add_hash(session, hg_changeset, git_changeset, proj)
    try:
        session.commit()
    except sa.exc.IntegrityError:
        abort(409, "mapping already exists")
    row = _check_existing_sha(project, 'hg', hg_changeset)
    if row:
        return row.as_json()
    else:
        abort(500, "row doesn't exist!")

@bp.route('/<project>', methods=('POST',))
@login_required
def add_project(project):
    """Insert a new project into the DB.

    Args:
        project: single project name string (not comma-delimited list)

    Returns:
        200 OK on success
        409 Conflict if the project already exists
    """

    session = g.db.session('mapper')
    p = Project(name=project)
    session.add(p)
    try:
        session.commit()
    except (sa.exc.IntegrityError, sa.exc.ProgrammingError):
        abort(409)
    return jsonify()
