import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_maker
from models.assistant_session import AssistantSession
from models.assistant_session_message import AssistantSessionMessage
from models.user import User
from schemas.assistant import (
    AssistantChatResponse,
    AssistantHistoryResponse,
    AssistantMessageResponse,
    AssistantSessionListResponse,
    AssistantSessionResponse,
)
from services.advisor_service import AdvisorService
from services.portfolio_service import PortfolioService
from utils.timezone import now_in_shanghai, now_in_utc_naive


class AssistantService:
    """投资助手服务"""

    HISTORY_LIMIT = 20
    MEMORY_WINDOW = 12
    LLM_MAX_ATTEMPTS = 3
    STREAM_POLL_SECONDS = 0.8
    _stream_subscribers: dict[str, set[asyncio.Queue[dict]]] = {}
    @staticmethod
    def normalize_response(text: str) -> str:
        """清洗模型返回，避免把 JSON 包装直接展示给前端"""
        content = text.strip()
        if not content:
            return "我暂时没有生成有效回复，请稍后重试。"

        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                for key in ("response", "answer", "content", "message"):
                    value = parsed.get(key)
                    if isinstance(value, str) and value.strip():
                        content = value.strip()
                        break
        except json.JSONDecodeError:
            pass

        if content.startswith("```") and content.endswith("```"):
            lines = content.splitlines()
            if len(lines) >= 3:
                content = "\n".join(lines[1:-1]).strip()

        return content.replace("\\n", "\n").strip()

    @staticmethod
    def iter_response_chunks(text: str) -> list[str]:
        """将完整回复切成适合前端渐进渲染的片段"""
        normalized = text.replace("\r\n", "\n").strip()
        if not normalized:
            return []

        chunks: list[str] = []
        for paragraph in normalized.split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if len(paragraph) <= 80:
                chunks.append(paragraph + "\n\n")
                continue

            current = ""
            for char in paragraph:
                current += char
                if char in "。！？\n" and len(current.strip()) >= 24:
                    chunks.append(current)
                    current = ""
            if current.strip():
                chunks.append(current)
            chunks.append("\n\n")

        if chunks and chunks[-1] == "\n\n":
            chunks.pop()
        return chunks

    @classmethod
    async def stream_and_collect_response(
        cls,
        llm,
        prompt: str,
        context: str = "assistant_stream",
    ) -> AsyncIterator[tuple[str, str | None]]:
        """优先使用原生流式，必要时降级或缓冲清洗"""
        raw_parts: list[str] = []
        buffered_prefix = ""
        mode = "pending"
        started_at = time.perf_counter()
        first_raw_at: float | None = None
        first_emit_at: float | None = None
        phase_searching_sent = False

        print(f"[AssistantStreamTiming] context={context} event=request_start", flush=True)

        async for event in AdvisorService.chat_stream_events_with_logging(llm, prompt, context):
            if event.get("type") == "phase":
                phase = event.get("phase")
                if phase == "searching" and not phase_searching_sent:
                    phase_searching_sent = True
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    print(
                        f"[AssistantStreamTiming] context={context} event=phase phase=searching elapsed_ms={elapsed_ms} detail={event.get('detail')}",
                        flush=True,
                    )
                    yield "phase", "searching"
                continue

            if event.get("type") != "text":
                continue

            raw_chunk = event.get("content")
            if not isinstance(raw_chunk, str) or not raw_chunk:
                continue

            if first_raw_at is None:
                first_raw_at = time.perf_counter()
                preview = raw_chunk[:80].replace("\n", "\\n")
                print(
                    f"[AssistantStreamTiming] context={context} event=first_raw_chunk elapsed_ms={int((first_raw_at - started_at) * 1000)} preview={preview!r}",
                    flush=True,
                )

            raw_parts.append(raw_chunk)

            if mode == "pending":
                buffered_prefix += raw_chunk
                stripped = buffered_prefix.lstrip()
                if not stripped:
                    continue
                if stripped.startswith("{") or stripped.startswith("```"):
                    mode = "buffered"
                    print(
                        f"[AssistantStreamTiming] context={context} event=mode_decided mode=buffered elapsed_ms={int((time.perf_counter() - started_at) * 1000)}",
                        flush=True,
                    )
                    continue

                mode = "direct"
                print(
                    f"[AssistantStreamTiming] context={context} event=mode_decided mode=direct elapsed_ms={int((time.perf_counter() - started_at) * 1000)}",
                    flush=True,
                )
                if first_emit_at is None:
                    first_emit_at = time.perf_counter()
                    print(
                        f"[AssistantStreamTiming] context={context} event=first_client_chunk elapsed_ms={int((first_emit_at - started_at) * 1000)} mode={mode}",
                        flush=True,
                    )
                    yield "phase", "generating"
                yield "chunk", buffered_prefix
                buffered_prefix = ""
                continue

            if mode == "direct":
                if first_emit_at is None:
                    first_emit_at = time.perf_counter()
                    print(
                        f"[AssistantStreamTiming] context={context} event=first_client_chunk elapsed_ms={int((first_emit_at - started_at) * 1000)} mode={mode}",
                        flush=True,
                    )
                    yield "phase", "generating"
                yield "chunk", raw_chunk

        final_text = cls.normalize_response("".join(raw_parts))

        if mode in {"pending", "buffered"}:
            for chunk in cls.iter_response_chunks(final_text):
                if first_emit_at is None:
                    first_emit_at = time.perf_counter()
                    print(
                        f"[AssistantStreamTiming] context={context} event=first_client_chunk elapsed_ms={int((first_emit_at - started_at) * 1000)} mode={mode}",
                        flush=True,
                    )
                    yield "phase", "generating"
                yield "chunk", chunk

        print(
            f"[AssistantStreamTiming] context={context} event=done elapsed_ms={int((time.perf_counter() - started_at) * 1000)} mode={mode} raw_chars={len(''.join(raw_parts))} final_chars={len(final_text)}",
            flush=True,
        )
        yield "done", final_text

    @classmethod
    async def chat_with_retry(cls, llm, prompt: str, context: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, cls.LLM_MAX_ATTEMPTS + 1):
            retry_context = context if attempt == 1 else f"{context}:retry:{attempt}"
            try:
                if attempt > 1:
                    print(f"[Assistant] LLM调用失败后重试: {retry_context}", flush=True)
                return await AdvisorService.chat_with_logging(llm, prompt, context=retry_context)
            except Exception as exc:
                last_error = exc
                if attempt >= cls.LLM_MAX_ATTEMPTS:
                    break
                print(
                    f"[Assistant] LLM调用失败，准备第 {attempt + 1}/{cls.LLM_MAX_ATTEMPTS} 次尝试: {type(exc).__name__}: {exc}",
                    flush=True,
                )
        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM调用失败")

    @classmethod
    async def stream_and_collect_response_with_retry(
        cls,
        llm,
        prompt: str,
        context: str = "assistant_stream",
    ) -> AsyncIterator[tuple[str, str | None]]:
        last_error: Exception | None = None
        for attempt in range(1, cls.LLM_MAX_ATTEMPTS + 1):
            emitted_chunk = False
            retry_context = context if attempt == 1 else f"{context}:retry:{attempt}"
            try:
                if attempt > 1:
                    print(f"[Assistant] 流式LLM调用失败后重试: {retry_context}", flush=True)
                async for event_type, payload in cls.stream_and_collect_response(llm, prompt, retry_context):
                    if event_type == "chunk" and payload:
                        emitted_chunk = True
                    yield event_type, payload
                return
            except Exception as exc:
                last_error = exc
                if emitted_chunk or attempt >= cls.LLM_MAX_ATTEMPTS:
                    break
                print(
                    f"[Assistant] 流式LLM调用失败，准备第 {attempt + 1}/{cls.LLM_MAX_ATTEMPTS} 次尝试: {type(exc).__name__}: {exc}",
                    flush=True,
                )
        if last_error is not None:
            raise last_error
        raise RuntimeError("流式LLM调用失败")

    @staticmethod
    def build_session_title(message: str) -> str:
        title = " ".join(message.strip().split())
        return (title[:24] + "...") if len(title) > 24 else (title or "新会话")

    @staticmethod
    def build_preview(message: str) -> str:
        preview = " ".join(message.strip().split())
        return (preview[:80] + "...") if len(preview) > 80 else preview

    @classmethod
    async def list_sessions(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> AssistantSessionListResponse:
        result = await session.execute(
            select(AssistantSession)
            .where(AssistantSession.user_id == user_id)
            .order_by(AssistantSession.updated_at.desc(), AssistantSession.id.desc())
        )
        sessions = result.scalars().all()
        return AssistantSessionListResponse(
            sessions=[AssistantSessionResponse.model_validate(item) for item in sessions]
        )

    @classmethod
    async def create_session(
        cls,
        session: AsyncSession,
        user_id: int,
        title: str | None = None,
    ) -> AssistantSessionResponse:
        conversation = AssistantSession(
            user_id=user_id,
            title=(title or "新会话")[:120],
        )
        session.add(conversation)
        await session.flush()
        return AssistantSessionResponse.model_validate(conversation)

    @classmethod
    async def get_or_create_session(
        cls,
        session: AsyncSession,
        user_id: int,
        session_id: int | None,
    ) -> AssistantSession:
        if session_id is not None:
            conversation = await session.get(AssistantSession, session_id)
            if conversation and conversation.user_id == user_id:
                return conversation
            raise ValueError("session not found")

        result = await session.execute(
            select(AssistantSession)
            .where(AssistantSession.user_id == user_id)
            .order_by(AssistantSession.updated_at.desc(), AssistantSession.id.desc())
            .limit(1)
        )
        conversation = result.scalar_one_or_none()
        if conversation:
            return conversation

        created = AssistantSession(user_id=user_id, title="新会话")
        session.add(created)
        await session.flush()
        return created

    @classmethod
    async def get_history(
        cls,
        session: AsyncSession,
        user_id: int,
        session_id: int | None = None,
        limit: int = HISTORY_LIMIT,
    ) -> AssistantHistoryResponse:
        conversation = await cls.get_or_create_session(session, user_id, session_id)
        result = await session.execute(
            select(AssistantSessionMessage)
            .where(AssistantSessionMessage.user_id == user_id, AssistantSessionMessage.session_id == conversation.id)
            .order_by(AssistantSessionMessage.created_at.desc(), AssistantSessionMessage.id.desc())
            .limit(limit)
        )
        messages = list(reversed(result.scalars().all()))
        return AssistantHistoryResponse(
            session=AssistantSessionResponse.model_validate(conversation),
            messages=[AssistantMessageResponse.model_validate(message) for message in messages]
        )

    @classmethod
    async def delete_session(cls, session: AsyncSession, user_id: int, session_id: int) -> int:
        conversation = await cls.get_or_create_session(session, user_id, session_id)
        await session.execute(
            delete(AssistantSessionMessage).where(AssistantSessionMessage.session_id == conversation.id)
        )
        result = await session.execute(
            delete(AssistantSession).where(AssistantSession.id == conversation.id, AssistantSession.user_id == user_id)
        )
        return result.rowcount or 0

    @classmethod
    async def touch_session(
        cls,
        conversation: AssistantSession,
        message: str,
        set_title: bool = False,
    ) -> None:
        conversation.updated_at = now_in_utc_naive()
        conversation.last_message_preview = cls.build_preview(message)
        if set_title and (not conversation.title or conversation.title == "新会话"):
            conversation.title = cls.build_session_title(message)

    @classmethod
    async def prepare_user_message(
        cls,
        session: AsyncSession,
        user_id: int,
        session_id: int | None,
        message: str,
        retry_message_id: int | None = None,
        include_portfolio_context: bool = True,
        portfolio_ids: Sequence[int] | None = None,
    ) -> tuple[AssistantSession, AssistantSessionMessage, str]:
        clean_message = message.strip()
        if not clean_message:
            raise ValueError("message cannot be empty")

        conversation = await cls.get_or_create_session(session, user_id, session_id)
        if retry_message_id is not None:
            user_message = await session.get(AssistantSessionMessage, retry_message_id)
            if (
                not user_message
                or user_message.user_id != user_id
                or user_message.session_id != conversation.id
                or user_message.role != "user"
            ):
                raise ValueError("retry message not found")

            clean_message = user_message.content.strip()
            await session.execute(
                delete(AssistantSessionMessage).where(
                    AssistantSessionMessage.user_id == user_id,
                    AssistantSessionMessage.session_id == conversation.id,
                    AssistantSessionMessage.id > user_message.id,
                )
            )
            prompt = await cls.build_prompt(
                session,
                user_id,
                conversation.id,
                clean_message,
                before_message_id=user_message.id,
                include_portfolio_context=include_portfolio_context,
                portfolio_ids=portfolio_ids,
            )
            await cls.touch_session(conversation, clean_message, set_title=False)
            return conversation, user_message, prompt

        user_message = AssistantSessionMessage(
            session_id=conversation.id,
            user_id=user_id,
            role="user",
            content=clean_message,
        )
        session.add(user_message)
        await session.flush()
        await cls.touch_session(conversation, clean_message, set_title=True)
        prompt = await cls.build_prompt(
            session,
            user_id,
            conversation.id,
            clean_message,
            include_portfolio_context=include_portfolio_context,
            portfolio_ids=portfolio_ids,
        )
        return conversation, user_message, prompt

    @classmethod
    async def chat(
        cls,
        session: AsyncSession,
        user_id: int,
        session_id: int | None,
        message: str,
        retry_message_id: int | None = None,
        include_portfolio_context: bool = True,
        portfolio_ids: Sequence[int] | None = None,
    ) -> AssistantChatResponse:
        conversation, user_message, prompt = await cls.prepare_user_message(
            session,
            user_id,
            session_id,
            message,
            retry_message_id=retry_message_id,
            include_portfolio_context=include_portfolio_context,
            portfolio_ids=portfolio_ids,
        )
        llm = AdvisorService.get_llm_client()
        prompt = await AdvisorService.enrich_prompt_with_tavily_tools(
            llm,
            prompt,
            context=f"assistant_chat:session:{conversation.id}",
            max_calls=3,
        )

        try:
            reply_text = cls.normalize_response(
                await cls.chat_with_retry(
                    llm,
                    prompt,
                    context=f"assistant_chat:session:{conversation.id}",
                )
            )
        except Exception as exc:
            reply_text = f"当前智能体暂时不可用，请稍后重试。错误信息：{exc}"

        assistant_message = AssistantSessionMessage(
            session_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content=reply_text,
        )
        session.add(assistant_message)
        await session.flush()
        await cls.touch_session(conversation, reply_text)

        return AssistantChatResponse(
            session=AssistantSessionResponse.model_validate(conversation),
            user_message=AssistantMessageResponse.model_validate(user_message),
            assistant_message=AssistantMessageResponse.model_validate(assistant_message),
        )

    @classmethod
    async def _publish_stream_event(cls, run_id: str | None, event: dict) -> None:
        if not run_id:
            return
        for queue in list(cls._stream_subscribers.get(run_id, set())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    @classmethod
    async def _run_stream_generation(
        cls,
        run_id: str,
        assistant_message_id: int,
        conversation_id: int,
        user_id: int,
        prompt: str,
    ) -> None:
        llm = AdvisorService.get_llm_client()
        final_text = ""
        status = "done"
        started_at = time.perf_counter()
        phase = "preparing"
        print(f"[AssistantStreamTiming] context=assistant_stream:session:{conversation_id}:run:{run_id} event=background_start", flush=True)
        await cls._publish_stream_event(run_id, {"event": "phase", "phase": "preparing"})
        try:
            phase = "calling_model"
            await cls._publish_stream_event(run_id, {"event": "phase", "phase": "calling_model"})
            async for event_type, payload in cls.stream_and_collect_response_with_retry(
                llm,
                prompt,
                context=f"assistant_stream:session:{conversation_id}:run:{run_id}",
            ):
                if event_type == "phase" and payload:
                    phase = payload
                    await cls._publish_stream_event(run_id, {"event": "phase", "phase": payload})
                    continue
                if event_type == "chunk" and payload:
                    final_text += payload
                    async with async_session_maker() as update_session:
                        assistant_message = await update_session.get(AssistantSessionMessage, assistant_message_id)
                        conversation = await update_session.get(AssistantSession, conversation_id)
                        if not assistant_message or assistant_message.user_id != user_id:
                            return
                        assistant_message.content = final_text
                        assistant_message.status = "streaming"
                        if conversation:
                            await cls.touch_session(conversation, final_text or "助手正在生成回复...")
                        await update_session.commit()
                    await cls._publish_stream_event(run_id, {"event": "chunk", "content": payload})
                if event_type == "done" and payload is not None:
                    final_text = payload
        except Exception as exc:
            final_text = f"当前智能体暂时不可用，请稍后重试。错误信息：{exc}"
            status = "error"
            print(
                f"[AssistantStreamTiming] context=assistant_stream:session:{conversation_id}:run:{run_id} event=error elapsed_ms={int((time.perf_counter() - started_at) * 1000)} phase={phase} error={type(exc).__name__}: {exc}",
                flush=True,
            )
            async with async_session_maker() as update_session:
                assistant_message = await update_session.get(AssistantSessionMessage, assistant_message_id)
                conversation = await update_session.get(AssistantSession, conversation_id)
                if assistant_message and assistant_message.user_id == user_id:
                    assistant_message.content = final_text
                    assistant_message.status = status
                    if conversation:
                        await cls.touch_session(conversation, final_text)
                    await update_session.commit()
            await cls._publish_stream_event(run_id, {"event": "chunk", "content": final_text})
        finally:
            async with async_session_maker() as update_session:
                assistant_message = await update_session.get(AssistantSessionMessage, assistant_message_id)
                conversation = await update_session.get(AssistantSession, conversation_id)
                if assistant_message and assistant_message.user_id == user_id:
                    assistant_message.content = final_text or assistant_message.content or "我暂时没有生成有效回复，请稍后重试。"
                    assistant_message.status = status
                    if conversation:
                        await cls.touch_session(conversation, assistant_message.content)
                    await update_session.commit()
                    payload = {
                        "assistant_message": AssistantMessageResponse.model_validate(assistant_message).model_dump(mode="json"),
                        "session_id": conversation_id,
                    }
                    print(
                        f"[AssistantStreamTiming] context=assistant_stream:session:{conversation_id}:run:{run_id} event=background_done elapsed_ms={int((time.perf_counter() - started_at) * 1000)} status={status} final_chars={len(assistant_message.content or '')}",
                        flush=True,
                    )
                    await cls._publish_stream_event(run_id, {"event": "done", "payload": payload})

    @classmethod
    async def subscribe_stream(
        cls,
        session: AsyncSession,
        user_id: int,
        message_id: int,
    ) -> AsyncIterator[str]:
        assistant_message = await session.get(AssistantSessionMessage, message_id)
        if not assistant_message or assistant_message.user_id != user_id or assistant_message.role != "assistant":
            raise ValueError("assistant message not found")

        yield f"event: snapshot\ndata: {json.dumps({'assistant_message': AssistantMessageResponse.model_validate(assistant_message).model_dump(mode='json')}, ensure_ascii=False)}\n\n"
        if assistant_message.status == "streaming" and not (assistant_message.content or ""):
            yield f"event: phase\ndata: {json.dumps({'phase': 'calling_model'}, ensure_ascii=False)}\n\n"
        if assistant_message.status != "streaming" or not assistant_message.run_id:
            yield f"event: done\ndata: {json.dumps({'assistant_message': AssistantMessageResponse.model_validate(assistant_message).model_dump(mode='json'), 'session_id': assistant_message.session_id}, ensure_ascii=False)}\n\n"
            return

        run_id = assistant_message.run_id
        last_content = assistant_message.content or ""
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)
        cls._stream_subscribers.setdefault(run_id, set()).add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=cls.STREAM_POLL_SECONDS)
                except asyncio.TimeoutError:
                    await session.refresh(assistant_message)
                    next_content = assistant_message.content or ""
                    if len(next_content) > len(last_content):
                        delta = next_content[len(last_content):]
                        last_content = next_content
                        yield f"event: chunk\ndata: {json.dumps({'content': delta}, ensure_ascii=False)}\n\n"
                    if assistant_message.status != "streaming":
                        yield f"event: done\ndata: {json.dumps({'assistant_message': AssistantMessageResponse.model_validate(assistant_message).model_dump(mode='json'), 'session_id': assistant_message.session_id}, ensure_ascii=False)}\n\n"
                        break
                    continue

                if event.get("event") == "phase":
                    phase = str(event.get("phase") or "")
                    if phase:
                        yield f"event: phase\ndata: {json.dumps({'phase': phase}, ensure_ascii=False)}\n\n"
                if event.get("event") == "chunk":
                    content = str(event.get("content") or "")
                    if content:
                        last_content += content
                        yield f"event: chunk\ndata: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
                if event.get("event") == "done":
                    payload = event.get("payload") or {}
                    if "assistant_message" not in payload:
                        await session.refresh(assistant_message)
                        payload = {"assistant_message": AssistantMessageResponse.model_validate(assistant_message).model_dump(mode='json'), "session_id": assistant_message.session_id}
                    yield f"event: done\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    break
        finally:
            subscribers = cls._stream_subscribers.get(run_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    cls._stream_subscribers.pop(run_id, None)

    @classmethod
    async def chat_stream(
        cls,
        session: AsyncSession,
        user_id: int,
        session_id: int | None,
        message: str,
        retry_message_id: int | None = None,
        include_portfolio_context: bool = True,
        portfolio_ids: Sequence[int] | None = None,
    ) -> tuple[None, AsyncIterator[str]]:
        conversation, user_message, prompt = await cls.prepare_user_message(
            session,
            user_id,
            session_id,
            message,
            retry_message_id=retry_message_id,
            include_portfolio_context=include_portfolio_context,
            portfolio_ids=portfolio_ids,
        )
        llm = AdvisorService.get_llm_client()
        prompt = await AdvisorService.enrich_prompt_with_tavily_tools(
            llm,
            prompt,
            context=f"assistant_stream:session:{conversation.id}",
            max_calls=3,
        )
        run_id = uuid.uuid4().hex
        assistant_message = AssistantSessionMessage(
            session_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content="",
            status="streaming",
            run_id=run_id,
        )
        session.add(assistant_message)
        await session.flush()
        await session.commit()

        assistant_message_id = assistant_message.id
        conversation_id = conversation.id
        asyncio.create_task(cls._run_stream_generation(run_id, assistant_message_id, conversation_id, user_id, prompt))

        async def event_stream() -> AsyncIterator[str]:
            yield f"event: meta\ndata: {json.dumps({'session': AssistantSessionResponse.model_validate(conversation).model_dump(mode='json'), 'user_message': AssistantMessageResponse.model_validate(user_message).model_dump(mode='json'), 'assistant_message': AssistantMessageResponse.model_validate(assistant_message).model_dump(mode='json')}, ensure_ascii=False)}\n\n"
            async for event in cls.subscribe_stream(session, user_id, assistant_message_id):
                yield event

        return None, event_stream()

    @classmethod
    async def build_prompt(
        cls,
        session: AsyncSession,
        user_id: int,
        session_id: int,
        latest_user_message: str,
        before_message_id: int | None = None,
        include_portfolio_context: bool = True,
        portfolio_ids: Sequence[int] | None = None,
    ) -> str:
        user = await session.get(User, user_id)

        history_result = await session.execute(
            select(AssistantSessionMessage)
            .where(
                AssistantSessionMessage.user_id == user_id,
                AssistantSessionMessage.session_id == session_id,
                *(
                    [AssistantSessionMessage.id < before_message_id]
                    if before_message_id is not None
                    else []
                ),
            )
            .order_by(AssistantSessionMessage.created_at.desc(), AssistantSessionMessage.id.desc())
            .limit(cls.MEMORY_WINDOW)
        )
        history_messages = list(reversed(history_result.scalars().all()))

        history_text = "\n".join(
            f"{'用户' if item.role == 'user' else '助手'}: {item.content}"
            for item in history_messages
        ) or "暂无历史对话。"
        current_time = now_in_shanghai().strftime("%Y-%m-%d %H:%M:%S %Z")

        portfolio_context = ""
        asset_type_labels = {
            "etf": "场内ETF/场内基金",
            "stock": "股票",
            "otc_fund": "场外基金",
            "cash": "现金",
            "money_fund": "货币基金",
        }
        asset_guidance = (
            "多资产分析口径:\n"
            "- 场内ETF/场内基金: 可结合指数、行业、估值、成交额、折溢价、IOPV、流动性和趋势纪律分析。\n"
            "- 股票: 重点关注公司基本面、行业景气、公告事件、单票集中度、波动和止损纪律，不要套用ETF估值百分位或IOPV规则。\n"
            "- 场外基金: 以单位净值、基金经理/策略、持仓风格、申赎规则、费用、回撤和中长期配置为主，不要使用场内实时成交、折溢价或IOPV规则。\n"
            "- 现金/货币基金: 只从流动性、备用资金、再平衡资金来源和低风险收益角度分析，不给趋势交易建议。\n"
        )
        search_instruction = (
            "回答时必须主动搜索最新公告、新闻、政策、宏观事件和品种资料，以增强回答的准确性和时效性。"
            "如果问题涉及用户持仓、股票、ETF、场内基金、场外基金、指数、行业、宏观、利率、汇率、政策、公告、新闻、市场走势或具体投资品种，"
            "需要结合持仓的资产类型生成具体搜索方向，不要只依赖历史知识或模型记忆。"
            "搜索结果不足或不可用时，需要明确说明信息不足，并把结论降级为观察性分析。"
        )
        role_context = (
            "你是多资产投资智能体中的前端浮动助手。你的职责是基于用户当前持仓、账户概况和历史对话，"
            "回答投资组合相关问题、解释已有建议、提示风险，并给出务实、可执行的下一步建议。"
            "用户持仓可能包含场内ETF/场内基金、股票、场外基金、现金和货币基金；必须先识别资产类型，再选择对应分析口径。"
        )
        if include_portfolio_context:
            portfolios = await PortfolioService.get_with_market(session, user_id=user_id)
            if portfolio_ids is not None:
                allowed_ids = {int(item) for item in portfolio_ids}
                portfolios = [item for item in portfolios if item.id in allowed_ids]
            available_cash = (
                PortfolioService._finite_float(user.account_balance)
                if user and user.account_balance is not None
                else 0.0
            )
            summary = PortfolioService.build_summary_from_portfolios(portfolios, available_cash)
            total_assets = summary.total_assets if summary.total_assets is not None else summary.total_market_value + available_cash
            portfolio_lines = []
            code_name_lines = []
            for item in portfolios:
                asset_type = getattr(item, "asset_type", "etf") or "etf"
                asset_label = asset_type_labels.get(asset_type, asset_type)
                display_name = (item.etf_name or "名称未知").strip()
                display_symbol = f"{display_name}（{item.etf_code}）" if display_name != "名称未知" else f"{item.etf_code}（名称未知）"
                current_price = f"{item.current_price:.4f}" if item.current_price is not None else "N/A"
                pnl_pct = f"{item.pnl_pct:.2f}%" if item.pnl_pct is not None else "N/A"
                market_value = f"{item.market_value:.2f}" if item.market_value is not None else "0.00"
                unit_label = "股数" if asset_type == "stock" else ("金额" if asset_type == "cash" else "份额")
                cost_label = "成本净值" if asset_type == "otc_fund" else ("单位成本" if asset_type == "stock" else "成本")
                price_label = "最新净值" if asset_type == "otc_fund" else ("账面单价" if asset_type in {"cash", "money_fund"} else "现价")
                code_name_lines.append(f"- {item.etf_code}: {display_name} | 类型 {asset_label}")
                portfolio_lines.append(
                    f"- {display_symbol} | 类型 {asset_label} | {unit_label} {item.shares:.2f} | "
                    f"{cost_label} {item.cost_price:.4f} | {price_label} {current_price} | 盈亏 {pnl_pct} | 市值 {market_value}"
                )
            portfolio_text = "\n".join(portfolio_lines) if portfolio_lines else "当前无持仓。"
            code_name_text = "\n".join(code_name_lines) if code_name_lines else "当前无持仓映射。"
            portfolio_context = (
                f"账户概况:\n"
                f"- 账户总资产: {total_assets:.2f}\n"
                f"- 持仓总市值: {summary.total_market_value:.2f}\n"
                f"- 可用现金: {available_cash:.2f}\n"
                f"- 总成本: {summary.total_cost:.2f}\n"
                f"- 总盈亏: {summary.total_pnl:.2f} ({summary.total_pnl_pct:.2f}%)\n"
                f"- 今日盈亏: {f'{summary.today_pnl:.2f} ({summary.today_pnl_pct or 0:.2f}%)' if summary.today_pnl is not None else '暂无今日行情'}\n"
                f"- 分类分布: {summary.category_distribution}\n\n"
                f"{asset_guidance}\n"
                f"标的代码名称映射（回答中引用这些标的时必须同时写名称和代码）:\n{code_name_text}\n\n"
                f"当前持仓:\n{portfolio_text}\n\n"
            )
        else:
            role_context = (
                "你是多资产投资和宏观市场分析助手。你的职责是基于用户问题和历史对话，"
                "解释股票、ETF/场内基金、场外基金、现金管理、资产配置和风险管理问题，并给出务实、可执行的分析建议。"
                "当用户没有提供持仓上下文时，不要假设用户持有什么资产。"
            )
            search_instruction = (
                "当前模式不会引用用户持仓信息。只要用户问题涉及股票、ETF、场内基金、场外基金、指数、行业、宏观、利率、汇率、政策、公告、新闻、市场走势或具体投资品种，"
                "必须主动搜索最新公告、新闻、政策、宏观事件和品种资料后再回答；不要只依赖历史知识或模型记忆。"
                "如果搜索结果不足或不可用，需要明确说明信息不足，并把结论降级为观察性分析。"
            )

        return (
            f"{role_context}"
            "不要编造不存在的持仓、资产类型、收益数据或交易限制；如果上下文里没有，就明确说没有。"
            "回答中凡引用当前持仓或上下文映射里的具体标的，必须同时输出名称和代码，优先使用“名称（代码）”格式；不要只写 159509 这类裸代码。"
            "如果标的名称未知，需要写成“代码（名称未知）”，并说明需要刷新行情或资料来补全名称。"
            "不要把股票、场外基金、现金/货币基金强行当作ETF分析；不同资产必须使用不同风险口径。"
            f"{search_instruction}"
            "回答使用简体中文，优先简洁、直接、可操作。请直接输出 Markdown 正文，不要返回 JSON、代码块外壳或 response 字段包装。"
            "如果适合，使用 Markdown 标题、项目符号、编号列表、加粗重点和分段来提升可读性；Markdown 标题（#、##、###）必须单独成行，标题前后保留空行，不要把 ## 今日结论 接在上一句话后面。\n\n"
            f"当前时间:\n"
            f"- {current_time}\n\n"
            f"{portfolio_context}"
            f"历史对话记忆:\n{history_text}\n\n"
            f"用户最新问题:\n{latest_user_message}\n\n"
            "请结合以上上下文直接作答。"
        )
