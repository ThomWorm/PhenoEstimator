# phenoestimator/io/inat_io.py

import polars as pl
from pyinaturalist import get_observations
from pyinaturalist.models import Observation # Annotation model is usually part of Observation or imported separately if needed
from typing import Optional, List, Dict, Any, Union
from datetime import date as date_type

# --- Constants ---
R_SCRIPT_PHENO_COLS = ["Plant_Phenology", "Evidence_of_Presence", "Life_Stage", "Gall_generation", "Gall_phenophase", "Host_Plant_ID", "Rearing_viability"]
TARGET_OUTPUT_COLUMNS = ['obs_id', 'lifestage_derived', 'date', 'latitude', 'longitude', 'taxon_name', 'uri'] + R_SCRIPT_PHENO_COLS
COLUMN_TYPES = {'obs_id': pl.Int64, 'lifestage_derived': pl.Utf8, 'date': pl.Date, 'latitude': pl.Float64, 'longitude': pl.Float64, 'taxon_name': pl.Utf8, 'uri': pl.Utf8, **{col: pl.Utf8 for col in R_SCRIPT_PHENO_COLS}}
DEFAULT_PER_PAGE = 200

def get_inat_observations(
    taxon_name: Optional[str] = None,
    taxon_id: Optional[int] = None,
    gallformers_code: Optional[str] = None,
    place_id: Optional[Union[int, List[int], str]] = None,
    quality_grade: str = "research",
    verifiable: Optional[bool] = None,
    order_by: str = "observed_on",
    order: str = "desc",
    d1: Optional[str] = None,
    d2: Optional[str] = None,
    limit: Optional[int] = None,
) -> pl.DataFrame:
    
    all_converted_observation_models: List[Observation] = []
    current_page = 1
    keep_fetching = True
    total_results_api = 0

    # print(f"DEBUG: Initial user limit: {limit}") # Keep for now

    while keep_fetching:
        api_params: Dict[str, Any] = {
            'order': order, 'order_by': order_by, 'page': current_page,
            'per_page': DEFAULT_PER_PAGE 
        }
        if verifiable is not None: api_params['verifiable'] = verifiable
        if quality_grade and quality_grade.lower() != 'any': api_params['quality_grade'] = quality_grade
        if taxon_name: api_params['taxon_name'] = taxon_name
        elif taxon_id: api_params['taxon_id'] = taxon_id
        if gallformers_code: api_params['field:gallformers code'] = gallformers_code
        if place_id: api_params['place_id'] = place_id
        if d1: api_params['d1'] = d1
        if d2: api_params['d2'] = d2
        
        # print(f"DEBUG: Fetching page {current_page} with params: {api_params}") # Keep for now
        
        full_api_response_dict = None
        try:
            full_api_response_dict = get_observations(**api_params)
        except Exception as e:
            print(f"Error calling pyinaturalist.get_observations for page {current_page}: {e}")
            break 

        if not full_api_response_dict or not isinstance(full_api_response_dict, dict):
            # print(f"DEBUG: pyinaturalist.get_observations did not return a valid dictionary for page {current_page}.")
            keep_fetching = False
        else:
            if current_page == 1:
                total_results_api = full_api_response_dict.get('total_results', 0)
                # print(f"DEBUG: API reports total_results: {total_results_api}")

            raw_observation_list_from_json = full_api_response_dict.get('results', [])

            if not raw_observation_list_from_json:
                # print(f"DEBUG: No 'results' found or 'results' list is empty for page {current_page}.")
                keep_fetching = False
            else:
                # print(f"DEBUG: Page {current_page} - API returned {len(raw_observation_list_from_json)} raw records in 'results' list.")
                page_converted_models = []
                for i, obs_json_dict in enumerate(raw_observation_list_from_json):
                    try:
                        model = Observation.from_json(obs_json_dict)
                        page_converted_models.append(model)
                    except Exception as e:
                        print(f"WARNING: Page {current_page}, Record {i+1} (ID: {obs_json_dict.get('id')}) - Failed to convert to Observation model: {e}")
                
                if page_converted_models:
                    all_converted_observation_models.extend(page_converted_models)
                    # print(f"DEBUG: Successfully converted and added {len(page_converted_models)} models from page {current_page}. Total models now: {len(all_converted_observation_models)}")
                # else:
                    # print(f"DEBUG: No models successfully converted on page {current_page}.")

                if limit is not None:
                    if len(all_converted_observation_models) >= limit:
                        # print(f"DEBUG: Reached or exceeded user limit of {limit}.")
                        keep_fetching = False
                if total_results_api > 0 and len(all_converted_observation_models) >= total_results_api:
                    # print(f"DEBUG: All {total_results_api} available records fetched.")
                    keep_fetching = False
                if keep_fetching:
                     current_page += 1
            
    if limit is not None and len(all_converted_observation_models) > limit:
        # print(f"DEBUG: Truncating {len(all_converted_observation_models)} records to user limit of {limit}.")
        all_converted_observation_models = all_converted_observation_models[:limit]

    # print(f"DEBUG: Total Observation models collected for DataFrame: {len(all_converted_observation_models)}")

    processed_observations_list: List[Dict[str, Any]] = []
    if all_converted_observation_models:
        for obs_model in all_converted_observation_models:
            record: Dict[str, Any] = {
                'obs_id': obs_model.id,
                'date': obs_model.observed_on.date() if obs_model.observed_on else None,
                'latitude': obs_model.lat if hasattr(obs_model, 'lat') else None,
                'longitude': obs_model.lng if hasattr(obs_model, 'lng') else (obs_model.lon if hasattr(obs_model, 'lon') else None),
                'taxon_name': obs_model.taxon.name if obs_model.taxon else None,
                'uri': obs_model.uri,
            }
            
            # --- MODIFIED ANNOTATION PROCESSING ---
            obs_annotations_data: Dict[str, str] = {}
            # obs_model.annotations is a list of Annotation objects
            if hasattr(obs_model, 'annotations') and obs_model.annotations:
                for ann_obj in obs_model.annotations: # ann_obj is an Annotation model instance
                    # The Annotation model has .controlled_attribute (another model) and .controlled_value (another model)
                    # Each of those should have a .label attribute
                    term_label = None
                    value_label = None
                    
                    if hasattr(ann_obj, 'controlled_attribute') and ann_obj.controlled_attribute and hasattr(ann_obj.controlled_attribute, 'label'):
                        term_label = ann_obj.controlled_attribute.label
                    
                    if hasattr(ann_obj, 'controlled_value') and ann_obj.controlled_value and hasattr(ann_obj.controlled_value, 'label'):
                        value_label = ann_obj.controlled_value.label

                    if term_label and value_label:
                        col_name = term_label.replace(" ", "_")
                        existing_val = obs_annotations_data.get(col_name, "")
                        obs_annotations_data[col_name] = (existing_val + "; " if existing_val else "") + value_label
            record.update(obs_annotations_data)
            # --- END MODIFIED ANNOTATION PROCESSING ---

            # --- MODIFIED OBSERVATION FIELD PROCESSING ---
            obs_ofv_data: Dict[str, str] = {}
            # The attribute is likely 'ofvs' (Observation Field Values) or 'observation_fields'
            # Let's try 'ofvs' first as it's common in pyinaturalist models and your R code implies it
            # Each item in obs_model.ofvs is an ObservationFieldValue object
            # which should have .name (for the field name/label) and .value (for the field value)
            ofv_list_attr_name = None
            if hasattr(obs_model, 'ofvs'):
                ofv_list_attr_name = 'ofvs'
            elif hasattr(obs_model, 'observation_field_values'): # Fallback to the longer name
                 ofv_list_attr_name = 'observation_field_values'
            
            if ofv_list_attr_name and getattr(obs_model, ofv_list_attr_name):
                for ofv_obj in getattr(obs_model, ofv_list_attr_name): # ofv_obj is an ObservationFieldValue model
                    # ObservationFieldValue model should have .name and .value
                    field_name = None
                    field_value_str = None

                    if hasattr(ofv_obj, 'name') and ofv_obj.name:
                        field_name = ofv_obj.name
                    
                    if hasattr(ofv_obj, 'value') and ofv_obj.value is not None:
                         field_value_str = str(ofv_obj.value)

                    if field_name and field_value_str is not None:
                        col_name = field_name.replace(" ", "_")
                        existing_val = obs_ofv_data.get(col_name, "")
                        obs_ofv_data[col_name] = (existing_val + "; " if existing_val else "") + field_value_str
            record.update(obs_ofv_data)
            # --- END MODIFIED OBSERVATION FIELD PROCESSING ---
            
            processed_observations_list.append(record)

    if not processed_observations_list:
        empty_df_series = [pl.Series(name=col, values=[], dtype=COLUMN_TYPES.get(col, pl.Utf8)) for col in TARGET_OUTPUT_COLUMNS]
        return pl.DataFrame(empty_df_series)

    df = pl.DataFrame(processed_observations_list)
    for col_name in df.columns:
        if df[col_name].dtype == pl.Utf8:
            df = df.with_columns(pl.when(pl.col(col_name).str.starts_with("; ")).then(pl.col(col_name).str.slice(2)).otherwise(pl.col(col_name)).alias(col_name))

    life_stage_col_name = "Life_Stage"; plant_pheno_col_name = "Plant_Phenology"
    if life_stage_col_name not in df.columns: df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias(life_stage_col_name))
    if plant_pheno_col_name not in df.columns: df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias(plant_pheno_col_name))
    df = df.with_columns(pl.coalesce([pl.col(life_stage_col_name), pl.col(plant_pheno_col_name)]).cast(pl.Utf8).alias("lifestage_derived"))

    select_expressions = []; 
    for col_name in TARGET_OUTPUT_COLUMNS:
        col_type = COLUMN_TYPES.get(col_name, pl.Utf8)
        if col_name in df.columns: select_expressions.append(pl.col(col_name).cast(col_type, strict=False))
        else: select_expressions.append(pl.lit(None).cast(col_type).alias(col_name))
    df = df.select(select_expressions)
    return df