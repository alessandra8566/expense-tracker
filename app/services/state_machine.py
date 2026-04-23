"""
State machine — reads/writes user_states table and drives conversation flow.
"""
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_state import UserState, StateEnum


class StateMachineService:

    @staticmethod
    async def get_state(db: AsyncSession, line_user_id: str) -> UserState:
        """Return existing UserState or create a fresh one."""
        result = await db.execute(
            select(UserState).where(UserState.line_user_id == line_user_id)
        )
        user_state = result.scalar_one_or_none()
        if user_state is None:
            user_state = UserState(
                line_user_id=line_user_id,
                state=StateEnum.WAITING_INPUT,
                pending_data=None,
            )
            db.add(user_state)
            await db.flush()
        return user_state

    @staticmethod
    async def transition(
        db: AsyncSession,
        line_user_id: str,
        new_state: StateEnum,
        pending_data: Optional[Any] = None,
    ) -> UserState:
        """Move a user to a new state, optionally storing pending data."""
        user_state = await StateMachineService.get_state(db, line_user_id)
        user_state.state = new_state
        user_state.pending_data = pending_data
        user_state.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return user_state

    @staticmethod
    async def reset(db: AsyncSession, line_user_id: str) -> UserState:
        """Return user to idle (WAITING_INPUT) and clear pending data."""
        return await StateMachineService.transition(
            db, line_user_id, StateEnum.WAITING_INPUT, None
        )
