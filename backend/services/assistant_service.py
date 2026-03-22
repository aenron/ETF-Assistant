import json
from collections.abc import AsyncIterator

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.assistant_message import AssistantMessage
from models.user import User
from schemas.assistant import AssistantChatResponse, AssistantHistoryResponse, AssistantMessageResponse
from services.advisor_service import AdvisorService
from services.portfolio_service import PortfolioService


class AssistantService:
    """投资助手服务"""

    HISTORY_LIMIT = 20
    MEMORY_WINDOW = 12

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
    ) -> AsyncIterator[tuple[str, str | None]]:
        """优先使用原生流式，必要时降级或缓冲清洗"""
        raw_parts: list[str] = []
        buffered_prefix = ""
        mode = "pending"

        async for raw_chunk in llm.chat_stream(prompt):
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
    async def get_history(
        cls,
        session: AsyncSession,
        user_id: int,
        limit: int = HISTORY_LIMIT,
    ) -> AssistantHistoryResponse:
        result = await session.execute(
            select(AssistantMessage)
            .where(AssistantMessage.user_id == user_id)
            .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
            .limit(limit)
        )
        messages = list(reversed(result.scalars().all()))
        return AssistantHistoryResponse(
            messages=[AssistantMessageResponse.model_validate(message) for message in messages]
        )

    @classmethod
    async def clear_history(cls, session: AsyncSession, user_id: int) -> int:
        result = await session.execute(
            delete(AssistantMessage).where(AssistantMessage.user_id == user_id)
        )
        return result.rowcount or 0

    @classmethod
    async def chat(
        cls,
        session: AsyncSession,
        user_id: int,
        message: str,
    ) -> AssistantChatResponse:
        clean_message = message.strip()
        if not clean_message:
            raise ValueError("message cannot be empty")

        prompt = await cls.build_prompt(session, user_id, clean_message)
        llm = AdvisorService.get_llm_client()

        user_message = AssistantMessage(
            user_id=user_id,
            role="user",
            content=clean_message,
        )
        session.add(user_message)
        await session.flush()

        try:
            reply_text = cls.normalize_response(await llm.chat(prompt))
        except Exception as exc:
            reply_text = f"当前智能体暂时不可用，请稍后重试。错误信息：{exc}"

        assistant_message = AssistantMessage(
            user_id=user_id,
            role="assistant",
            content=reply_text,
        )
        session.add(assistant_message)
        await session.flush()

        return AssistantChatResponse(
            user_message=AssistantMessageResponse.model_validate(user_message),
            assistant_message=AssistantMessageResponse.model_validate(assistant_message),
        )

    @classmethod
    async def chat_stream(
        cls,
        session: AsyncSession,
        user_id: int,
        message: str,
    ) -> tuple[None, AsyncIterator[str]]:
        clean_message = message.strip()
        if not clean_message:
            raise ValueError("message cannot be empty")

        prompt = await cls.build_prompt(session, user_id, clean_message)
        llm = AdvisorService.get_llm_client()

        user_message = AssistantMessage(
            user_id=user_id,
            role="user",
            content=clean_message,
        )
        session.add(user_message)
        await session.flush()

        async def event_stream() -> AsyncIterator[str]:
            yield f"event: meta\ndata: {json.dumps({'user_message': AssistantMessageResponse.model_validate(user_message).model_dump(mode='json')}, ensure_ascii=False)}\n\n"

            final_text = ""
            try:
                async for event_type, payload in cls.stream_and_collect_response(llm, prompt):
                    if event_type == "chunk" and payload:
                        yield f"event: chunk\ndata: {json.dumps({'content': payload}, ensure_ascii=False)}\n\n"
                    if event_type == "done" and payload is not None:
                        final_text = payload
            except Exception as exc:
                final_text = f"当前智能体暂时不可用，请稍后重试。错误信息：{exc}"
                for chunk in cls.iter_response_chunks(final_text):
                    yield f"event: chunk\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

            assistant_message = AssistantMessage(
                user_id=user_id,
                role="assistant",
                content=final_text or "我暂时没有生成有效回复，请稍后重试。",
            )
            session.add(assistant_message)
            await session.flush()
            await session.commit()

            yield f"event: done\ndata: {json.dumps({'assistant_message': AssistantMessageResponse.model_validate(assistant_message).model_dump(mode='json')}, ensure_ascii=False)}\n\n"

        return None, event_stream()

    @classmethod
    async def build_prompt(
        cls,
        session: AsyncSession,
        user_id: int,
        latest_user_message: str,
    ) -> str:
        user = await session.get(User, user_id)
        portfolios = await PortfolioService.get_with_market(session, user_id=user_id)
        summary = await PortfolioService.get_summary(session, user_id=user_id)

        history_result = await session.execute(
            select(AssistantMessage)
            .where(AssistantMessage.user_id == user_id)
            .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
            .limit(cls.MEMORY_WINDOW)
        )
        history_messages = list(reversed(history_result.scalars().all()))

        history_text = "\n".join(
            f"{'用户' if item.role == 'user' else '助手'}: {item.content}"
            for item in history_messages
        ) or "暂无历史对话。"

        account_balance = float(user.account_balance) if user and user.account_balance is not None else 0.0
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

        return (
            "你是 ETF 投资智能体中的前端浮动助手。你的职责是基于用户当前持仓、账户概况和历史对话，"
            "回答投资组合相关问题、解释已有建议、提示风险，并给出务实、可执行的下一步建议。"
            "不要编造不存在的持仓或收益数据；如果上下文里没有，就明确说没有。"
            "回答使用简体中文，优先简洁、直接、可操作。直接输出自然语言内容，不要返回 JSON、代码块或 response 字段包装。"
            "如果适合，使用短标题、项目符号和分段来提升可读性。\n\n"
            f"账户概况:\n"
            f"- 账户余额: {account_balance:.2f}\n"
            f"- 持仓总市值: {summary.total_market_value:.2f}\n"
            f"- 总成本: {summary.total_cost:.2f}\n"
            f"- 总盈亏: {summary.total_pnl:.2f} ({summary.total_pnl_pct:.2f}%)\n"
            f"- 今日盈亏: {summary.today_pnl or 0:.2f} ({summary.today_pnl_pct or 0:.2f}%)\n"
            f"- 分类分布: {summary.category_distribution}\n\n"
            f"当前持仓:\n{portfolio_text}\n\n"
            f"历史对话记忆:\n{history_text}\n\n"
            f"用户最新问题:\n{latest_user_message}\n\n"
            "请结合以上上下文直接作答。"
        )
