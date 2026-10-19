from functools import wraps
from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from ..extensions import db
from ..workflow import safe_local_path


def validated_operation(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except PermissionError:
            db.session.rollback()
            return render_template('errors/403.html'), 403
        except LookupError:
            db.session.rollback()
            return render_template('errors/404.html'), 404
        except ValueError as error:
            db.session.rollback()
            # Domain validation only. Database and programming failures are not
            # disguised as successful operations.
            if request.path.startswith('/api/'):
                return jsonify(ok=False, error=str(error)), 400
            flash(str(error), 'error')
            return render_template('operations/error.html'), 400
    return wrapped


def payload():
    return {key: request.form.getlist(key) for key in request.form
            if key not in {'csrf_token', 'request_key', 'password', 'code', 'current_password'}}
