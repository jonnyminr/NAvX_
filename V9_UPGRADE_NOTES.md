# ANTARCTIC NAV-X V9 Upgrade Notes

## Removed

- Mission Overview sidebar item
- Emoji navigation icons
- Indian research-station destination presets
- Great Lakes / river workflow
- decorative iceberg/ship marker hover and bobbing motion
- map cursor/pointer readout
- assistant-style route chat panel
- assistant/model branding in the visible application

## Added

- Antarctic sea-only destination list
- browser GPS location detection and accuracy reporting
- "Use GPS as Origin" and "Route from GPS"
- route duration + estimated arrival UTC
- same-window Iceberg Catalog hyperlink
- same-window AIS Vessel Catalog hyperlink
- iceberg USNIC series/type and size class
- route comparison graph
- static SVG map markers
- time-aware geodesic A* route optimizer
- safety-first recommended route selection

## Route engine V9

The route cost now matches the vessel's estimated time at each candidate grid cell against the corresponding interpolated iceberg forecast position and its uncertainty envelope. The final route geometry is geodesically densified before CPA/TCA assessment.
