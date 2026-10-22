# MedMitra pharmacy finder and dark-mode update

## Current behavior

- Removed the separate fictional Google-Maps-style schematic/demo map and its dedicated CSS/JavaScript assets.
- Kept the existing verified-pharmacy directory and its original Leaflet/OpenStreetMap map, route, and data behavior.
- Shifted dark mode from pure black to a softer charcoal/slate palette for page surfaces, cards, forms, tables, navigation, and map controls. Light-mode styles are unchanged.
- Added extra spacing between Shop by Category tiles only: 18px column / 16px row gap on desktop and 12px on small screens. No other commerce rails were changed.
- No Django model, view, form, URL, authentication, order, prescription, or database code was changed.

## Local verification

From the project directory containing `manage.py`, run:

```powershell
python manage.py check
python manage.py test
python manage.py runserver 127.0.0.1:8000
```

Use `http://127.0.0.1:8000/` for local development (HTTP, not HTTPS).
