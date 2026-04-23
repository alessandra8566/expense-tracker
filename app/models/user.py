import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    line_user_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default="Unknown"
    )
    partner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    invite_code: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, unique=True, index=True
    )
    invite_code_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    partner: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[partner_id], remote_side="User.id", uselist=False
    )
    expenses_paid: Mapped[List["Expense"]] = relationship(
        "Expense", back_populates="payer", foreign_keys="Expense.payer_id"
    )

    def __repr__(self) -> str:
        return f"<User line_user_id={self.line_user_id} display_name={self.display_name}>"
