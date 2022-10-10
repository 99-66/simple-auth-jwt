from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from models.token import Token
from schemas.token import InsertTokenSchema


class RefreshTokenDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def exists_by_user_id(self, user_id: int) -> bool:
        """
        사용자 refreshToken이 존재하는지 조회한다
        """
        exists_criteria = (
            select(Token.user_id).
            where(Token.user_id == user_id).
            exists()
        )
        q = select(Token.user_id).where(exists_criteria)
        result = await self.session.execute(q)

        return bool(result.all())

    async def delete_by_user_id(self, user_id: int) -> None:
        """
        사용자의 refreshToken을 삭제한다
        """
        q = delete(Token) \
            .where(Token.user_id == user_id) \
            .execution_options(synchronize_session="fetch")

        await self.session.execute(q)

    async def insert(self, refresh_token: InsertTokenSchema):
        q = insert(Token).values(**refresh_token.dict())

        await self.session.execute(q)