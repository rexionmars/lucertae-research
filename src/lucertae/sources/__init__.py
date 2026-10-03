"""Data sources.

    series    readers of the ONS open series on disk, one source per series
    db        connection to the local PostGIS
    ons       download of ONS open data and loading into the br schema
    weather   archived Open-Meteo forecasts for the solar and wind clusters

`db`, `ons` and `weather` need the local PostGIS and are imported on demand.
"""
