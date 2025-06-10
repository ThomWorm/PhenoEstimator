# phenoestimator/io/inat_io.py

from pyinaturalist import get_observations
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import json
import urllib.parse

DEFAULT_PER_PAGE = 200

def parse_api_params(api_param_string: str) -> Dict[str, Any]:
    """
    Parse URL parameter string into dictionary for pyinaturalist.
    
    Args:
        api_param_string: String like "taxon_name=Cynips&field:Life_Stage=adult&place_id=1"
    
    Returns:
        Dict of parameters ready for pyinaturalist.get_observations()
    """
    params = {}
    if not api_param_string.strip():
        return params
    
    # Parse the parameter string
    for param_pair in api_param_string.split('&'):
        if '=' in param_pair:
            key, value = param_pair.split('=', 1)
            key = urllib.parse.unquote(key)
            value = urllib.parse.unquote(value)
            
            # Handle special cases for pyinaturalist
            if key == 'place_id':
                # Could be single ID or comma-separated list
                if ',' in value:
                    params[key] = [int(x.strip()) for x in value.split(',')]
                else:
                    params[key] = int(value)
            elif key in ['taxon_id', 'per_page', 'page']:
                params[key] = int(value)
            elif key in ['verifiable']:
                params[key] = value.lower() in ('true', '1', 'yes')
            elif key.startswith('field:'):
                # Custom observation fields
                params[key] = value
            else:
                params[key] = value
    
    return params

def build_api_url(base_params: Dict[str, Any]) -> str:
    """Build the actual API URL that would be called for logging/reproducibility."""
    base_url = "https://api.inaturalist.org/v1/observations"
    
    # Convert params back to URL format
    url_params = []
    for key, value in base_params.items():
        if isinstance(value, list):
            for v in value:
                url_params.append(f"{urllib.parse.quote(key)}={urllib.parse.quote(str(v))}")
        else:
            url_params.append(f"{urllib.parse.quote(key)}={urllib.parse.quote(str(value))}")
    
    if url_params:
        return f"{base_url}?{'&'.join(url_params)}"
    return base_url

