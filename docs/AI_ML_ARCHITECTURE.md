# NAV-X AI / ML Architecture

```text
Official USNIC snapshots + CMEMS currents + ECMWF/ERA5 wind
                         |
                         v
              Real feature construction
                         |
                         v
              Physics baseline velocity
                         |
                  residual target
                         |
                         v
          RandomForest residual regression
                         |
               held-out validation gate
                         |
               +---------+---------+
               |                   |
             PASS                HOLD
               |                   |
               v                   v
        ML residual prior      physics only
               |
               v
  PrecisionIcebergTrajectoryModel (+6..72 h)
               |
               v
     Time-aware iceberg hazard envelopes
               |
               v
       Polar A* route alternatives
               |
               v
 Structured AI decision report / evidence
```

No database is required in this build. Saved model artifacts and model cards live under `models/ml/`.
