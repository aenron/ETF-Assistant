"""用户认证相关Schema"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, Union
from datetime import datetime


class UserCreate(BaseModel):
    """用户注册"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    email: Optional[str] = None
    invite_code: str = Field(..., min_length=1, description="邀请码")

    @field_validator('email', mode='before')
    @classmethod
    def validate_email(cls, v):
        if v is None or v == '':
            return None
        # 简单邮箱格式校验
        if '@' not in v or '.' not in v.split('@')[-1]:
            raise ValueError('邮箱格式不正确')
        return v


class UserLogin(BaseModel):
    """用户登录"""
    username: str
    password: str


class UserResponse(BaseModel):
    """用户信息响应"""
    id: int
    username: str
    email: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    """Token响应"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenPayload(BaseModel):
    """Token载荷"""
    sub: int  # user_id
    exp: datetime
