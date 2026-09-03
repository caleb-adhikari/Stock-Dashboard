"""Data source adapters. Each module here is responsible for producing
typed objects from models.py (GaapQuarter / NonGaapQuarter) from one
particular source — SEC EDGAR, a manual JSON file, and eventually an
automated press-release parser. Nothing outside this package should know
or care where the data physically came from."""
