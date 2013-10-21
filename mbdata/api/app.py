# Copyright (C) 2013 Lukas Lalinsky
# Distributed under the MIT license, see the LICENSE file for details.

from flask import Flask, g, request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from mbdata.api.blueprints.artist import blueprint as artist_blueprint
from mbdata.api.blueprints.place import blueprint as place_blueprint
from mbdata.api.blueprints.recording import blueprint as recording_blueprint
from mbdata.api.blueprints.release import blueprint as release_blueprint
from mbdata.api.blueprints.release_group import blueprint as release_group_blueprint
from mbdata.api.blueprints.work import blueprint as work_blueprint


app = Flask(__name__)
app.config.from_object('mbdata.api.commonsettings')
app.config.from_envvar('MBDATA_API_SETTINGS')

app.register_blueprint(artist_blueprint, url_prefix='/1.0/artist')
app.register_blueprint(place_blueprint, url_prefix='/1.0/place')
app.register_blueprint(recording_blueprint, url_prefix='/1.0/recording')
app.register_blueprint(release_blueprint, url_prefix='/1.0/release')
app.register_blueprint(release_group_blueprint, url_prefix='/1.0/release_group')
app.register_blueprint(work_blueprint, url_prefix='/1.0/work')

Session = engine = None

def setup_db():
    global engine, Session
    engine = create_engine(app.config['DATABASE_URI'], echo=app.config['DATABASE_ECHO'])
    Session = sessionmaker(bind=engine)

setup_db()


@app.before_request
def before_request():
    g.db = Session()


@app.teardown_request
def teardown_request(exception):
    g.db.close()


@app.after_request
def after_request(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    headers = request.headers.get('Access-Control-Request-Headers')
    if headers is not None:
        response.headers['Access-Control-Allow-Headers'] = headers
    return response


if __name__ == "__main__":
    app.run(debug=True)

