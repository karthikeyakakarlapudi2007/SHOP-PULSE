from typing import Optional, List
from uuid import UUID
from sqlalchemy.orm import Session

from db.models.shop import Shop
from db.models.user import User
from db.models.shop_member import ShopMember, ShopRole
from schemas.shop_member import ShopMemberCreate, ShopMemberUpdate


def get_shop_member(db: Session, shop_id: UUID, user_id: UUID) -> Optional[ShopMember]:
    """Retrieve the membership of a user for a specific shop.
    
    If no explicit ShopMember row exists but the user is the recorded owner of the shop,
    bootstrap an OWNER membership row for seamless backward compatibility.
    """
    member = db.query(ShopMember).filter(
        ShopMember.shop_id == shop_id,
        ShopMember.user_id == user_id,
        ShopMember.is_active.is_(True)
    ).first()

    if member:
        return member

    # Fallback to Shop.owner_id
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if shop and shop.owner_id == user_id:
        # Check if an inactive or uncommitted record exists
        existing = db.query(ShopMember).filter(
            ShopMember.shop_id == shop_id,
            ShopMember.user_id == user_id
        ).first()
        if existing:
            existing.role = ShopRole.OWNER.value
            existing.is_active = True
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return existing
        else:
            new_member = ShopMember(
                shop_id=shop_id,
                user_id=user_id,
                role=ShopRole.OWNER.value,
                is_active=True
            )
            db.add(new_member)
            try:
                db.commit()
                db.refresh(new_member)
                return new_member
            except Exception:
                db.rollback()
                return db.query(ShopMember).filter(
                    ShopMember.shop_id == shop_id,
                    ShopMember.user_id == user_id
                ).first()

    return None


def list_shop_members(db: Session, shop_id: UUID) -> List[ShopMember]:
    # Ensure shop owner is bootstrapped in members
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if shop:
        get_shop_member(db, shop.id, shop.owner_id)

    return db.query(ShopMember).filter(
        ShopMember.shop_id == shop_id,
        ShopMember.is_active.is_(True)
    ).all()


def add_shop_member(
    db: Session,
    shop_id: UUID,
    acting_user_id: UUID,
    member_in: ShopMemberCreate
) -> ShopMember:
    acting_member = get_shop_member(db, shop_id, acting_user_id)
    if not acting_member or acting_member.role != ShopRole.OWNER.value:
        raise PermissionError("Only the shop owner can add or invite staff members.")

    requested_role = member_in.role.strip().upper()
    if requested_role not in [ShopRole.MANAGER.value, ShopRole.CASHIER.value]:
        raise ValueError("Staff role must be either MANAGER or CASHIER.")

    # Locate user by user_id or email
    target_user = None
    if member_in.user_id:
        target_user = db.query(User).filter(User.id == member_in.user_id).first()
    elif member_in.email:
        target_user = db.query(User).filter(User.email == member_in.email.strip().lower()).first()

    if not target_user:
        raise ValueError("Target user not found. User must register before being added to a shop.")

    if target_user.id == acting_user_id:
        raise ValueError("Shop owner already holds the highest authority and cannot change own role.")

    existing_membership = db.query(ShopMember).filter(
        ShopMember.shop_id == shop_id,
        ShopMember.user_id == target_user.id
    ).first()

    if existing_membership:
        existing_membership.role = requested_role
        existing_membership.is_active = True
        db.add(existing_membership)
        db.commit()
        db.refresh(existing_membership)
        return existing_membership

    new_membership = ShopMember(
        shop_id=shop_id,
        user_id=target_user.id,
        role=requested_role,
        is_active=True
    )
    db.add(new_membership)
    db.commit()
    db.refresh(new_membership)
    return new_membership


def update_shop_member(
    db: Session,
    shop_id: UUID,
    member_id: UUID,
    acting_user_id: UUID,
    member_in: ShopMemberUpdate
) -> ShopMember:
    acting_member = get_shop_member(db, shop_id, acting_user_id)
    if not acting_member or acting_member.role != ShopRole.OWNER.value:
        raise PermissionError("Only the shop owner can modify staff roles.")

    target = db.query(ShopMember).filter(
        ShopMember.id == member_id,
        ShopMember.shop_id == shop_id
    ).first()

    if not target:
        raise ValueError("Shop membership record not found.")

    if target.role == ShopRole.OWNER.value:
        raise ValueError("Cannot modify or demote shop owner.")

    if member_in.role is not None:
        new_role = member_in.role.strip().upper()
        if new_role not in [ShopRole.MANAGER.value, ShopRole.CASHIER.value]:
            raise ValueError("Role must be MANAGER or CASHIER.")
        target.role = new_role

    if member_in.is_active is not None:
        target.is_active = member_in.is_active

    db.add(target)
    db.commit()
    db.refresh(target)
    return target
