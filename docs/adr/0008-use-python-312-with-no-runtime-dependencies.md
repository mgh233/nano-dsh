# Use Python 3.12 with no runtime dependencies

nano-dsh requires Python 3.12 and uses only the standard library in production
and tests. `tomllib`, `urllib.request`, `subprocess`, `pathlib`, `importlib`,
and `unittest` cover the selected feature set. Avoiding SDKs and frameworks
keeps both setup and the core mechanisms visible to new readers.
