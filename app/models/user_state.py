import enum
from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy import String, DateTime, JSON
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class StateEnum(str, enum.Enum):
    WAITING_INPUT = "WAITING_INPUT"
    WAITING_PAYER = "WAITING_PAYER"
    WAITING_SPLIT_MODE = "WAITING_SPLIT_MODE"
    WAITING_CUSTOM_SPLIT = "WAITING_CUSTOM_SPLIT"


class UserState(Base):
    __tablename__ = "user_states"

    line_user_id: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )
    state: Mapped[StateEnum] = mapped_column(
        SAEnum(StateEnum), nullable=False, default=StateEnum.WAITING_INPUT
    )
    # Stores pending expense data: {description, amount} while awaiting split choice
    pending_data: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<UserState {self.line_user_id} state={self.state}>"
