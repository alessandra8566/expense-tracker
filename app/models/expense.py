import uuid
import enum
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, DateTime, Numeric, ForeignKey, Boolean
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class SplitMode(str, enum.Enum):
    AA = "AA"
    CUSTOM = "CUSTOM"


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    payer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # partner_id: the other user at time of recording
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    split_mode: Mapped[SplitMode] = mapped_column(SAEnum(SplitMode), nullable=False)
    # How much of the total amount the payer is responsible for
    payer_share: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # How much of the total amount the partner is responsible for
    partner_share: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_settled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    payer: Mapped["User"] = relationship(
        "User", back_populates="expenses_paid", foreign_keys=[payer_id]
    )

    def __repr__(self) -> str:
        return f"<Expense {self.description} {self.amount}>"
