import uuid
from typing import Generator, Optional, List, Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from pydantic import ValidationError
from sqlalchemy.orm import Session

from core.config import settings
from db.session import SessionLocal
from db.models.user import User
from db.models.shop import Shop
from db.models.shop_member import ShopMember, ShopRole
from schemas.token import TokenPayload
from services import shop_member as shop_member_service

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(reusable_oauth2)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        user_uuid = uuid.UUID(user_id)
        token_data = TokenPayload(sub=str(user_uuid))
    except (jwt.PyJWTError, ValidationError, ValueError, TypeError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return user


def get_user_accessible_shop(db: Session, user: User) -> Optional[Shop]:
    """Find the shop accessible to the user: either owned by the user, or where user is an active member."""
    # First priority: direct ownership
    shop = db.query(Shop).filter(Shop.owner_id == user.id).first()
    if shop:
        return shop

    # Second priority: staff membership
    membership = db.query(ShopMember).filter(
        ShopMember.user_id == user.id,
        ShopMember.is_active.is_(True)
    ).first()
    if membership:
        return db.query(Shop).filter(Shop.id == membership.shop_id).first()

    return None


def get_current_shop_member(
    shop_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShopMember:
    """Fetch shop membership for current user, returning 403 if user is not a member of the shop."""
    member = shop_member_service.get_shop_member(db, shop_id=shop_id, user_id=current_user.id)
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an authorized member of this shop."
        )
    return member


def require_shop_roles(allowed_roles: List[str]) -> Callable:
    """Factory dependency ensuring current user holds one of the specified roles in the shop."""
    def role_checker(
        shop_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> ShopMember:
        member = shop_member_service.get_shop_member(db, shop_id=shop_id, user_id=current_user.id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not an authorized member of this shop."
            )
        if member.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires elevated role ({', '.join(allowed_roles)}). Current role: {member.role}."
            )
        return member
    return role_checker


def get_current_shop_and_role(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> tuple[Shop, ShopMember]:
    """Fetch the active shop and the user's membership for the shop.
    Returns 400 if user has no shop profile, or 403 if user is not an active authorized member."""
    shop = get_user_accessible_shop(db, current_user)
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must create a shop profile or join an existing shop first."
        )
    member = shop_member_service.get_shop_member(db, shop_id=shop.id, user_id=current_user.id)
    if not member or not member.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an authorized active member of this shop."
        )
    return shop, member


def require_roles(allowed_roles: List[str]) -> Callable:
    """Dependency factory ensuring current user holds one of allowed_roles in their accessible shop."""
    def role_checker(
        shop_and_member: tuple[Shop, ShopMember] = Depends(get_current_shop_and_role)
    ) -> tuple[Shop, ShopMember]:
        shop, member = shop_and_member
        if member.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires elevated role ({', '.join(allowed_roles)}). Current role: {member.role}."
            )
        return shop, member
    return role_checker
