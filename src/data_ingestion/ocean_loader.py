from src.data_providers.ocean_provider import OceanDataOrchestrator

def load_ocean_data():
    orchestrator = OceanDataOrchestrator()
    try:
        ds, metadata = orchestrator.get_data()
        print("\n==================================================")
        print(f"SOURCE: {metadata['source']}")
        print(f"DATASET: {metadata['dataset_id']}")
        print(f"TIMESTAMP: {metadata['timestamp']}")
        print(f"BOUNDS: {metadata['bounds']}")
        print(f"VARIABLES: {metadata['variables']}")
        print("==================================================\n")
        return ds, metadata
    except RuntimeError as e:
        print("\n==================================================")
        print("ERROR: DATA PROVIDERS FAILED")
        print(str(e))
        print("REQUIRED USER ACTION: Either configure `copernicusmarine login` OR place a valid ocean NetCDF file in data/raw/.")
        print("==================================================\n")
        return None, None

if __name__ == "__main__":
    load_ocean_data()
