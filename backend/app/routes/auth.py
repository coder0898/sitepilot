from fastapi import APIRouter

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/provider")
def provider():
    return {
        "provider": "supabase",
        "passwords_stored_by_siteops": False,
        "recovery": "google_oauth",
    }