import polars as pl
from typing import Optional, Union
import pyinaturalist as pynat


def get_inat_observations(taxon_name: str) -> pl.DataFrame:
    """
    Fetches structuredobservations from the iNaturalist API for a given taxon name.


    Args:
        taxon_name (str): The name of the taxon to fetch observations for.

    Returns:
        pl.DataFrame: A DataFrame containing the observations.
        variables:
            - id: Unique identifier for the observation
            - name: Name of the taxon
            - date: Date of the observation
            - latitude: Latitude of the observation
            - longitude: Longitude of the observation
            - lifestage : Life stage of the organism #TODO what will this be?
            -
    """
    data = []
    return pl.DataFrame(data)