def get_observations_from_params(api_param_string: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Fetch observations using a parameter string and return raw JSON data with metadata.
    
    Args:
        api_param_string: URL parameter string like "taxon_name=Cynips&place_id=1"
        limit: Optional limit on number of observations to fetch
    
    Returns:
        Dict with 'observations' (list of raw JSON dicts), 'total_fetched', and 'api_url'
    """
    # Parse the parameter string
    base_params = parse_api_params(api_param_string)
    
    # Add defaults
    base_params.setdefault('order', 'desc')
    base_params.setdefault('order_by', 'observed_on')
    base_params.setdefault('quality_grade', 'research')
    
    # Build URL for logging
    api_url = build_api_url(base_params)
    
    all_observations: List[Dict[str, Any]] = []
    current_page = 1
    keep_fetching = True
    total_results_api = 0

    while keep_fetching:
        api_params = base_params.copy()
        api_params.update({
            'page': current_page,
            'per_page': DEFAULT_PER_PAGE
        })
        
        try:
            full_api_response_dict = get_observations(**api_params)
        except Exception as e:
            print(f"Error calling pyinaturalist.get_observations for page {current_page}: {e}")
            break 

        if not full_api_response_dict or not isinstance(full_api_response_dict, dict):
            keep_fetching = False
        else:
            if current_page == 1:
                total_results_api = full_api_response_dict.get('total_results', 0)

            raw_observation_list = full_api_response_dict.get('results', [])

            if not raw_observation_list:
                keep_fetching = False
            else:
                # Just add the raw JSON observations directly
                all_observations.extend(raw_observation_list)
                print(f"  -> Page {current_page}: {len(raw_observation_list)} observations")

                if limit is not None and len(all_observations) >= limit:
                    keep_fetching = False
                if total_results_api > 0 and len(all_observations) >= total_results_api:
                    keep_fetching = False
                if keep_fetching:
                     current_page += 1
            
    if limit is not None and len(all_observations) > limit:
        all_observations = all_observations[:limit]
    
    return {
        'observations': all_observations,
        'total_fetched': len(all_observations),
        'api_url': api_url
    }

def process_phenology_config(config: Union[str, Dict[str, Any]], limit_per_set: Optional[int] = None) -> Dict[str, Any]:
    """
    Process a phenology study configuration and fetch all required observation sets.
    
    Args:
        config: Either a JSON string or dict with study configuration
        limit_per_set: Optional limit on observations per observation set
    
    Returns:
        Dict with raw JSON observations, metadata, and processing info
    """
    # Parse config if it's a string
    if isinstance(config, str):
        config = json.loads(config)
    
    # Validate required fields
    if 'model_type' not in config:
        raise ValueError("Config must include 'model_type'")
    if 'observation_sets' not in config:
        raise ValueError("Config must include 'observation_sets'")
    
    model_type = config['model_type']
    observation_sets = config['observation_sets']
    
    # Validate model type and required observation sets
    valid_types = {'event', 'transition', 'three_stage'}
    if model_type not in valid_types:
        raise ValueError(f"model_type must be one of {valid_types}")
    
    if model_type == 'event' and 'event' not in observation_sets:
        raise ValueError("Event model requires 'event' observation set")
    elif model_type == 'transition' and not all(k in observation_sets for k in ['before', 'after']):
        raise ValueError("Transition model requires 'before' and 'after' observation sets")
    elif model_type == 'three_stage' and not all(k in observation_sets for k in ['before', 'event', 'after']):
        raise ValueError("Three-stage model requires 'before', 'event', and 'after' observation sets")
    
    # Process each observation set
    observations = {}
    api_urls = {}
    total_counts = {}
    
    for set_name, set_config in observation_sets.items():
        if 'api_params' not in set_config:
            raise ValueError(f"Observation set '{set_name}' missing 'api_params'")
        
        print(f"Fetching {set_name} observations...")
        result = get_observations_from_params(set_config['api_params'], limit_per_set)
        
        observations[set_name] = result['observations']  # Raw JSON list
        api_urls[set_name] = result['api_url']
        total_counts[set_name] = result['total_fetched']
        
        print(f"  -> Fetched {result['total_fetched']} observations")
    
    # Build output structure
    output = {
        'observations': observations,  # Dict of lists of raw JSON observation dicts
        'config': config,
        'processing_metadata': {
            'timestamp': datetime.now().isoformat(),
            'phenoestimator_version': '0.2.1',  # TODO: Get from package
            'total_records_fetched': total_counts,
            'api_request_urls': api_urls,
            'model_type': model_type
        }
    }
    
    return output

def save_phenology_study(study_result: Dict[str, Any], output_dir: str = ".") -> None:
    """
    Save phenology study results to files.
    
    Args:
        study_result: Output from process_phenology_config()
        output_dir: Directory to save files in
    """
    import os
    
    study_name = study_result['config'].get('metadata', {}).get('study_name', 'phenology_study')
    
    # Save raw observations as JSON files
    for set_name, obs_list in study_result['observations'].items():
        filename = os.path.join(output_dir, f"{study_name}_{set_name}_observations.json")
        with open(filename, 'w') as f:
            json.dump(obs_list, f, indent=2)
        print(f"Saved {len(obs_list)} {set_name} observations to {filename}")
    
    # Save metadata
    metadata_filename = os.path.join(output_dir, f"{study_name}_metadata.json")
    metadata = {
        'config': study_result['config'],
        'processing_metadata': study_result['processing_metadata']
    }
    with open(metadata_filename, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved study metadata to {metadata_filename}")

# Backward compatibility function
def get_inat_observations(
    taxon_name: Optional[str] = None,
    taxon_id: Optional[int] = None,
    place_id: Optional[Union[int, List[int], str]] = None,
    quality_grade: str = "research",
    limit: Optional[int] = None,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Backward compatibility function - returns raw observation JSON.
    For DataFrame output, use the old version or convert manually.
    """
    # Build parameter string
    params = []
    if taxon_name: params.append(f"taxon_name={taxon_name}")
    if taxon_id: params.append(f"taxon_id={taxon_id}")
    if place_id: 
        if isinstance(place_id, list):
            params.append(f"place_id={','.join(map(str, place_id))}")
        else:
            params.append(f"place_id={place_id}")
    if quality_grade and quality_grade.lower() != 'any': 
        params.append(f"quality_grade={quality_grade}")
    
    for key, value in kwargs.items():
        params.append(f"{key}={value}")
    
    param_string = "&".join(params)
    result = get_observations_from_params(param_string, limit)
    return result['observations']