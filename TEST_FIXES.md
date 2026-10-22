# MedMitra test fixes

This update addresses the errors in the provided Django test output:

1. In DEBUG/local mode, staticfiles uses Django StaticFilesStorage so template rendering and automated tests do not require a pre-built hashed manifest. Production (DEBUG=False) retains WhiteNoise CompressedManifestStaticFilesStorage.
2. Account JSON export passes `ensure_ascii=False` inside `JsonResponse(json_dumps_params=...)`, where Django expects JSON encoder options.

After extracting the ZIP and activating the project's virtual environment, run:

```powershell
python -m pip install -r requirements.txt
python manage.py check
python manage.py test
```

For deployment with DEBUG=False, build static assets using `python manage.py collectstatic --noinput`.
