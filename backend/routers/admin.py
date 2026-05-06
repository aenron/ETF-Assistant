"""管理员路由"""
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models.user import User
from routers.auth import get_current_admin
from schemas.user import AdminUserUpdate, UserResponse
from services.scheduler import (
    get_scheduler_job,
    list_scheduler_jobs,
    pause_scheduler_job,
    resume_scheduler_job,
    set_scheduler_job_enabled,
    trigger_scheduler_job_now,
)


router = APIRouter(
    prefix="/api/admin",
    tags=["管理员"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    session: AsyncSession = Depends(get_session),
):
    """列出全部账号"""
    result = await session.execute(select(User).order_by(User.created_at.asc(), User.id.asc()))
    return result.scalars().all()


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: AdminUserUpdate,
    session: AsyncSession = Depends(get_session),
    current_admin: User = Depends(get_current_admin),
):
    """更新账号状态、管理员角色或账户金额"""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if user.id == current_admin.id:
        if data.is_active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能禁用当前登录的管理员账号")
        if data.is_admin is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能移除当前登录账号的管理员权限")

    if data.is_active is not None:
        user.is_active = data.is_active
    if data.is_admin is not None:
        user.is_admin = data.is_admin
    if data.account_balance is not None:
        user.account_balance = Decimal(str(data.account_balance))

    await session.commit()
    await session.refresh(user)
    return user


def _require_scheduler_job(job_id: str):
    job = get_scheduler_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="定时任务不存在")
    return job


@router.get("/scheduler/jobs")
async def list_scheduler_job_status(
    session: AsyncSession = Depends(get_session),
):
    """列出后台定时任务状态"""
    from services.scheduler import ensure_scheduler_job_configs

    await ensure_scheduler_job_configs(session)
    await session.commit()
    return list_scheduler_jobs()


@router.post("/scheduler/jobs/{job_id}/run")
async def run_scheduler_job(job_id: str):
    """立即手动执行一个定时任务"""
    _require_scheduler_job(job_id)
    job = trigger_scheduler_job_now(job_id)
    return {
        "success": True,
        "message": f"任务 {job.name} 已开始手动执行",
        "job_id": job.id,
    }


@router.post("/scheduler/jobs/{job_id}/pause")
async def pause_scheduler_job_status(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """暂停一个定时任务"""
    _require_scheduler_job(job_id)
    job = pause_scheduler_job(job_id)
    await set_scheduler_job_enabled(session, job_id, False)
    await session.commit()
    return {
        "success": True,
        "message": f"任务 {job.name} 已暂停",
        "jobs": list_scheduler_jobs()["jobs"],
    }


@router.post("/scheduler/jobs/{job_id}/resume")
async def resume_scheduler_job_status(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """恢复一个定时任务"""
    _require_scheduler_job(job_id)
    job = resume_scheduler_job(job_id)
    await set_scheduler_job_enabled(session, job_id, True)
    await session.commit()
    return {
        "success": True,
        "message": f"任务 {job.name} 已恢复",
        "jobs": list_scheduler_jobs()["jobs"],
    }
