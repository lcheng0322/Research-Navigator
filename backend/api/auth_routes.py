from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..schemas import user_schemas
from ..database.session import get_db
from ..models.user import User
from ..core.security import verify_password, create_access_token
from ..core.cache import redis_client
from ..core.config import settings

router = APIRouter(
    prefix="/api",
    tags=["Authentication"],
)

@router.post("/token", response_model=user_schemas.Token)
async def login_for_access_token(
    request: Request,
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    # --- Rate Limiting (per IP, per minute) ---
    try:
        client_ip = (request.client.host if request and request.client else "unknown")
        rl_key = f"ratelimit:login:{client_ip}"
        count = await redis_client.incr(rl_key)
        if count == 1:
            # Set window to 60 seconds for the first hit
            await redis_client.expire(rl_key, 60)
        if count and int(count) > settings.LOGIN_RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")
    except Exception:
        # Fallback: do not block login if Redis is unavailable
        pass

    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, str(user.hashed_password)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(
        data={"sub": user.email}
    )
    return {"access_token": access_token, "token_type": "bearer"}
