import bisect
import datetime
import json
import logging

import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME
import homeassistant.util.dt as dt_util
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)
_RESOURCE = 'https://data.texas.gov/download/mqtr-wwpy/text%2Fplain'

ATTR_STOP_ID = "Stop ID"
ATTR_ROUTE = "Route"
ATTR_DUE_IN = "Due in"
ATTR_DUE_AT = "Due at"
ATTR_NEXT_UP = "Later Bus"

CONF_STOP_ID = 'stopid'
CONF_ROUTE = 'route'
CONF_DEPARTURES = 'departures'

DEFAULT_NAME = 'Next Bus'
ICON = 'mdi:bus'

MIN_TIME_BETWEEN_UPDATES = datetime.timedelta(seconds=60)
TIME_STR_FORMAT = "%H:%M"


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_DEPARTURES): [{
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_STOP_ID): cv.string,
        vol.Required(CONF_ROUTE): cv.string
    }]
})


def due_in_minutes(timestamp):
    """Get the remaining minutes from now until a given datetime object."""
    diff = timestamp - dt_util.now().replace(tzinfo=None)
    return int(diff.total_seconds() / 60)


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Get the Dublin public transport sensor."""
    data = PublicTransportData()
    sensors = []
    for departure in config.get(CONF_DEPARTURES):
        sensors.append(AustinPublicTransportSensor(
            data,
            departure.get(CONF_STOP_ID),
            departure.get(CONF_ROUTE),
            departure.get(CONF_NAME)
        ))

    add_devices(sensors)


class AustinPublicTransportSensor(Entity):
    """Implementation of an Austin public transport sensor."""

    def __init__(self, data, stop, route, name):
        """Initialize the sensor."""
        self.data = data
        self._name = name
        self._stop = int(stop)
        self._route = int(route)
        self.update()

    @property
    def name(self):
        return self._name

    def _get_next_buses(self):
        return self.data.info.get(self._route, {}).get(self._stop, [])

    @property
    def state(self):
        """Return the state of the sensor."""
        next_buses = self._get_next_buses()
        return due_in_minutes(next_buses[0]) if len(next_buses) > 0 else '-'

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        next_buses = self._get_next_buses()
        return {
            ATTR_DUE_IN: self.state,
            ATTR_DUE_AT: next_buses[0].strftime('%I:%M %p') if len(next_buses) > 0 else '-',
            ATTR_NEXT_UP: next_buses[1].strftime('%I:%M %p') if len(next_buses) > 1 else '-',
            ATTR_STOP_ID: self._stop,
            ATTR_ROUTE: self._route
        }

    @property
    def unit_of_measurement(self):
        """Return the unit this state is expressed in."""
        return "min"

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return ICON

    def update(self):
        """Get the latest data from opendata.ch and update the states."""
        self.data.update()


class PublicTransportData(object):
    """The Class for handling the data retrieval."""

    def __init__(self):
        """Initialize the data object."""
        self.info = {}

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Get the latest data."""
        departure_times = {}
        r = requests.get(_RESOURCE)
        data = json.loads(r.text)

        for entry in data['entity']:
            route_id = int(entry['trip_update']['trip']['route_id'])
            if route_id not in departure_times:
                departure_times[route_id] = {}

            for stop in entry['trip_update']['stop_time_update']:
                stop_id = int(stop['stop_id'])
                if not departure_times[route_id].get(stop_id):
                    departure_times[route_id][stop_id] = []
                # Use stop departure time; fall back on stop arrival time if not available
                if 'departure' in stop:
                    departure_time = datetime.datetime.fromtimestamp(stop['departure']['time'])
                    bisect.insort(departure_times[route_id][stop_id], departure_time)
                elif 'arrival' in stop:
                    arrival_time = datetime.datetime.fromtimestamp(stop['arrival']['time'])
                    bisect.insort(departure_times[route_id][stop_id], arrival_time)

        self.info = departure_times
