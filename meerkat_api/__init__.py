"""
meerkat_api.py

Root Flask app for the Meerkat API.
"""
from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy
from flask_restful import Api

from meerkat_abacus import config
from meerkat_abacus import model

# Create the Flask app
app = Flask(__name__)
app.config.from_object('config.Development')
app.config.from_envvar('MEERKAT_API_SETTINGS', silent=True)
db = SQLAlchemy(app)
api = Api(app)

from meerkat_api.resources.locations import Location, Locations
from meerkat_api.resources.variables import Variables, Variable
from meerkat_api.resources.data import Aggregate, AggregateYear
from meerkat_api.resources.data import AggregateCategory

api.add_resource(Locations, "/locations")
api.add_resource(Location, "/location/<location_id>")
api.add_resource(Variables, "/variables/<category>")
api.add_resource(Variable, "/variable/<variable_id>")
api.add_resource(Aggregate, "/aggregate/<variable_id>/<location_id>")
api.add_resource(AggregateYear,
                 "/aggregate_year/<variable_id>/<location_id>",
                 "/aggregate_year/<variable_id>/<location_id>/<year>")
api.add_resource(AggregateCategory,
                 "/aggregate_category/<category>/<location_id>",
                 "/aggregate_category/<category>/<location_id>/<year>")


@app.route('/')
def hello_world():
    return 'Hello WHO 2!'
