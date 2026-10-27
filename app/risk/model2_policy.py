"""Optional bounded heuristic overrides. Values are scores, not probabilities."""
import json
import os

def severity(event_type, defaults):
    overrides=json.loads(os.getenv('MODEL2_SEVERITY_WEIGHTS','{}'))
    if not isinstance(overrides,dict):raise ValueError('MODEL2_SEVERITY_WEIGHTS must be a JSON object')
    for key,value in overrides.items():
        if key not in defaults or type(value) not in (int,float) or not 0 <= value <= 35:
            raise ValueError('Severity overrides require known event names and values 0..35')
    return overrides.get(event_type,defaults.get(event_type,10.0))

def thresholds():
    values=json.loads(os.getenv('MODEL2_RISK_THRESHOLDS','[25,45,70]'))
    if not isinstance(values,list) or len(values)!=3 or any(type(v) not in (int,float) or not 0<v<=100 for v in values) or not values[0]<values[1]<values[2]:
        raise ValueError('Thresholds must be three increasing numbers in (0,100]')
    return values
