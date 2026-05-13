import json
from collections.abc import AsyncIterator

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

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

        async for raw_chunk in AdvisorService.chat_stream_with_logging(llm, prompt, context):
            if not raw_chunk:
                continue

            raw_parts.append(raw_chunk)

            if mode == "pending":
                buffered_prefix += raw_chunk
                stripped = buffered_prefix.lstrip()
                if not stripped:
                    continue
                if stripped.startswith("{") or stripped.startswith("```"):
                    mode = "buffered"
                    continue

                mode = "direct"
                yield "chunk", buffered_prefix
                buffered_prefix = ""
                continue

            if mode == "direct":
                yield "chunk", raw_chunk

        final_text = cls.normalize_response("".join(raw_parts))

        if mode in {"pending", "buffered"}:
            for chunk in cls.iter_response_chunks(final_text):
                yield "chunk", chunk

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
    ) -> AssistantChatResponse:
        conversation, user_message, prompt = await cls.prepare_user_message(
            session,
            user_id,
            session_id,
            message,
            retry_message_id=retry_message_id,
            include_portfolio_context=include_portfolio_context,
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
    async def chat_stream(
        cls,
        session: AsyncSession,
        user_id: int,
        session_id: int | None,
        message: str,
        retry_message_id: int | None = None,
        include_portfolio_context: bool = True,
    ) -> tuple[None, AsyncIterator[str]]:
        conversation, user_message, prompt = await cls.prepare_user_message(
            session,
            user_id,
            session_id,
            message,
            retry_message_id=retry_message_id,
            include_portfolio_context=include_portfolio_context,
        )
        llm = AdvisorService.get_llm_client()
        prompt = await AdvisorService.enrich_prompt_with_tavily_tools(
            llm,
            prompt,
            context=f"assistant_stream:session:{conversation.id}",
            max_calls=3,
        )

        async def event_stream() -> AsyncIterator[str]:
            yield f"event: meta\ndata: {json.dumps({'session': AssistantSessionResponse.model_validate(conversation).model_dump(mode='json'), 'user_message': AssistantMessageResponse.model_validate(user_message).model_dump(mode='json')}, ensure_ascii=False)}\n\n"

            final_text = ""
            try:
                async for event_type, payload in cls.stream_and_collect_response_with_retry(
                    llm,
                    prompt,
                    context=f"assistant_stream:session:{conversation.id}",
                ):
                    if event_type == "chunk" and payload:
                        yield f"event: chunk\ndata: {json.dumps({'content': payload}, ensure_ascii=False)}\n\n"
                    if event_type == "done" and payload is not None:
                        final_text = payload
            except Exception as exc:
                final_text = f"当前智能体暂时不可用，请稍后重试。错误信息：{exc}"
                for chunk in cls.iter_response_chunks(final_text):
                    yield f"event: chunk\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

            assistant_message = AssistantSessionMessage(
                session_id=conversation.id,
                user_id=user_id,
                role="assistant",
                content=final_text or "我暂时没有生成有效回复，请稍后重试。",
            )
            session.add(assistant_message)
            await session.flush()
            await cls.touch_session(conversation, assistant_message.content)
            await session.commit()

            yield f"event: done\ndata: {json.dumps({'session': AssistantSessionResponse.model_validate(conversation).model_dump(mode='json'), 'assistant_message': AssistantMessageResponse.model_validate(assistant_message).model_dump(mode='json')}, ensure_ascii=False)}\n\n"

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
        search_instruction = (
            "回答时必须主动搜索最新公告、新闻、政策和宏观事件，以增强回答的准确性和时效性。"
            "如果问题涉及用户持仓、ETF、指数、行业、宏观、利率、汇率、政策、公告、新闻、市场走势或具体投资品种，"
            "需要结合持仓上下文生成具体搜索方向，不要只依赖历史知识或模型记忆。"
            "搜索结果不足或不可用时，需要明确说明信息不足，并把结论降级为观察性分析。"
        )
        role_context = (
            "你是 ETF 投资智能体中的前端浮动助手。你的职责是基于用户当前持仓、账户概况和历史对话，"
            "回答投资组合相关问题、解释已有建议、提示风险，并给出务实、可执行的下一步建议。"
        )
        if include_portfolio_context:
            portfolios = await PortfolioService.get_with_market(session, user_id=user_id)
            available_cash = (
                PortfolioService._finite_float(user.account_balance)
                if user and user.account_balance is not None
                else 0.0
            )
            summary = PortfolioService.build_summary_from_portfolios(portfolios, available_cash)
            total_assets = summary.total_assets if summary.total_assets is not None else summary.total_market_value + available_cash
            portfolio_lines = []
            for item in portfolios:
                current_price = f"{item.current_price:.4f}" if item.current_price is not None else "N/A"
                pnl_pct = f"{item.pnl_pct:.2f}%" if item.pnl_pct is not None else "N/A"
                market_value = f"{item.market_value:.2f}" if item.market_value is not None else "0.00"
                portfolio_lines.append(
                    f"- {item.etf_code} {item.etf_name or ''} | 份额 {item.shares:.2f} | "
                    f"成本 {item.cost_price:.4f} | 现价 {current_price} | 盈亏 {pnl_pct} | 市值 {market_value}"
                )
            portfolio_text = "\n".join(portfolio_lines) if portfolio_lines else "当前无持仓。"
            portfolio_context = (
                f"账户概况:\n"
                f"- 账户总资产: {total_assets:.2f}\n"
                f"- 持仓总市值: {summary.total_market_value:.2f}\n"
                f"- 可用现金: {available_cash:.2f}\n"
                f"- 总成本: {summary.total_cost:.2f}\n"
                f"- 总盈亏: {summary.total_pnl:.2f} ({summary.total_pnl_pct:.2f}%)\n"
                f"- 今日盈亏: {f'{summary.today_pnl:.2f} ({summary.today_pnl_pct or 0:.2f}%)' if summary.today_pnl is not None else '暂无今日行情'}\n"
                f"- 分类分布: {summary.category_distribution}\n\n"
                f"当前持仓:\n{portfolio_text}\n\n"
            )
        else:
            role_context = (
                "你是 ETF 和宏观市场投资分析助手。你的职责是基于用户问题和历史对话，"
                "解释市场、行业、ETF、资产配置和风险管理问题，并给出务实、可执行的分析建议。"
            )
            search_instruction = (
                "当前模式不会引用用户持仓信息。只要用户问题涉及 ETF、指数、行业、宏观、利率、汇率、政策、公告、新闻、市场走势或具体投资品种，"
                "必须主动搜索最新公告、新闻、政策和宏观事件后再回答；不要只依赖历史知识或模型记忆。"
                "如果搜索结果不足或不可用，需要明确说明信息不足，并把结论降级为观察性分析。"
            )

        return (
            f"{role_context}"
            "不要编造不存在的持仓或收益数据；如果上下文里没有，就明确说没有。"
            f"{search_instruction}"
            "回答使用简体中文，优先简洁、直接、可操作。请直接输出 Markdown 正文，不要返回 JSON、代码块外壳或 response 字段包装。"
            "如果适合，使用 Markdown 标题、项目符号、编号列表、加粗重点和分段来提升可读性。\n\n"
            f"当前时间:\n"
            f"- {current_time}\n\n"
            f"{portfolio_context}"
            f"历史对话记忆:\n{history_text}\n\n"
            f"用户最新问题:\n{latest_user_message}\n\n"
            "请结合以上上下文直接作答。"
        )
