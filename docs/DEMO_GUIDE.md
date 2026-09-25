# 60-Second SIH Demo Guide

To demonstrate Antarctic NAV-X to the SIH evaluators, execute the following flow:

1. **Start the Application:** For local testing run `python -m src.api.main` and open `http://localhost:8000`. For judges/public access, use the deployed HTTPS URL described in `PUBLISH_SITE.md`.
2. **Explain the Interface (10s):** Point out the Model Status ("Physics Baseline Active"), the Data Provenance panel ("Cached Real Data"), and the Risk panel.
3. **Run Scenario 1 - Safe Route (10s):** Click Button 1. Watch the system draw a route safely distant from any red iceberg markers. The risk panel turns Green.
4. **Run Scenario 2 - Hazard (15s):** Click Button 2. The vessel route now directly intersects the forecasted iceberg drift. The panel immediately flashes Red (CRITICAL), outputs the closest approach (e.g. 9.5 km), and explains the temporal intersection.
5. **Run Scenario 4 - Alternatives (25s):** Click Button 4. The system detects the hazard and instantly computes and visualizes a green alternative route bypassing the uncertainty cone, explicitly labeling it "Recommended for further operator review".
