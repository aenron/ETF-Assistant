"""用户认证路由"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from database import get_session
from schemas.user import UserCreate, UserLogin, UserResponse, Token, AccountBalanceUpdate
from services.auth_service import AuthService
from models.user import User
from config import settings

router = APIRouter(prefix="/api/auth", tags=["认证"])

# Bearer Token认证
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> User:
    """获取当前登录用户"""
    token = credentials.credentials

    user_id = AuthService.decode_token(token)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = await AuthService.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户已被禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    session: AsyncSession = Depends(get_session),
) -> Optional[User]:
    """获取当前登录用户（可选）"""
    if not credentials:
        return None
    
    token = credentials.credentials
    user_id = AuthService.decode_token(token)
    
    if not user_id:
        return None
    
    return await AuthService.get_user_by_id(session, user_id)


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    session: AsyncSession = Depends(get_session),
):
    """用户注册"""
    # 校验邀请码
    if not settings.invite_code or user_data.invite_code != settings.invite_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请码无效",
        )
    try:
        user = await AuthService.create_user(session, user_data)
        access_token = AuthService.create_access_token(user.id)
        
        return Token(
            access_token=access_token,
            user=UserResponse.model_validate(user),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/login", response_model=Token)
async def login(
    user_data: UserLogin,
    session: AsyncSession = Depends(get_session),
):
    """用户登录"""
    user = await AuthService.authenticate_user(session, user_data.username, user_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = AuthService.create_access_token(user.id)
    
    return Token(
        access_token=access_token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserResponse.model_validate(current_user)


@router.get("/account-balance")
async def get_account_balance(current_user: User = Depends(get_current_user)):
    """获取账户金额"""
    return {"account_balance": current_user.account_balance}


@router.put("/account-balance")
async def update_account_balance(
    data: AccountBalanceUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """更新账户金额"""
    from decimal import Decimal
    current_user.account_balance = Decimal(str(data.account_balance))
    await session.commit()
    await session.refresh(current_user)
    return {"account_balance": current_user.account_balance}
