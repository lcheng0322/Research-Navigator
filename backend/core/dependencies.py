from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ..schemas import user_schemas
from ..core.config import settings
from ..database.session import get_db
from ..models.user import User

# This tells FastAPI where to look for the token.
# The tokenUrl should point to our login endpoint.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")

def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    """
    Dependency to get the current user from a JWT token.

    This function will be used to protect routes that require authentication.
    It decodes the token, validates its signature and expiration, and fetches
    the user from the database.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub") 
        if email is None:
            raise credentials_exception
        token_data = user_schemas.TokenData(email=email)
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.email == token_data.email).first()
    if user is None:
        raise credentials_exception
    return user

def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency to get the current active user.

    Builds on top of get_current_user to ensure the user is active.
    This is useful for endpoints that should not be accessible to disabled users.
    """
    if not getattr(current_user, 'is_active', True):
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user
