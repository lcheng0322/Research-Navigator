from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..schemas import user_schemas
from ..database.session import get_db
from ..models.user import User
from ..core.security import get_password_hash
from ..core.dependencies import get_current_active_user

router = APIRouter(
    prefix="/api/users",
    tags=["Users"],
)

@router.post("/", response_model=user_schemas.User)
def create_user(user: user_schemas.UserCreate, db: Session = Depends(get_db)):
    """
    Create a new user.
    """
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    db_user = User(email=user.email, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.get("/me", response_model=user_schemas.User)
def read_users_me(current_user: user_schemas.User = Depends(get_current_active_user)):
    """
    Get the current logged-in user's details.
    """
    return current_user

