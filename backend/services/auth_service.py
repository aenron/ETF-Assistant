"""用户认证服务"""
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import bcrypt
from jose import JWTError, jwt

from models.user import User
from schemas.user import UserCreate, UserResponse
from config import settings


# JWT配置
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7天


class AuthService:
    """用户认证服务"""

    @staticmethod
    def get_jwt_secret() -> str:
        """获取JWT密钥"""
        secret = settings.jwt_secret.strip()
        if not secret:
            raise RuntimeError("JWT_SECRET 未配置")
        return secret
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        password_bytes = plain_password.encode('utf-8')[:72]
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    
    @staticmethod
    def get_password_hash(password: str) -> str:
        """生成密码哈希"""
        password_bytes = password.encode('utf-8')[:72]
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    
    @staticmethod
    def create_access_token(user_id: int, expires_delta: Optional[timedelta] = None) -> str:
        """创建访问令牌"""
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        # sub 必须是字符串
        to_encode = {"sub": str(user_id), "exp": expire}
        return jwt.encode(to_encode, AuthService.get_jwt_secret(), algorithm=ALGORITHM)
    
    @staticmethod
    def decode_token(token: str) -> Optional[int]:
        """解码令牌，返回用户ID"""
        try:
            payload = jwt.decode(token, AuthService.get_jwt_secret(), algorithms=[ALGORITHM])
            print(f"[Auth] payload: {payload}")
            user_id = payload.get("sub")
            if user_id:
                return int(user_id)
        except RuntimeError:
            raise
        except (JWTError, ValueError, TypeError) as e:
            print(f"[Auth] JWT解码错误: {e}")
            return None
        return None
    
    @classmethod
    async def create_user(cls, session: AsyncSession, user_data: UserCreate) -> User:
        """创建用户"""
        # 检查用户名是否存在
        result = await session.execute(
            select(User).where(User.username == user_data.username)
        )
        if result.scalar_one_or_none():
            raise ValueError("用户名已存在")
        
        # 检查邮箱是否存在
        if user_data.email:
            result = await session.execute(
                select(User).where(User.email == user_data.email)
            )
            if result.scalar_one_or_none():
                raise ValueError("邮箱已存在")
        
        # 创建用户
        user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=cls.get_password_hash(user_data.password),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
    
    @classmethod
    async def authenticate_user(cls, session: AsyncSession, username: str, password: str) -> Optional[User]:
        """验证用户登录"""
        result = await session.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return None
        if not cls.verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            return None
        
        return user
    
    @staticmethod
    async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
        """根据ID获取用户"""
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
