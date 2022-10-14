from typing import List

from sqlalchemy import insert, update, delete
from sqlalchemy.future import select

from db.crud.abstract import DalABC
from models.roles import Roles
from schemas.roles import RoleCreateUpdateRequestSchema


class RolesDAL(DalABC):
    async def list(self) -> List[Roles]:
        q = select(Roles)

        result = await self.session.execute(q)
        return result.scalars().all()

    async def insert(self, role: RoleCreateUpdateRequestSchema):
        data = role.dict()
        del data['permissions']
        q = insert(Roles).values(**data)

        result = await self.session.execute(q)
        return result

    async def get(self, role_id: int):
        q = select(Roles) \
            .where(Roles.id == role_id)

        result = await self.session.execute(q)

        return result.scalars().first()

    async def update(self, role_id: int, role: RoleCreateUpdateRequestSchema) -> None:
        data = role.dict()
        del data['permissions']

        q = update(Roles) \
            .where(Roles.id == role_id) \
            .values(**data) \
            .execution_options(synchronize_session="fetch")

        await self.session.execute(q)

    async def delete(self, role_id: int) -> None:
        q = delete(Roles) \
            .where(Roles.id == role_id) \
            .execution_options(synchronize_session="fetch")

        await self.session.execute(q)