"""SQLite chat repository: detached reads and transactional, append-only writes."""
from datetime import datetime, timezone

from sqlalchemy import delete, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import lazyload

from app.db.chat.models import ChatORM, ChatMessageORM
from app.models import Chat, ChatMessage, ChatHistoryResponse


class ChatNotFoundError(Exception):
    pass


def message_from_record(record: ChatMessageORM) -> ChatMessage:
    return ChatMessage(
        message_id=record.message_id, role=record.role, content=record.content,
        name=record.name, tool_call_id=record.tool_call_id, tool_calls=record.tool_calls,
        created_at=record.created_at.replace(tzinfo=timezone.utc) if record.created_at.tzinfo is None else record.created_at)


def message_payload(message):
    return (message.role, message.content, message.name, message.tool_call_id, message.tool_calls)


class ChatManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.temporary_chats: dict[str, Chat] = {}

    async def get_or_create(self, chat_id: str | None = None, temporary: bool = True) -> Chat:
        if chat_id is None:
            chat = Chat(temporary=temporary)
            if temporary:
                await self.save(chat)
            else:
                await self.create_persistent_chat(chat)
            return chat
        if temporary:
            chat = self.temporary_chats.get(chat_id)
            if chat is None:
                raise ChatNotFoundError(f"Chat '{chat_id}' not found")
            return chat.model_copy(deep=True)
        async with self.session_factory() as session:
            await session.execute(text('BEGIN'))
            record = await session.get(ChatORM, chat_id, options=[lazyload(ChatORM.messages)])
            if record is None:
                raise ChatNotFoundError(f"Chat '{chat_id}' not found")
            messages = (await session.scalars(select(ChatMessageORM).where(
                ChatMessageORM.chat_id == chat_id).order_by(ChatMessageORM.position))).all()
            return Chat(chat_id=record.chat_id, title=record.title, temporary=False,
                        created_at=record.created_at, updated_at=record.updated_at,
                        messages=[message_from_record(message) for message in messages])

    async def get_persistent_chat(self, chat_id: str, limit: int = 50, offset: int = 0,
                                  before: int | None = None) -> ChatHistoryResponse | None:
        if not 1 <= limit <= 500 or offset < 0 or (before is not None and before < 0):
            raise ValueError('Invalid history pagination')
        if before is not None and offset:
            raise ValueError('Use before or offset, not both')
        async with self.session_factory() as session:
            await session.execute(text('BEGIN'))
            record = await session.get(ChatORM, chat_id, options=[lazyload(ChatORM.messages)])
            if record is None:
                return None
            total = await session.scalar(select(func.count()).select_from(ChatMessageORM).where(
                ChatMessageORM.chat_id == chat_id)) or 0
            end = max(0, total - offset) if before is None else min(total, before)
            start = max(0, end - limit)
            messages = (await session.scalars(select(ChatMessageORM).where(
                ChatMessageORM.chat_id == chat_id, ChatMessageORM.position >= start,
                ChatMessageORM.position < end).order_by(ChatMessageORM.position))).all()
            return ChatHistoryResponse(chat_id=record.chat_id, title=record.title,
                messages=[message_from_record(message) for message in messages], total_messages=total,
                next_offset=total - start if start else None, next_before=start if start else None,
                has_more=start > 0)

    async def create_persistent_chat(self, chat: Chat) -> None:
        if chat.temporary:
            raise ValueError('Chat must be persistent')
        await self._save_persistent(chat, create_only=True)

    async def save(self, chat: Chat) -> None:
        if not chat.temporary:
            await self._save_persistent(chat)
            return
        saved = self.temporary_chats.get(chat.chat_id)
        merged = saved.model_copy(deep=True) if saved else chat.model_copy(deep=True, update={'messages': []})
        known = {message.message_id: message for message in merged.messages}
        for message in chat.messages:
            previous = known.get(message.message_id)
            if previous is not None:
                if message_payload(previous) != message_payload(message):
                    raise ValueError('Existing messages are immutable')
                continue
            merged.messages.append(message.model_copy(deep=True))
            known[message.message_id] = message
        merged.title = chat.title
        merged.updated_at = datetime.now(timezone.utc)
        self.temporary_chats[chat.chat_id] = merged
        chat.updated_at = merged.updated_at

    async def _save_persistent(self, chat: Chat, create_only: bool = False) -> None:
        updated_at = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            # Reserve the SQLite writer BEFORE reading positions. This works across
            # managers/processes, unlike a per-instance asyncio.Lock. No LLM work
            # happens inside this short transaction. Context exit rolls back errors.
            await session.execute(text('BEGIN IMMEDIATE'))
            record = await session.get(ChatORM, chat.chat_id, options=[lazyload(ChatORM.messages)])
            if record is not None and create_only:
                raise ValueError(f"Chat '{chat.chat_id}' already exists")
            if record is None:
                record = ChatORM(chat_id=chat.chat_id, title=chat.title,
                                 created_at=chat.created_at, updated_at=updated_at)
                session.add(record)
                await session.flush()
            else:
                record.title = chat.title
                record.updated_at = updated_at
            records = (await session.scalars(select(ChatMessageORM).where(
                ChatMessageORM.chat_id == chat.chat_id))).all()
            known = {message.message_id: message for message in records}
            position = max((message.position for message in records), default=-1) + 1
            for message in chat.messages:
                previous = known.get(message.message_id)
                if previous is not None:
                    if message_payload(previous) != message_payload(message):
                        raise ValueError('Existing messages are immutable')
                    continue
                new_record = ChatMessageORM(message_id=message.message_id, chat_id=chat.chat_id,
                    position=position, role=message.role, content=message.content, name=message.name,
                    tool_call_id=message.tool_call_id, tool_calls=message.tool_calls, created_at=message.created_at)
                session.add(new_record)
                known[message.message_id] = new_record
                position += 1
            await session.commit()
        chat.updated_at = updated_at

    async def delete(self, chat_id: str, temporary: bool) -> bool:
        if temporary:
            return self.temporary_chats.pop(chat_id, None) is not None
        async with self.session_factory() as session:
            await session.execute(text('BEGIN IMMEDIATE'))
            record = await session.get(ChatORM, chat_id, options=[lazyload(ChatORM.messages)])
            if record is None:
                return False
            await session.execute(delete(ChatMessageORM).where(ChatMessageORM.chat_id == chat_id))
            await session.delete(record)
            await session.commit()
        return True

    async def list_persistent_chats(self, limit: int = 50, offset: int = 0) -> list[dict]:
        async with self.session_factory() as session:
            records = (await session.scalars(select(ChatORM).options(lazyload(ChatORM.messages))
                .order_by(ChatORM.updated_at.desc(), ChatORM.chat_id).limit(limit).offset(offset))).all()
            return [{'chat_id': record.chat_id, 'title': record.title,
                     'created_at': record.created_at, 'updated_at': record.updated_at} for record in records]
