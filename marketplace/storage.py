"""Storage for documents that must not be exposed through public media URLs."""
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateUploadStorage(FileSystemStorage):
    """Keep uploaded proofs outside MEDIA_ROOT and deny automatic public URLs."""

    def __init__(self):
        super().__init__(location=settings.BASE_DIR / "private_uploads")

    def url(self, name):
        raise ValueError("This file is private and must be served through an authorized view.")
