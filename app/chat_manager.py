from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.chat.models import ChatORM, ChatMessageORM
from app.models import Chat, ChatMessage, ChatHistoryResponse


class ChatNotFoundError(Exception):
    pass


class ChatManager:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.session_factory = session_factory
        self.temporary_chats: dict[str, Chat] = {}

    async def get_or_create(
        self,
        chat_id: str | None = None,
        temporary: bool = True,
    ) -> Chat:
        if chat_id is None:
            chat = Chat(
                chat_id=str(uuid4()),
                title="Новый чат",
                temporary=temporary,
            )

            if temporary:
                self.temporary_chats[chat.chat_id] = chat
            else:
                await self.save(chat)

            return chat

        if temporary:
            chat = self.temporary_chats.get(chat_id)
        else:
            chat = await self.get_persistent_chat(chat_id)

        if chat is None:
            raise ChatNotFoundError(f"Chat '{chat_id}' not found")

        return chat

    async def get_persistent_chat(
            self,
            chat_id: str,
            limit: int = 50,
            offset: int = 0,
    ) -> ChatHistoryResponse | None:
        async with self.session_factory() as session:
            chat_record = await session.get(ChatORM, chat_id)

            if chat_record is None:
                return None

            count_statement = (
                select(func.count())
                .select_from(ChatMessageORM)
                .where(ChatMessageORM.chat_id == chat_id)
            )
            total_messages = await session.scalar(count_statement) or 0

            # offset отсчитывается от конца истории:
            # 0 — самые новые сообщения, limit — размер страницы.
            end_position = total_messages - offset
            start_position = max(0, end_position - limit)

            statement = (
                select(ChatMessageORM)
                .where(
                    ChatMessageORM.chat_id == chat_id,
                    ChatMessageORM.position >= start_position,
                    ChatMessageORM.position < end_position,
                )
                .order_by(ChatMessageORM.position.asc())
            )

            records = (await session.scalars(statement)).all()

            has_more = start_position > 0

            return ChatHistoryResponse(
                chat_id=chat_record.chat_id,
                title=chat_record.title,
                messages=[
                    ChatMessage(
                        message_id=message.message_id,
                        role=message.role,
                        content=message.content,
                        name=message.name,
                        tool_call_id=message.tool_call_id,
                        tool_calls=message.tool_calls,
                        created_at=message.created_at,
                    )
                    for message in records
                ],
                total_messages=total_messages,
                next_offset=offset + len(records) if has_more else None,
                has_more=has_more,
            )

    async def create_persistent_chat(self, chat: Chat) -> None:
        if chat.temporary:
            raise ValueError("Chat must be persistent")

        async with self.session_factory() as session:
            exists = await session.get(ChatORM, chat.chat_id)

            if exists is not None:
                raise ValueError(f"Chat '{chat.chat_id}' already exists")

        await self.save(chat)

    async def save(self, chat: Chat) -> None:
        chat.updated_at = datetime.now(timezone.utc)

        if chat.temporary:
            self.temporary_chats[chat.chat_id] = chat
            return

        async with self.session_factory.begin() as session:
            record = await session.get(ChatORM, chat.chat_id)

            if record is None:
                record = ChatORM(
                    chat_id=chat.chat_id,
                    title=chat.title,
                    created_at=chat.created_at,
                    updated_at=chat.updated_at,
                )
                session.add(record)
                await session.flush()
            else:
                record.title = chat.title
                record.updated_at = chat.updated_at

            # Полностью заменяем историю текущим состоянием Chat.
            await session.execute(
                delete(ChatMessageORM).where(
                    ChatMessageORM.chat_id == chat.chat_id
                )
            )
            await session.flush()

            for position, message in enumerate(chat.messages):
                session.add(
                    ChatMessageORM(
                        message_id=message.message_id,
                        chat_id=chat.chat_id,
                        position=position,
                        role=message.role,
                        content=message.content,
                        name=message.name,
                        tool_call_id=message.tool_call_id,
                        tool_calls=message.tool_calls,
                        created_at=message.created_at,
                    )
                )

    async def delete(self, chat_id: str, temporary: bool) -> bool:
        if temporary:
            return self.temporary_chats.pop(chat_id, None) is not None

        async with self.session_factory.begin() as session:
            record = await session.get(ChatORM, chat_id)

            if record is None:
                return False

            await session.execute(
                delete(ChatMessageORM).where(
                    ChatMessageORM.chat_id == chat_id
                )
            )
            await session.delete(record)

        return True

    async def list_persistent_chats(
            self,
            limit: int = 50,
            offset: int = 0,
    ) -> list[dict]:
        """
        Получает список всех чатов
        :param limit: Количество загружаемых чатов
        :param offset: с какого начинать (для постепенной загрузки)
        :return: Список чатов
        """
        async with self.session_factory() as session:
            statement = (
                select(ChatORM)
                .order_by(ChatORM.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )

            records = (await session.scalars(statement)).all()

            return [
                {
                    "chat_id": record.chat_id,
                    "title": record.title,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                }
                for record in records
            ]
