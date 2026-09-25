"""Machine-learning components for ANTARCTIC NAV-X.

Scientific observations are never fabricated by this package.  Training
utilities only consume archived official/provider observations already present
in ``data/`` or explicitly supplied by the operator.
"""

from .iceberg_drift import IcebergResidualML
from .ais_anomaly import AISAnomalyML

__all__ = ["IcebergResidualML", "AISAnomalyML"]
