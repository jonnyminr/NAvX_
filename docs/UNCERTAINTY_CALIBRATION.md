# Uncertainty Calibration

## 1. Current State
The Phase 5 uncertainty envelope (`1km + 5% displacement`) is strictly a **heuristic/modelled uncertainty envelope**.

## 2. Future Calibration
When historical test data is integrated, this heuristic will be replaced with empirical error distributions. 
- The empirical 95th percentile error at `+24h`, `+48h`, and `+72h` for the Hybrid Model will define the radius of the forecast cone.
- Only once this test-set verification is achieved will the cone be labeled as **"Calibrated Statistical Uncertainty."**
