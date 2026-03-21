"""用户认证服务"""
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext
from jose import JWTError, jwt

from models.user import User
from schemas.user import UserCreate, UserResponse
from config import settings


# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT配置
SECRET_KEY = "your-secret-key-change-in-production"  # 生产环境应从配置读取
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7天


class AuthService:
    """用户认证服务"""
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def get_password_hash(password: str) -> str:
        """生成密码哈希"""
        return pwd_context.hash(password)
    
    @staticmethod
    def create_access_token(user_id: int, expires_delta: Optional[timedelta] = None) -> str:
        """创建访问令牌"""
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode = {"sub": user_id, "exp": expire}
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    @staticmethod
    def decode_token(token: str) -> Optional[int]:
        """解码令牌，返回用户ID"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id: int = payload.get("sub")
            if user_id:
                return user_id
        except JWTError:
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
