import logging

import firebase_admin
from fastapi import HTTPException
from firebase_admin import credentials, firestore

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


def get_firebase_app() -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        settings = get_settings()
        if not all((settings.firebase_project_id, settings.firebase_client_email, settings.firebase_private_key)):
            raise HTTPException(status_code=503, detail="Firebase Admin credentials are not configured")
        try:
            credential = credentials.Certificate({
                "type": "service_account",
                "project_id": settings.firebase_project_id,
                "client_email": settings.firebase_client_email,
                "private_key": settings.firebase_private_key.replace("\\n", "\n"),
                "token_uri": "https://oauth2.googleapis.com/token",
            })
            options = {"projectId": settings.firebase_project_id}
            if settings.firebase_storage_bucket:
                options["storageBucket"] = settings.firebase_storage_bucket
            return firebase_admin.initialize_app(credential, options)
        except (ValueError, TypeError) as exc:
            logger.exception("Firebase Admin SDK initialization failed")
            raise HTTPException(status_code=503, detail="Firebase Admin SDK initialization failed") from exc


def get_firestore():
    return firestore.client(app=get_firebase_app())
